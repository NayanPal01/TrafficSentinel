"""FastAPI server for TrafficSentinel AI DSS Dashboard.

Complete backend providing 100% of feature set from app.py:
  - GET  /stream                  MJPEG live video stream
  - WS   /ws/events               Real-time WebSocket event stream (ANPR + Violations)
  - GET  /api/stats               Live FPS, track count, violation counts
  - GET  /api/violations          Historical violations from SQLite database
  - GET  /api/events              Recent combined ANPR & violation events
  - GET  /api/review              Pending review queue violations with evidence & clip paths
  - POST /api/review/action       Approve/issue or dismiss violation challan
  - POST /api/review/clear-all    Clear all logs and evidence files
  - GET  /api/analytics           Analytics stats, fines in INR, violation distribution
  - GET  /api/anpr/trace          Multi-camera vehicle passage trajectory by plate
  - GET  /api/calibration         Spatial calibration checks (homography, stop line, zones)
  - POST /api/source              Change video source (webcam / file / RTSP)
  - POST /api/settings            Update system & rule configuration parameters
  - POST /api/alerts/test         Send test Telegram police alert
  - GET  /evidence/{path}         Serve evidence snapshots and plate crop images
"""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

# Auto-relaunch inside project virtual environment if invoked with global Python
_venv_python = Path(__file__).resolve().parent / ".venv" / "Scripts" / "python.exe"
if _venv_python.exists() and sys.executable.lower() != str(_venv_python).lower():
    sys.exit(subprocess.call([str(_venv_python)] + sys.argv))

import asyncio
import json
import logging
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Dict, List, Set, Optional

import cv2
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Body, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import AppConfig, VIOLATION_META, AlertConfig
from core.database import Database
from core.engine import TrafficSentinel
from core.video_source import VideoSource
from core.alerts import TelegramAlertService
from core.road_network import RoadNetwork
from core.tracking_engine import MultiCameraTracker

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

app = FastAPI(title="TrafficSentinel AI API", version="2.0.0")

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

CONFIG_PATH = "camera.json"
cfg = AppConfig.load(CONFIG_PATH)
db = Database(cfg.db_path)
road_network = RoadNetwork()

# Global engine & pipeline state
lock = threading.Lock()
engine = TrafficSentinel(cfg, fps=25.0)
video_src: Optional[VideoSource] = None
pipeline_active = False

# Latest processed frame & state for streaming
current_frame_bytes: bytes | None = None
latest_raw_frame: np.ndarray | None = None
latest_render_payload: tuple | None = None
latest_hud: dict = {}
websocket_clients: Set[WebSocket] = set()
loop: asyncio.AbstractEventLoop | None = None

# Enabled rules state
enabled_rules = {vtype: True for vtype in VIOLATION_META}
show_clean_vehicles = True

# Background processing loop
processing_running = True


def processing_worker():
    global current_frame_bytes, latest_raw_frame, latest_render_payload, latest_hud, engine, video_src, processing_running, pipeline_active

    logger.info("Processing worker thread started (waiting for manual start/upload)")
    prev_frame_idx = -1

    while processing_running:
        try:
            if video_src is None or not video_src.running:
                current_frame_bytes = None
                time.sleep(0.1)
                continue

            if not pipeline_active:
                # Video paused: hold current frame on screen
                time.sleep(0.08)
                continue

            ok, frame, frame_idx = video_src.read()
            if not ok or frame is None:
                time.sleep(0.02)
                continue

            # Detect video loop/rewind and clear stale cooldowns so detections refresh on loop
            if prev_frame_idx > 30 and frame_idx < (prev_frame_idx - 30):
                logger.info("Video looped to beginning: refreshing vehicle tracking & cooldowns.")
                engine.detector.reset_tracks()
                engine.registry.tracks.clear()
                engine._plate_violation_cooldown.clear()
                engine._recent_violation_boxes.clear()
                engine._anpr_broadcast_cooldown.clear()
            prev_frame_idx = frame_idx

            latest_raw_frame = frame.copy()

            # Update live rule toggles on engine
            engine.cfg = cfg
            engine.annotator.show_clean = show_clean_vehicles
            for vtype, on in enabled_rules.items():
                engine.rules.set_enabled(vtype, on)

            # High-performance detection loop: decoupled from HUD drawing & JPEG encoding
            res = engine.process(frame, frame_idx=frame_idx, draw=False)
            latest_hud = res.get("hud", {})
            latest_render_payload = (
                frame,
                res.get("graph"),
                res.get("violations"),
                latest_hud,
                list(getattr(engine, "_latest_plate_boxes", []))
            )

            # Broadcast new violations over WebSocket and register in tracking engine
            new_v = res.get("new_violations", [])
            if new_v:
                for v in new_v:
                    plate = v.get("plate")
                    if plate and plate != "UNREAD":
                        spd = v.get("speed_kmh") or 40.0
                        logger.info(f"[Live Violation OCR] Auto-registering plate {plate} at {cfg.geometry.camera_id} (speed: {spd:.1f} km/h)")
                        tracking_engine.register_sighting(
                            plate=plate,
                            camera_id=cfg.geometry.camera_id,
                            speed_kmh=spd,
                            ts=time.time()
                        )
                if loop and websocket_clients:
                    for v in new_v:
                        plate_img = v.get("plate_img") or ""
                        if "/crops/" in plate_img:
                            plate_img = ""
                        if plate_img:
                            plate_img = "/" + plate_img.replace("\\", "/").lstrip("/")
                        event_payload = {
                            "type": "violation",
                            "id": f"v_{v.get('track_id', 0)}_{frame_idx}",
                            "plate": v.get("plate") or "UNREAD",
                            "vehicleType": v.get("vehicle_type") or "Vehicle",
                            "vehicleColor": "Unknown",
                            "source": cfg.geometry.camera_id,
                            "timestamp": time.strftime("%Y-%m-%d  %H:%M:%S"),
                            "violation": v.get("type") or v.get("rule"),
                            "plateImg": plate_img,
                            "evidenceImg": ("/" + v.get("crop_path", "").replace("\\", "/").lstrip("/")) if v.get("crop_path") else "",
                            "fine": v.get("fine"),
                            "status": v.get("status"),
                        }
                        asyncio.run_coroutine_threadsafe(
                            broadcast_event(event_payload), loop
                        )

            # Broadcast pure ANPR detections over WebSocket and register in tracking engine
            anpr_events = res.get("anpr_events", [])
            if anpr_events:
                for ae in anpr_events:
                    p = ae.get("plate")
                    if p:
                        spd = ae.get("speed_kmh") or 40.0
                        logger.info(f"[Live ANPR OCR] Auto-registering plate {p} at {cfg.geometry.camera_id} (speed: {spd:.1f} km/h)")
                        tracking_engine.register_sighting(
                            plate=p,
                            camera_id=cfg.geometry.camera_id,
                            speed_kmh=spd,
                            ts=time.time()
                        )
                if loop and not loop.is_closed() and websocket_clients:
                    for ae in anpr_events:
                        p_img = ae.get("plate_img") or ""
                        if "/crops/" in p_img:
                            p_img = ""
                        if p_img:
                            p_img = "/" + p_img.replace("\\", "/").lstrip("/")

                        # Check if vehicle has an active violation
                        tid = ae.get("track_id", 0)
                        viol_match = None
                        for item in engine.live_violations:
                            if item.get("track_id") == tid and item.get("type") not in ("ANPR_DETECT", "VEHICLE"):
                                viol_match = item
                                break

                        if viol_match:
                            crop_p = viol_match.get("crop_path") or viol_match.get("evidence") or ""
                            if crop_p and not crop_p.startswith("/"):
                                crop_p = "/" + crop_p.replace("\\", "/").lstrip("/")
                            ae_payload = {
                                "type": "violation",
                                "id": f"v_{tid}_{int(time.time() * 100) % 100000}",
                                "plate": ae.get("plate"),
                                "vehicleType": ae.get("vehicle_type") or "Vehicle",
                                "vehicleColor": "Unknown",
                                "source": cfg.geometry.camera_id,
                                "timestamp": time.strftime("%Y-%m-%d  %H:%M:%S"),
                                "violation": viol_match.get("type"),
                                "plateImg": p_img,
                                "evidenceImg": crop_p,
                                "fine": viol_match.get("fine"),
                                "status": viol_match.get("status", "issued"),
                            }
                        else:
                            ae_payload = {
                                "type": "anpr_detect",
                                "id": f"anpr_{tid}_{int(time.time() * 100) % 100000}",
                                "plate": ae.get("plate"),
                                "vehicleType": ae.get("vehicle_type") or "Vehicle",
                                "vehicleColor": "Unknown",
                                "source": cfg.geometry.camera_id,
                                "timestamp": time.strftime("%Y-%m-%d  %H:%M:%S"),
                                "violation": None,
                                "plateImg": p_img,
                                "fine": None,
                                "status": "detected",
                            }

                        asyncio.run_coroutine_threadsafe(
                            broadcast_event(ae_payload), loop
                        )

            # Broadcast blacklist hits over WebSocket
            bl_hits = res.get("blacklist_hits", [])
            if bl_hits and loop and websocket_clients:
                for bh in bl_hits:
                    bl_payload = {
                        "type": "blacklist_hit",
                        "plate": bh.get("plate"),
                        "reason": bh.get("reason"),
                        "severity": bh.get("severity"),
                        "camera_id": bh.get("camera_id"),
                        "timestamp": time.strftime("%Y-%m-%d  %H:%M:%S"),
                    }
                    asyncio.run_coroutine_threadsafe(
                        broadcast_event(bl_payload), loop
                    )

            # Broadcast anomaly hits over WebSocket
            anom_hits = res.get("anomaly_hits", [])
            if anom_hits and loop and websocket_clients:
                for ah in anom_hits:
                    anom_payload = {
                        "type": "anomaly_hit",
                        "plate": ah.get("plate"),
                        "anomaly_type": ah.get("type"),
                        "description": ah.get("description"),
                        "camera_id": ah.get("camera_id"),
                        "severity": ah.get("severity", "critical"),
                        "timestamp": time.strftime("%Y-%m-%d  %H:%M:%S"),
                    }
                    asyncio.run_coroutine_threadsafe(
                        broadcast_event(anom_payload), loop
                    )

            target_dt = 1.0 / max(5.0, video_src.fps)
            time.sleep(max(0.001, target_dt - 0.005))

        except Exception as exc:
            logger.error(f"Error in processing worker: {exc}")
            time.sleep(0.05)


worker_thread = threading.Thread(target=processing_worker, daemon=True)
worker_thread.start()


# Dedicated streaming worker: renders HUD and compresses JPEG at a steady 15 FPS
# without stalling the high-throughput detection pipeline
def mjpeg_encoder_worker():
    global current_frame_bytes
    last_render = 0.0
    interval = 1.0 / 15.0  # Smooth 15 FPS dashboard display stream

    while processing_running:
        try:
            now = time.time()
            if now - last_render < interval:
                time.sleep(0.008)
                continue

            payload = latest_render_payload
            if payload is not None and engine is not None:
                frame_snap, graph_snap, violations_snap, hud_snap, pboxes_snap = payload
                annotated = engine.annotator.draw(
                    frame_snap.copy(), graph_snap, violations_snap,
                    engine.registry, hud_snap, plate_boxes=pboxes_snap
                )
                ok_enc, jpeg = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
                if ok_enc:
                    current_frame_bytes = jpeg.tobytes()
                    last_render = now
            elif video_src is None or not getattr(video_src, "running", False):
                current_frame_bytes = None
            time.sleep(0.008)
        except Exception as exc:
            logger.error(f"Error in mjpeg_encoder_worker: {exc}")
            time.sleep(0.02)

mjpeg_worker_thread = threading.Thread(target=mjpeg_encoder_worker, daemon=True)
mjpeg_worker_thread.start()


@app.on_event("startup")
async def startup_event():
    global loop, video_src, pipeline_active
    loop = asyncio.get_running_loop()
    # Server starts in standby: wait for manual user video upload
    video_src = None
    pipeline_active = False
    logger.info("Server started in standby (waiting for manual video upload)")


async def broadcast_event(data: dict):
    clients = list(websocket_clients)
    if not clients:
        return

    async def _send(ws: WebSocket):
        try:
            await ws.send_json(data)
            return None
        except Exception:
            return ws

    results = await asyncio.gather(*[_send(ws) for ws in clients], return_exceptions=True)
    for res in results:
        if isinstance(res, WebSocket):
            websocket_clients.discard(res)


def on_tracking_event(event_data: dict):
    if loop and websocket_clients:
        asyncio.run_coroutine_threadsafe(broadcast_event(event_data), loop)

tracking_engine = MultiCameraTracker(road_network, on_event_callback=on_tracking_event)

def tracking_tick_worker():
    while processing_running:
        try:
            tracking_engine.tick()
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Tracking tick worker error: {e}")
            time.sleep(1.0)

tracking_worker_thread = threading.Thread(target=tracking_tick_worker, daemon=True)
tracking_worker_thread.start()


# Pre-rendered standby JPEG shown when video stream is idle
def _create_standby_frame():
    import numpy as np
    img = np.zeros((480, 854, 3), dtype=np.uint8)
    img[:] = (22, 28, 40)  # Sleek dark background matching dashboard #161c28
    cv2.putText(img, "TRAFFICSENTINEL AI", (270, 220),
                cv2.FONT_HERSHEY_SIMPLEX, 0.85, (0, 210, 255), 2, cv2.LINE_AA)
    cv2.putText(img, "SYSTEM STANDBY - UPLOAD VIDEO TO START", (220, 265),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 174, 192), 1, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes()

STANDBY_JPEG = _create_standby_frame()


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.get("/stream")
def video_stream():
    """MJPEG stream endpoint for live video feed."""
    def generate():
        while True:
            frame = current_frame_bytes if current_frame_bytes is not None else STANDBY_JPEG
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
            time.sleep(0.04)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    await websocket.accept()
    websocket_clients.add(websocket)
    logger.info(f"WebSocket client connected ({len(websocket_clients)} total)")
    try:
        init_events = get_recent_events(limit=25)
        for ev in reversed(init_events):
            await websocket.send_json(ev)
    except Exception as e:
        logger.debug(f"Initial WS events push note: {e}")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        websocket_clients.discard(websocket)
        logger.info("WebSocket client disconnected")


class TogglePayload(BaseModel):
    run: bool


@app.get("/api/stats")
def get_stats():
    """Return real-time pipeline performance and track stats."""
    return {
        "pipeline_active": pipeline_active,
        "fps": round(latest_hud.get("fps", 0.0), 1) if pipeline_active else 0.0,
        "infer_ms": round(latest_hud.get("infer_ms", 0.0), 1) if pipeline_active else 0.0,
        "active_tracks": latest_hud.get("tracks", 0) if pipeline_active else 0,
        "ocr_backlog": latest_hud.get("ocr_backlog", 0) if pipeline_active else 0,
        "camera_id": latest_hud.get("camera_id", cfg.geometry.camera_id),
        "light": latest_hud.get("light", "GREEN"),
    }


@app.post("/api/pipeline/toggle")
def toggle_pipeline(payload: TogglePayload):
    global pipeline_active, video_src
    pipeline_active = payload.run
    return {"status": "success", "pipeline_active": pipeline_active}


@app.get("/api/live-logs")
def get_live_logs():
    """Returns real-time live detection logs dataframe rows.
    Combines:
      1. Recent detected violations & ANPR reads from engine.live_violations
      2. Currently active vehicles tracked in the camera feed
    """
    rows = []
    seen_track_ids = set()

    # 1. Primary: recent violations & ANPR plate detections
    for v in list(engine.live_violations)[:20]:
        tid = v.get("track_id")
        seen_track_ids.add(tid)
        tr_obj = engine.registry.get(tid)
        live_p = (tr_obj.plate if tr_obj and tr_obj.plate else v.get("plate")) or "-"
        if live_p == "UNREAD":
            live_p = "-"

        try:
            conf_str = f"{float(v.get('confidence', 0.0)):.2f}"
        except Exception:
            conf_str = "0.90"

        fine_val = v.get("fine")
        fine_str = f"Rs {fine_val}" if fine_val and fine_val > 0 else "-"

        reasons = v.get("reasons", [])
        if isinstance(reasons, list):
            reason_str = " | ".join(str(r) for r in reasons[:2])
        else:
            reason_str = str(reasons)

        rows.append({
            "type": v.get("type", "UNKNOWN"),
            "track_id": tid,
            "plate": live_p,
            "conf": conf_str,
            "status": v.get("status", "detected"),
            "fine": fine_str,
            "reasons": reason_str,
            "is_violation": v.get("type") not in ("ANPR_DETECT", "VEHICLE"),
        })

    # 2. Secondary: Currently active tracked vehicles on road not yet in logs
    for tid, tr in list(engine.registry.tracks.items()):
        if tid in seen_track_ids:
            continue
        if len(rows) >= 25:
            break

        spd = tr.effective_speed_kmh(default_speed=float(cfg.rules.speed_limit_kmh))
        plate_display = tr.plate if tr.plate else "SCANNING..."
        status_display = "verified" if tr.plate else "tracking"
        vtype = tr.label.upper() if tr.label else "VEHICLE"

        rows.append({
            "type": vtype,
            "track_id": tid,
            "plate": plate_display,
            "conf": f"{float(tr.conf):.2f}" if tr.conf else "0.85",
            "status": status_display,
            "fine": "-",
            "reasons": f"Speed {spd:.1f} km/h | Active on CAM",
            "is_violation": False,
        })

    return rows


def find_plate_crop(plate_norm: str) -> str:
    """Locate matching tight license plate crop on disk if available."""
    if not plate_norm or plate_norm in ("UNREAD", "-"):
        return ""
    plates_dir = Path("evidence/plates")
    if not plates_dir.exists():
        return ""
    for f in plates_dir.glob(f"*_{plate_norm}_*.jpg"):
        return f"/evidence/plates/{f.name}"
    for f in plates_dir.glob(f"*{plate_norm}*.jpg"):
        return f"/evidence/plates/{f.name}"
    return ""


@app.get("/api/events")
def get_recent_events(limit: int = 50):
    """Returns recent unified ANPR and violation events for live sidebar feeds."""
    events = []
    seen_plates = set()

    # 1. From active engine.live_violations (real-time in memory)
    for v in list(engine.live_violations):
        plate = v.get("plate")
        if not plate or plate in ("-", "UNREAD"):
            continue
        p_norm = "".join(c for c in plate.upper() if c.isalnum())
        if p_norm in seen_plates:
            continue
        seen_plates.add(p_norm)

        is_viol = (v.get("type") not in ("ANPR_DETECT", "VEHICLE"))
        p_img = v.get("plate_img") or ""
        if "/crops/" in p_img:
            p_img = ""
        if not p_img:
            p_img = find_plate_crop(p_norm)
        if p_img and not p_img.startswith("/"):
            p_img = "/" + p_img.replace("\\", "/").lstrip("/")

        ev_img = v.get("crop_path") or v.get("evidence") or ""
        if ev_img and not ev_img.startswith("/"):
            ev_img = "/" + ev_img.replace("\\", "/").lstrip("/")

        events.append({
            "type": "violation" if is_viol else "anpr_detect",
            "id": f"live_{v.get('track_id', 0)}_{p_norm}",
            "plate": plate,
            "vehicleType": v.get("vehicle_type") or "Vehicle",
            "vehicleColor": "Unknown",
            "source": cfg.geometry.camera_id,
            "timestamp": time.strftime("%Y-%m-%d  %H:%M:%S"),
            "violation": v.get("type") if is_viol else None,
            "plateImg": p_img,
            "evidenceImg": ev_img,
            "fine": v.get("fine") if is_viol else None,
            "status": v.get("status", "detected"),
        })
        if len(events) >= limit:
            break

    # 2. Backfill from database sightings and violations if live list has room
    if len(events) < limit:
        sightings = db.query(
            "SELECT * FROM sightings ORDER BY ts DESC LIMIT ?",
            (limit * 2,)
        )
        for s in sightings:
            plate = s["plate_number"]
            p_norm = s["plate_norm"]
            if not p_norm or p_norm in seen_plates:
                continue
            seen_plates.add(p_norm)

            viols = db.query(
                "SELECT * FROM violations WHERE plate_number=? ORDER BY ts DESC LIMIT 1",
                (plate,)
            )
            is_viol = bool(viols)
            viol_type = viols[0]["violation_type"] if is_viol else None
            fine_val = viols[0]["fine_amount"] if is_viol else None
            status_val = viols[0]["status"] if is_viol else "detected"
            crop_p = viols[0]["evidence_path"] if is_viol else ""
            if crop_p and not crop_p.startswith("/"):
                crop_p = "/" + crop_p.replace("\\", "/").lstrip("/")

            p_img = find_plate_crop(p_norm)
            ts_str = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(s["ts"]))
            cam_src = s["camera_id"] or cfg.geometry.camera_id

            events.append({
                "type": "violation" if is_viol else "anpr_detect",
                "id": f"db_{s['sighting_id']}_{p_norm}",
                "plate": plate,
                "vehicleType": "Vehicle",
                "vehicleColor": "Unknown",
                "source": cam_src,
                "timestamp": ts_str,
                "violation": viol_type,
                "plateImg": p_img,
                "evidenceImg": crop_p,
                "fine": fine_val,
                "status": status_val,
            })
            if len(events) >= limit:
                break

    # 3. Backfill from database violations (in case violation logged without sighting)
    if len(events) < limit:
        viols_db = db.query(
            "SELECT * FROM violations ORDER BY ts DESC LIMIT ?",
            (limit,)
        )
        for v in viols_db:
            plate = v["plate_number"]
            if not plate or plate in ("-", "UNREAD"):
                continue
            p_norm = "".join(c for c in plate.upper() if c.isalnum())
            if not p_norm or p_norm in seen_plates:
                continue
            seen_plates.add(p_norm)

            crop_p = v["evidence_path"] or ""
            if crop_p and not crop_p.startswith("/"):
                crop_p = "/" + crop_p.replace("\\", "/").lstrip("/")

            p_img = find_plate_crop(p_norm)
            ts_str = time.strftime("%Y-%m-%d  %H:%M:%S", time.localtime(v["ts"]))
            cam_src = v["camera_id"] or cfg.geometry.camera_id

            events.append({
                "type": "violation",
                "id": f"db_viol_{v['violation_id']}_{p_norm}",
                "plate": plate,
                "vehicleType": "Vehicle",
                "vehicleColor": "Unknown",
                "source": cam_src,
                "timestamp": ts_str,
                "violation": v["violation_type"],
                "plateImg": p_img,
                "evidenceImg": crop_p,
                "fine": v["fine_amount"],
                "status": v["status"],
            })
            if len(events) >= limit:
                break

    return events


@app.post("/api/upload-video")
def upload_video(file: UploadFile = File(...)):
    """Upload custom video file and set as active source."""
    global video_src, pipeline_active
    # Stop existing source first to release Windows file handle lock on _upload.mp4
    if video_src is not None:
        try:
            video_src.stop()
        except Exception:
            pass
        video_src = None
        time.sleep(0.1)

    dest_path = Path("_upload.mp4")
    with dest_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    engine.reset()
    video_src = VideoSource(str(dest_path), realtime=False).start()
    pipeline_active = True
    return {"status": "success", "filename": file.filename, "source": str(dest_path), "pipeline_active": True}


class SourcePayload(BaseModel):
    kind: str  # "upload", "webcam", "rtsp"
    source: Optional[str] = None


@app.post("/api/source")
def set_video_source(payload: SourcePayload):
    """Explicitly switch video source between Upload file, Webcam index, or RTSP CCTV stream."""
    global video_src, pipeline_active
    if video_src is not None:
        try:
            video_src.stop()
        except Exception:
            pass

    realtime = True
    src_val: str | int = 0

    if payload.kind == "upload":
        src_val = payload.source or "_upload.mp4"
        realtime = False
    elif payload.kind == "webcam":
        src_val = int(payload.source) if payload.source and payload.source.isdigit() else 0
        realtime = True
    elif payload.kind == "rtsp":
        src_val = payload.source or "rtsp://127.0.0.1:554/live"
        realtime = True

    engine.reset()
    video_src = VideoSource(src_val, realtime=realtime).start()
    pipeline_active = True
    return {"status": "success", "kind": payload.kind, "source": str(src_val), "pipeline_active": True}


@app.get("/api/violations")
def get_violations(limit: int = 100):
    rows = db.fetch_all(limit=limit)
    return [
        {
            "id": r[0],
            "track_id": r[1],
            "plate": r[2] or "UNREAD",
            "rule": r[3],
            "speed_kph": r[4],
            "crop_path": r[5],
            "evidence_mp4": r[6],
            "timestamp": r[7],
        }
        for r in rows
    ]


@app.get("/api/review")
def get_review_queue(limit: int = 100):
    """Fetch pending review queue violations (status='review')."""
    rows = db.recent(limit=limit, status="review")
    return [dict(r) for r in rows]


class ActionPayload(BaseModel):
    violation_id: int
    action: str  # "issue" or "dismiss"
    verified_plate: Optional[str] = None


@app.post("/api/review/action")
def handle_review_action(payload: ActionPayload):
    """Approve challan or dismiss false positive."""
    if payload.verified_plate:
        db_conn = db._connect()
        db_conn.execute(
            "UPDATE violations SET plate_number=? WHERE violation_id=?",
            (payload.verified_plate.strip().upper(), payload.violation_id)
        )
        db_conn.commit()
        db_conn.close()

    new_status = "issued" if payload.action == "issue" else "dismissed"
    db.set_status(payload.violation_id, new_status)
    return {"status": "success", "violation_id": payload.violation_id, "new_status": new_status}


@app.post("/api/review/clear-all")
def clear_all_logs():
    """Clear all violation logs, sightings, and evidence clips."""
    engine.reset()
    db_inst = Database(cfg.db_path, async_writes=False)
    db_inst.clear_all(clear_evidence=True)
    return {"status": "success", "message": "All logs and evidence deleted."}


@app.get("/api/analytics")
def get_analytics():
    """Full analytics breakdown: totals, fines in INR, violation distribution."""
    stats = db.stats()
    rows = db.query(
        "SELECT violation_type, COUNT(*) c FROM violations "
        "GROUP BY violation_type ORDER BY c DESC"
    )
    breakdown = [dict(r) for r in rows] if rows else []

    # Calculate total fine revenue breakdown
    fine_breakdown = {}
    for item in breakdown:
        vtype = item["violation_type"]
        meta = VIOLATION_META.get(vtype, {"fine": 0})
        fine_breakdown[vtype] = {
            "count": item["c"],
            "fine_per_item": meta["fine"],
            "total_fine": item["c"] * meta["fine"]
        }

    return {
        "stats": stats,
        "violation_types": breakdown,
        "fine_breakdown": fine_breakdown,
        "violation_meta": VIOLATION_META,
    }


@app.get("/api/anpr/trace")
def trace_vehicle(plate: str):
    """Trace vehicle route checkpoints across camera nodes."""
    if not plate:
        return {"error": "Plate parameter required"}

    rows = db.vehicle_route(plate.upper())
    if not rows:
        return {"plate": plate, "sightings": []}

    sightings = [dict(r) for r in rows]
    return {"plate": plate.upper(), "total_checkpoints": len(sightings), "sightings": sightings}


@app.get("/api/calibration")
def get_calibration():
    """Return spatial calibration status checks."""
    g = cfg.geometry
    return {
        "camera_id": g.camera_id,
        "latitude": g.latitude,
        "longitude": g.longitude,
        "homography": bool(g.homography_src),
        "stop_line": bool(g.stop_line),
        "lane_direction": g.lane_direction != [0.0, -1.0],
        "no_parking_zones": bool(g.no_parking_zones),
    }


# ------------------------------------------------------------------ #
# Blacklist API
# ------------------------------------------------------------------ #

class BlacklistPayload(BaseModel):
    plate: str
    reason: str = ""
    severity: str = "high"


@app.get("/api/blacklist")
def get_blacklist():
    return db.get_blacklist()


@app.post("/api/blacklist")
def add_to_blacklist(payload: BlacklistPayload):
    ok = db.add_blacklist(payload.plate, payload.reason, payload.severity)
    return {"status": "success" if ok else "failed", "plate": payload.plate}


@app.delete("/api/blacklist/{plate}")
def remove_from_blacklist(plate: str):
    db.remove_blacklist(plate)
    return {"status": "success", "plate": plate}


@app.post("/api/blacklist/import")
async def import_blacklist_file(file: UploadFile = File(...)):
    """Import blacklist plates from a CSV or text file."""
    content = await file.read()
    text = content.decode("utf-8", errors="ignore")
    imported = 0
    import csv, io
    reader = csv.reader(io.StringIO(text))
    for row in reader:
        if not row or not row[0].strip() or row[0].strip().startswith("#"):
            continue
        # Support headers: plate, reason, severity
        plate = row[0].strip()
        if plate.lower() in ("plate", "license_plate", "plate_number"):
            continue
        reason = row[1].strip() if len(row) > 1 else "Flagged vehicle"
        severity = row[2].strip() if len(row) > 2 else "high"
        if db.add_blacklist(plate, reason, severity):
            imported += 1
    return {"status": "success", "imported_count": imported}


# ------------------------------------------------------------------ #
# OCR Accuracy API
# ------------------------------------------------------------------ #

@app.get("/api/analytics/ocr-accuracy")
def get_ocr_accuracy():
    return db.ocr_accuracy_stats()


# ------------------------------------------------------------------ #
# Flow / Heatmap / Congestion / O-D Matrix API
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
# Junction and Midway Cameras API
# ------------------------------------------------------------------ #

@app.get("/api/cameras")
def get_cameras():
    """Return all known junction, midway, and custom camera positions."""
    cams = db.get_all_cameras()
    if not cams:
        db._init_schema()
        cams = db.get_all_cameras()

    result = []
    active_cid = cfg.geometry.camera_id
    for c in cams:
        result.append({
            "id": c["camera_id"],
            "name": c["name"],
            "kind": c.get("kind", "junction"),
            "lat": c["latitude"],
            "lon": c["longitude"],
            "active": (c["camera_id"] == active_cid),
        })
    return result


class CameraPayload(BaseModel):
    id: str
    name: str
    kind: str = "junction"  # "junction" or "midway"
    lat: float
    lon: float


@app.post("/api/cameras")
def add_camera_endpoint(payload: CameraPayload):
    """Add a manual camera at a junction or midway point."""
    db.add_camera(payload.id, payload.name, payload.kind, payload.lat, payload.lon, 0)
    return {"status": "success", "camera": payload.model_dump()}


@app.delete("/api/cameras/{camera_id}")
def delete_camera_endpoint(camera_id: str):
    """Remove any camera node."""
    db.delete_camera(camera_id)
    return {"status": "success", "camera_id": camera_id}


# ------------------------------------------------------------------ #
# Flow Analytics: Heatmap, Timeseries, Congestion, OD Matrix
# ------------------------------------------------------------------ #

@app.get("/api/flow/heatmap")
def get_flow_heatmap():
    """Vehicle density per camera for Leaflet heatmap layer."""
    flow_data = db.flow_heatmap_data()
    cams = {c["id"]: (c["lat"], c["lon"]) for c in get_cameras()}

    result = []
    for f in flow_data:
        cid = f["camera_id"]
        lat, lon = cams.get(cid, (cfg.geometry.latitude, cfg.geometry.longitude))
        result.append({
            "camera_id": cid,
            "lat": lat, "lon": lon,
            "total_vehicles": f["total_vehicles"] or 0,
            "avg_speed": round(f["avg_speed"] or 0, 1),
            "intensity": min(max((f["total_vehicles"] or 0) / 120.0, 0.25), 1.0),
        })
    return result


@app.get("/api/flow/timeseries")
def get_flow_timeseries(camera_id: str = None, hours: int = 24):
    return db.flow_timeseries(camera_id, hours)


@app.get("/api/flow/congestion")
def get_congestion_zones(speed_threshold: float = 15.0):
    return db.congestion_zones(speed_threshold)


@app.get("/api/flow/od-matrix")
def get_od_matrix(date: str = None):
    return db.origin_destination_matrix(date)


@app.post("/api/simulation/seed")
def seed_simulation_data():
    """Seeds realistic multi-camera trajectory passages through Junctions and Midway corridors."""
    import random
    all_cams = get_cameras()
    now = time.time()

    # 1. Seed Flow Stats across all junction & midway cameras over 24h
    for h in range(24):
        t = now - ((23 - h) * 3600)
        for c in all_cams:
            cid = c["id"]
            is_mid = (c.get("kind") == "midway")
            v_count = random.randint(25, 95) if is_mid else random.randint(60, 210)
            avg_spd = random.uniform(28.0, 52.0) if is_mid else random.uniform(12.0, 32.0)
            q_len = random.randint(1, 5) if is_mid else random.randint(4, 18)
            db._submit("INSERT INTO flow_stats VALUES (?,?,?,?,?)", (t, cid, v_count, avg_spd, q_len))

    # 2. Realistic Corridor Sequences (Junction -> Midway -> Junction -> Midway)
    corridors = [
        ["CAM-02", "CAM-01", "CAM-03", "CAM-04", "CAM-05", "CAM-06", "CAM-07", "CAM-08"], # Park Street Eastbound
        ["CAM-08", "CAM-07", "CAM-06", "CAM-05", "CAM-04", "CAM-03", "CAM-01", "CAM-02"], # Park Street Westbound
        ["CAM-09", "CAM-13", "CAM-10", "CAM-11"],                                           # Ripon St to Eliot Rd
        ["CAM-08", "CAM-11", "CAM-12"],                                                     # Mullick Bazar to SH1 Flyover
    ]

    sample_plates = [
        "WB02AK1928", "WB06B4912", "WB12C3301", "DL03CC8899",
        "MH12DE4411", "KA01MJ2020", "WB01AB1234", "WB08F9081",
        "WB04E5521", "WB19H7732", "WB07J1104", "HR26DK8800"
    ]

    cam_dict = {c["id"]: c for c in all_cams}

    for plate in sample_plates:
        chosen_corridor = random.choice(corridors)
        # Choose a sub-path of 3 to 6 sequential checkpoints
        sub_len = min(len(chosen_corridor), random.randint(3, 6))
        start_idx = random.randint(0, len(chosen_corridor) - sub_len)
        path = chosen_corridor[start_idx : start_idx + sub_len]

        base_time = now - random.randint(1800, 14400)
        for i, cid in enumerate(path):
            c_info = cam_dict.get(cid, all_cams[0])
            s_time = base_time + (i * random.randint(120, 360))
            is_vio = 1 if (plate in ("WB02AK1928", "DL03CC8899") and i == 1) else 0
            db._submit(
                "INSERT INTO sightings (ts, plate_number, plate_norm, camera_id, latitude, longitude, is_violation) "
                "VALUES (?,?,?,?,?,?,?)",
                (s_time, plate, plate, cid, c_info["lat"], c_info["lon"], is_vio)
            )

    # 3. Seed OCR Accuracy Logs
    for _ in range(95):
        db._submit(
            "INSERT INTO ocr_accuracy_log (ts, track_id, raw_text, final_text, confidence, regex_valid, pass_index) "
            "VALUES (?,?,?,?,?,?,?)",
            (now - random.randint(100, 10000), random.randint(1, 50), "WB02AK1928", "WB02AK1928", random.uniform(0.91, 0.99), 1, 1)
        )

    # 4. Blacklist Seed
    db.add_blacklist("WB02AK1928", "Stolen Vehicle Alert (Park Street)", "high")
    db.add_blacklist("DL03CC8899", "Suspicious Inter-State Movement", "medium")

    return {"status": "success", "message": f"Seeded traffic flow and routes across {len(all_cams)} Junction & Midway cameras!"}



# ------------------------------------------------------------------ #
# Multi-Camera ANPR Tracking & Branch Prediction Endpoints
# ------------------------------------------------------------------ #

class SimulateSightingPayload(BaseModel):
    plate: str
    camera_id: str
    speed_kmh: Optional[float] = 40.0
    is_violation: Optional[bool] = False


@app.get("/api/tracking/graph")
def get_tracking_graph():
    """Returns road network nodes and edges with real OSM polylines."""
    return road_network.to_dict()


@app.get("/api/tracking/live")
def get_live_tracking():
    """Returns all current active vehicle tracks and interpolated positions."""
    return {
        "count": len(tracking_engine.active_tracks),
        "vehicles": [t.to_dict() for t in tracking_engine.active_tracks.values()]
    }


@app.post("/api/tracking/simulate-sighting")
def simulate_vehicle_sighting(payload: SimulateSightingPayload):
    """Simulates or reports a vehicle sighting at any camera in the network."""
    cid = payload.camera_id
    node = road_network.get_node(cid)
    lat = node.latitude if node else cfg.geometry.latitude
    lon = node.longitude if node else cfg.geometry.longitude
    spd = payload.speed_kmh or 40.0
    db.log_sighting(payload.plate, cid, lat, lon, int(bool(payload.is_violation)), speed_kmh=spd)
    instance_ids = tracking_engine.register_sighting(
        plate=payload.plate,
        camera_id=cid,
        speed_kmh=spd,
        ts=time.time()
    )
    return {
        "status": "success",
        "plate": payload.plate,
        "camera_id": cid,
        "speed_kmh": spd,
        "active_instances": instance_ids
    }


@app.post("/api/tracking/reset")
def reset_tracking():
    """Clears all active vehicle tracks from memory."""
    tracking_engine.active_tracks.clear()
    tracking_engine.plate_to_instances.clear()
    return {"status": "success", "message": "Multi-camera tracking state reset"}


class SettingsPayload(BaseModel):
    speed_limit: float | None = None
    conf_thresh: float | None = None
    auto_issue_conf: float | None = None
    source: str | None = None
    show_clean: bool | None = None
    enabled_rules: dict | None = None
    camera_preset: str | None = None
    camera_id: str | None = None
    alerts: dict | None = None


CAMERA_PRESETS = {
    "CAM-01 (Park Street Junction)": ("CAM-01", 22.5526, 88.3539),
    "CAM-02 (Howrah Bridge Approach)": ("CAM-02", 22.5850, 88.3426),
    "CAM-03 (Salt Lake Sector V)": ("CAM-03", 22.5735, 88.4331),
    "CAM-04 (Airport Expressway)": ("CAM-04", 22.6450, 88.4410),
}


@app.post("/api/settings")
def update_settings(payload: SettingsPayload):
    global cfg, engine, video_src, show_clean_vehicles, enabled_rules

    if payload.speed_limit is not None:
        cfg.rules.speed_limit_kmh = payload.speed_limit
    if payload.conf_thresh is not None:
        cfg.detector.conf = payload.conf_thresh
    if payload.auto_issue_conf is not None:
        cfg.rules.auto_issue_confidence = payload.auto_issue_conf
    if payload.show_clean is not None:
        show_clean_vehicles = payload.show_clean

    if payload.enabled_rules is not None:
        for k, v in payload.enabled_rules.items():
            if k in enabled_rules:
                enabled_rules[k] = bool(v)

    if payload.camera_id is not None:
        all_cams = get_cameras()
        matched = next((c for c in all_cams if c["id"] == payload.camera_id), None)
        if matched:
            cfg.geometry.camera_id = matched["id"]
            cfg.geometry.latitude = matched["lat"]
            cfg.geometry.longitude = matched["lon"]
    elif payload.camera_preset in CAMERA_PRESETS:
        cid, lat, lon = CAMERA_PRESETS[payload.camera_preset]
        cfg.geometry.camera_id = cid
        cfg.geometry.latitude = lat
        cfg.geometry.longitude = lon

    if payload.source is not None and payload.source != getattr(video_src, "src", None):
        try:
            video_src.stop()
        except Exception:
            pass
        src_val = int(payload.source) if str(payload.source).isdigit() else payload.source
        video_src = VideoSource(src_val, realtime=False).start()

    if payload.alerts is not None:
        for k, v in payload.alerts.items():
            if hasattr(cfg.alerts, k):
                setattr(cfg.alerts, k, v)

    cfg.save(CONFIG_PATH)

    return {"status": "success", "config": {
        "speed_limit": cfg.rules.speed_limit_kmh,
        "conf_thresh": cfg.detector.conf,
        "auto_issue_conf": cfg.rules.auto_issue_confidence,
        "show_clean": show_clean_vehicles,
        "enabled_rules": enabled_rules,
        "camera_id": cfg.geometry.camera_id,
        "source": str(getattr(video_src, "src", "_upload.mp4")),
    }}


@app.post("/api/alerts/test")
def send_test_alert(payload: dict = Body(...)):
    token = payload.get("bot_token", cfg.alerts.bot_token)
    chat_id = payload.get("chat_id", cfg.alerts.chat_id)
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="Bot token and Chat ID required")
    ok, msg = TelegramAlertService.send_test_alert(token, chat_id)
    return {"ok": ok, "message": msg}


# ------------------------------------------------------------------ #
# ANPR Lab & Model Evaluation API
# ------------------------------------------------------------------ #

_ANPR_LAB_MODELS = {}


def _get_anpr_yolo_model(model_path: str):
    """Load or retrieve cached YOLO model on best available device."""
    import torch
    from ultralytics import YOLO

    clean_path = str(Path(model_path)).replace("\\", "/")
    if clean_path not in _ANPR_LAB_MODELS:
        device = "cuda:0" if torch.cuda.is_available() else "cpu"
        m = YOLO(clean_path)
        m.to(device)
        _ANPR_LAB_MODELS[clean_path] = m
    return _ANPR_LAB_MODELS[clean_path]


@app.get("/api/anpr-lab/models")
def list_anpr_models():
    """List all available .pt models in models/ and root folder."""
    import torch
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)
    found = []

    # Check models/ directory
    for p in sorted(models_dir.glob("*.pt")):
        found.append({
            "id": str(p).replace("\\", "/"),
            "name": p.name,
            "path": str(p).replace("\\", "/"),
            "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            "is_default": (p.name == "license_plate_detector.pt"),
            "location": "models/"
        })

    # Check root directory
    for p in sorted(Path(".").glob("*.pt")):
        found.append({
            "id": str(p).replace("\\", "/"),
            "name": p.name,
            "path": str(p).replace("\\", "/"),
            "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
            "is_default": False,
            "location": "root"
        })

    return {
        "models": found,
        "active_model": getattr(cfg.ocr, "plate_model_path", "models/license_plate_detector.pt"),
        "cuda_available": torch.cuda.is_available(),
        "device_name": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU",
    }


@app.post("/api/anpr-lab/upload-model")
async def upload_anpr_model(file: UploadFile = File(...)):
    """Upload a custom .pt model weights file into models/."""
    if not file.filename.endswith(".pt"):
        raise HTTPException(status_code=400, detail="Only PyTorch .pt model files are allowed.")
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)
    target = models_dir / file.filename
    content = await file.read()
    target.write_bytes(content)
    return {
        "status": "success",
        "filename": file.filename,
        "path": str(target).replace("\\", "/"),
        "size_mb": round(len(content) / (1024 * 1024), 2),
    }


@app.get("/api/anpr-lab/current-frame")
def get_current_frame_for_lab():
    """Retrieve current video frame for instant ANPR lab evaluation."""
    import base64
    frame = latest_raw_frame
    if frame is None and Path("_upload.mp4").exists():
        cap = cv2.VideoCapture("_upload.mp4")
        ret, frame = cap.read()
        cap.release()
    if frame is None:
        raise HTTPException(status_code=404, detail="No active frame available. Please upload a video or image.")
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to encode frame.")
    b64 = base64.b64encode(buf).decode("utf-8")
    return {"status": "success", "image_data": f"data:image/jpeg;base64,{b64}"}


@app.post("/api/anpr-lab/evaluate")
async def evaluate_anpr_model(
    model_path: str = Form("models/license_plate_detector.pt"),
    conf_thresh: float = Form(0.25),
    enable_ocr: bool = Form(True),
    use_current_frame: bool = Form(False),
    file: Optional[UploadFile] = File(None)
):
    """Run ANPR plate detection and full OCR evaluation on a single image/frame."""
    import base64, time, torch
    from core.ocr_worker import (
        validate_indian_plate, disambiguate_indian_plate,
        detect_plate_background, INDIAN_STATE_CODES
    )

    img_bgr = None
    if use_current_frame:
        if latest_raw_frame is not None:
            img_bgr = latest_raw_frame.copy()
        elif Path("_upload.mp4").exists():
            cap = cv2.VideoCapture("_upload.mp4")
            ret, f = cap.read()
            cap.release()
            if ret:
                img_bgr = f
    elif file is not None:
        content = await file.read()
        nparr = np.frombuffer(content, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img_bgr is None or img_bgr.size == 0:
        raise HTTPException(status_code=400, detail="No valid image provided.")

    target_model = Path(model_path)
    if not target_model.exists():
        raise HTTPException(status_code=404, detail=f"Model file '{model_path}' not found.")

    try:
        model = _get_anpr_yolo_model(str(target_model))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load model: {str(e)}")

    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    # 1. Measure detection inference time
    t0 = time.perf_counter()
    results = model.predict(img_bgr, conf=float(conf_thresh), verbose=False, device=device)
    t_infer = (time.perf_counter() - t0) * 1000.0

    boxes = results[0].boxes if (results and len(results[0].boxes) > 0) else []
    h_img, w_img = img_bgr.shape[:2]

    annotated = img_bgr.copy()
    plates = []
    t_ocr_total = 0.0

    for idx, box in enumerate(boxes, start=1):
        x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].cpu().numpy()]
        conf = float(box.conf)

        pad_x = max(2, int((x2 - x1) * 0.04))
        pad_y = max(2, int((y2 - y1) * 0.04))
        cx1 = max(0, x1 - pad_x)
        cy1 = max(0, y1 - pad_y)
        cx2 = min(w_img, x2 + pad_x)
        cy2 = min(h_img, y2 + pad_y)
        crop = img_bgr[cy1:cy2, cx1:cx2]

        crop_b64 = ""
        if crop.size > 0:
            _, cbuf = cv2.imencode(".jpg", crop)
            crop_b64 = f"data:image/jpeg;base64,{base64.b64encode(cbuf).decode('utf-8')}"

        plate_text, ocr_conf = None, 0.0
        plate_type, text_is_dark = "UNKNOWN", True
        is_valid = False
        valid_reason = ""
        state_name = "N/A"

        if enable_ocr and crop.size > 0:
            t_ocr_start = time.perf_counter()
            plate_type, text_is_dark = detect_plate_background(crop)
            raw_text, ocr_conf = engine.ocr.reader.read(crop)
            t_ocr_total += (time.perf_counter() - t_ocr_start) * 1000.0

            if raw_text:
                plate_text = raw_text
                is_valid, valid_reason = validate_indian_plate(raw_text)
                state_code = raw_text[:2] if len(raw_text) >= 2 else ""
                STATE_NAMES = {
                    'AP': 'Andhra Pradesh', 'AR': 'Arunachal Pradesh', 'AS': 'Assam', 'BR': 'Bihar', 'CG': 'Chhattisgarh',
                    'GA': 'Goa', 'GJ': 'Gujarat', 'HR': 'Haryana', 'HP': 'Himachal Pradesh', 'JK': 'Jammu & Kashmir',
                    'JH': 'Jharkhand', 'KA': 'Karnataka', 'KL': 'Kerala', 'MP': 'Madhya Pradesh', 'MH': 'Maharashtra',
                    'MN': 'Manipur', 'ML': 'Meghalaya', 'MZ': 'Mizoram', 'NL': 'Nagaland', 'OD': 'Odisha',
                    'PB': 'Punjab', 'RJ': 'Rajasthan', 'SK': 'Sikkim', 'TN': 'Tamil Nadu', 'TS': 'Telangana',
                    'TR': 'Tripura', 'UP': 'Uttar Pradesh', 'UA': 'Uttarakhand', 'WB': 'West Bengal',
                    'AN': 'Andaman & Nicobar', 'CH': 'Chandigarh', 'DL': 'Delhi', 'DN': 'Dadra & Nagar Haveli',
                    'DD': 'Daman & Diu', 'LD': 'Lakshadweep', 'PY': 'Puducherry', 'BH': 'Bharat (National)'
                }
                state_name = STATE_NAMES.get(state_code, state_code if state_code in INDIAN_STATE_CODES else "Unknown")

        # Draw aesthetic annotation box
        box_color = (46, 213, 115) if is_valid else (0, 210, 255)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)
        label = f"#{idx} {plate_text or 'PLATE'} ({conf:.0%})"
        (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
        cv2.rectangle(annotated, (x1, max(0, y1 - lh - 8)), (x1 + lw + 6, y1), box_color, -1)
        cv2.putText(annotated, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 15, 25), 2, cv2.LINE_AA)

        plates.append({
            "id": idx,
            "bbox": [x1, y1, x2, y2],
            "det_conf": round(conf, 3),
            "plate_crop": crop_b64,
            "plate_text": plate_text or "UNREAD",
            "ocr_conf": round(ocr_conf, 2),
            "is_valid_indian": is_valid,
            "valid_reason": valid_reason,
            "plate_type": plate_type,
            "state": state_name,
        })

    _, out_buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
    out_b64 = f"data:image/jpeg;base64,{base64.b64encode(out_buf).decode('utf-8')}"

    return {
        "status": "success",
        "model_path": str(target_model).replace("\\", "/"),
        "model_name": target_model.name,
        "device": f"{device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})",
        "infer_ms": round(t_infer, 1),
        "ocr_ms": round(t_ocr_total, 1),
        "total_ms": round(t_infer + t_ocr_total, 1),
        "fps": round(1000.0 / max(0.1, t_infer), 1),
        "plates_detected": len(plates),
        "plates": plates,
        "annotated_image": out_b64,
    }


@app.post("/api/anpr-lab/benchmark")
async def benchmark_models(
    models: str = Form(""),
    conf_thresh: float = Form(0.25),
    use_current_frame: bool = Form(False),
    file: Optional[UploadFile] = File(None)
):
    """Run multiple models side-by-side on the SAME test frame to compare speed and detection accuracy."""
    import base64, time, torch
    from core.ocr_worker import validate_indian_plate

    img_bgr = None
    if use_current_frame:
        if latest_raw_frame is not None:
            img_bgr = latest_raw_frame.copy()
        elif Path("_upload.mp4").exists():
            cap = cv2.VideoCapture("_upload.mp4")
            ret, f = cap.read()
            cap.release()
            if ret:
                img_bgr = f
    elif file is not None:
        content = await file.read()
        nparr = np.frombuffer(content, np.uint8)
        img_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img_bgr is None or img_bgr.size == 0:
        raise HTTPException(status_code=400, detail="No valid image provided.")

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    if not model_list:
        model_list = [str(p).replace("\\", "/") for p in Path("models").glob("*.pt")] + \
                     [str(p).replace("\\", "/") for p in Path(".").glob("*.pt")]

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    results_bench = []

    for mpath in model_list:
        p = Path(mpath)
        if not p.exists():
            continue
        try:
            m = _get_anpr_yolo_model(str(p))
            # Timed inference pass
            t0 = time.perf_counter()
            res = m.predict(img_bgr, conf=float(conf_thresh), verbose=False, device=device)
            dt = (time.perf_counter() - t0) * 1000.0

            boxes = res[0].boxes if (res and len(res[0].boxes) > 0) else []
            confs = [float(b.conf) for b in boxes]
            avg_conf = (sum(confs) / len(confs)) if confs else 0.0

            top_plate = "N/A"
            valid_morth = False
            if boxes:
                x1, y1, x2, y2 = [int(round(v)) for v in boxes[0].xyxy[0].cpu().numpy()]
                crop = img_bgr[max(0, y1):min(img_bgr.shape[0], y2), max(0, x1):min(img_bgr.shape[1], x2)]
                if crop.size > 0:
                    text, _ = engine.ocr.reader.read(crop)
                    if text:
                        top_plate = text
                        valid_morth, _ = validate_indian_plate(text)

            results_bench.append({
                "model_name": p.name,
                "model_path": str(p).replace("\\", "/"),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "plates_found": len(boxes),
                "avg_conf": round(avg_conf, 3),
                "infer_ms": round(dt, 1),
                "fps": round(1000.0 / max(0.1, dt), 1),
                "sample_plate": top_plate,
                "is_valid_morth": valid_morth,
            })
        except Exception as e:
            results_bench.append({
                "model_name": p.name,
                "model_path": str(p).replace("\\", "/"),
                "error": str(e),
                "plates_found": 0,
                "infer_ms": 0,
                "fps": 0
            })

    return {
        "status": "success",
        "benchmark": results_bench,
        "device": f"{device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})",
    }


@app.post("/api/anpr-lab/evaluate-video")
def evaluate_anpr_video(
    model_path: str = Form("models/license_plate_detector.pt"),
    conf_thresh: float = Form(0.25),
    max_frames: int = Form(100),
    frame_step: int = Form(1),
    ocr_interval: int = Form(3),
    enable_ocr: bool = Form(True),
    file: Optional[UploadFile] = File(None)
):
    """Run ANPR plate detection & tracking across a video file with an annotated output video."""
    import base64, time, torch
    from core.ocr_worker import (
        validate_indian_plate, disambiguate_indian_plate,
        detect_plate_background, INDIAN_STATE_CODES
    )

    STATE_NAMES = {
        'AP': 'Andhra Pradesh', 'AR': 'Arunachal Pradesh', 'AS': 'Assam', 'BR': 'Bihar', 'CG': 'Chhattisgarh',
        'GA': 'Goa', 'GJ': 'Gujarat', 'HR': 'Haryana', 'HP': 'Himachal Pradesh', 'JK': 'Jammu & Kashmir',
        'JH': 'Jharkhand', 'KA': 'Karnataka', 'KL': 'Kerala', 'MP': 'Madhya Pradesh', 'MH': 'Maharashtra',
        'MN': 'Manipur', 'ML': 'Meghalaya', 'MZ': 'Mizoram', 'NL': 'Nagaland', 'OD': 'Odisha',
        'PB': 'Punjab', 'RJ': 'Rajasthan', 'SK': 'Sikkim', 'TN': 'Tamil Nadu', 'TS': 'Telangana',
        'TR': 'Tripura', 'UP': 'Uttar Pradesh', 'UA': 'Uttarakhand', 'WB': 'West Bengal',
        'AN': 'Andaman & Nicobar', 'CH': 'Chandigarh', 'DL': 'Delhi', 'DN': 'Dadra & Nagar Haveli',
        'DD': 'Daman & Diu', 'LD': 'Lakshadweep', 'PY': 'Puducherry', 'BH': 'Bharat (National)'
    }

    # Video input resolution
    temp_video = None
    if file is not None and file.filename:
        evidence_dir = Path("evidence")
        evidence_dir.mkdir(exist_ok=True)
        temp_video = evidence_dir / f"_lab_upload_{int(time.time())}.mp4"
        with temp_video.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        src_path = str(temp_video)
    else:
        raise HTTPException(status_code=400, detail="Please select a video file (.mp4) to evaluate.")

    cap = cv2.VideoCapture(src_path)
    if not cap.isOpened():
        raise HTTPException(status_code=400, detail="Could not open video file.")

    fps_src = cap.get(cv2.CAP_PROP_FPS) or 25.0
    w_src = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    h_src = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    total_src_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 100

    target_model = Path(model_path)
    if not target_model.exists():
        raise HTTPException(status_code=404, detail=f"Model '{model_path}' not found.")

    model = _get_anpr_yolo_model(str(target_model))
    device = "cuda:0" if torch.cuda.is_available() else "cpu"

    # Setup output video writer (H.264 for native browser playback)
    evidence_dir = Path("evidence")
    evidence_dir.mkdir(exist_ok=True)
    out_name = f"anpr_lab_eval_{int(time.time())}.mp4"
    out_path = evidence_dir / out_name

    writer_is_imageio = True
    try:
        import imageio
        fps_out = max(5.0, fps_src / max(1, frame_step))
        out_writer = imageio.get_writer(str(out_path), fps=fps_out, codec='libx264', format='FFMPEG', macro_block_size=1)
    except Exception:
        writer_is_imageio = False
        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out_writer = cv2.VideoWriter(str(out_path), fourcc, fps_src / max(1, frame_step), (w_src, h_src))

    frames_processed = 0
    total_detections = 0
    t_infer_total = 0.0
    t_start = time.perf_counter()

    unique_plates = {}
    frame_idx = 0
    max_target = max_frames if max_frames > 0 else total_src_frames

    while frames_processed < max_target:
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        frame_idx += 1
        if frame_idx % frame_step != 0:
            continue

        frames_processed += 1
        curr_time_sec = frame_idx / fps_src
        mins = int(curr_time_sec // 60)
        secs = curr_time_sec % 60
        time_str = f"{mins:02d}:{secs:04.1f}s"

        t0 = time.perf_counter()
        results = model.predict(frame, conf=float(conf_thresh), verbose=False, device=device)
        t_infer_total += (time.perf_counter() - t0) * 1000.0

        boxes = results[0].boxes if (results and len(results[0].boxes) > 0) else []
        total_detections += len(boxes)
        annotated = frame.copy()

        for b_idx, box in enumerate(boxes, start=1):
            x1, y1, x2, y2 = [int(round(v)) for v in box.xyxy[0].cpu().numpy()]
            conf = float(box.conf)

            pad_x = max(2, int((x2 - x1) * 0.04))
            pad_y = max(2, int((y2 - y1) * 0.04))
            cx1 = max(0, x1 - pad_x)
            cy1 = max(0, y1 - pad_y)
            cx2 = min(w_src, x2 + pad_x)
            cy2 = min(h_src, y2 + pad_y)
            crop = frame[cy1:cy2, cx1:cx2]

            plate_text = None
            ocr_conf = 0.0
            is_valid = False

            if enable_ocr and crop.size > 0 and (frames_processed % max(1, ocr_interval) == 0) and (b_idx <= 2):
                text, score = getattr(engine.ocr.reader, 'read_fast', engine.ocr.reader.read)(crop)
                if text:
                    plate_text = text
                    ocr_conf = score
                    is_valid, _ = validate_indian_plate(text)
                    state_code = text[:2] if len(text) >= 2 else ""
                    state_name = STATE_NAMES.get(state_code, state_code if state_code in INDIAN_STATE_CODES else "Unknown")

                    if plate_text not in unique_plates:
                        _, cbuf = cv2.imencode(".jpg", crop)
                        crop_b64 = f"data:image/jpeg;base64,{base64.b64encode(cbuf).decode('utf-8')}"
                        unique_plates[plate_text] = {
                            "plate": plate_text,
                            "conf": round(ocr_conf, 2),
                            "crop": crop_b64,
                            "first_seen": time_str,
                            "is_valid_indian": is_valid,
                            "state": state_name,
                            "count": 1
                        }
                    else:
                        unique_plates[plate_text]["count"] += 1
                        if ocr_conf > unique_plates[plate_text]["conf"]:
                            unique_plates[plate_text]["conf"] = round(ocr_conf, 2)

            box_color = (46, 213, 115) if is_valid else (0, 210, 255)
            cv2.rectangle(annotated, (x1, y1), (x2, y2), box_color, 2)
            label = f"#{b_idx} {plate_text or 'PLATE'} ({conf:.0%})"
            (lw, lh), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
            cv2.rectangle(annotated, (x1, max(0, y1 - lh - 8)), (x1 + lw + 6, y1), box_color, -1)
            cv2.putText(annotated, label, (x1 + 3, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 15, 25), 2, cv2.LINE_AA)

        # Draw HUD on video frame
        cv2.rectangle(annotated, (10, 10), (340, 56), (16, 22, 36), -1)
        cv2.putText(annotated, f"ANPR LAB · {target_model.name}", (18, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 210, 255), 2, cv2.LINE_AA)
        cv2.putText(annotated, f"Frame {frames_processed}/{max_target} | {time_str} | Plt: {total_detections}", (18, 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 174, 192), 1, cv2.LINE_AA)

        if writer_is_imageio:
            out_writer.append_data(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB))
        else:
            out_writer.write(annotated)

    cap.release()
    if writer_is_imageio:
        out_writer.close()
    else:
        out_writer.release()

    total_time_sec = round(time.perf_counter() - t_start, 2)
    avg_infer_ms = round(t_infer_total / max(1, frames_processed), 1)
    avg_fps = round(frames_processed / max(0.01, total_time_sec), 1)

    if temp_video and temp_video.exists():
        try:
            temp_video.unlink()
        except Exception:
            pass

    sorted_plates = sorted(unique_plates.values(), key=lambda x: (x["is_valid_indian"], x["count"]), reverse=True)

    return {
        "status": "success",
        "video_url": f"/evidence/{out_name}",
        "frames_processed": frames_processed,
        "total_detections": total_detections,
        "unique_plates_count": len(sorted_plates),
        "unique_plates": sorted_plates,
        "infer_ms": avg_infer_ms,
        "total_sec": total_time_sec,
        "fps": avg_fps,
        "model_name": target_model.name,
        "device": f"{device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})",
    }


@app.post("/api/anpr-lab/benchmark-video")
def benchmark_models_video(
    models: str = Form(""),
    conf_thresh: float = Form(0.25),
    max_frames: int = Form(50),
    file: Optional[UploadFile] = File(None)
):
    """Benchmark multiple models side-by-side on a video clip (comparing FPS, latency, total plates)."""
    import time, torch
    from core.ocr_worker import validate_indian_plate

    temp_video = None
    if file is not None and file.filename:
        evidence_dir = Path("evidence")
        evidence_dir.mkdir(exist_ok=True)
        temp_video = evidence_dir / f"_lab_bench_{int(time.time())}.mp4"
        with temp_video.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        src_path = str(temp_video)
    else:
        raise HTTPException(status_code=400, detail="Please select a video file (.mp4) to benchmark.")

    model_list = [m.strip() for m in models.split(",") if m.strip()]
    if not model_list:
        model_list = [str(p).replace("\\", "/") for p in Path("models").glob("*.pt")] + \
                     [str(p).replace("\\", "/") for p in Path(".").glob("*.pt")]

    device = "cuda:0" if torch.cuda.is_available() else "cpu"
    results_bench = []

    cap = cv2.VideoCapture(src_path)
    sample_frames = []
    while len(sample_frames) < max_frames:
        ret, f = cap.read()
        if not ret or f is None:
            break
        sample_frames.append(f)
    cap.release()

    if not sample_frames:
        raise HTTPException(status_code=400, detail="Could not read frames from video.")

    for mpath in model_list:
        p = Path(mpath)
        if not p.exists():
            continue
        try:
            m = _get_anpr_yolo_model(str(p))
            # Warm up pass
            _ = m.predict(sample_frames[0], conf=float(conf_thresh), verbose=False, device=device)

            t0 = time.perf_counter()
            total_plates = 0
            conf_list = []
            for f in sample_frames:
                res = m.predict(f, conf=float(conf_thresh), verbose=False, device=device)
                boxes = res[0].boxes if (res and len(res[0].boxes) > 0) else []
                total_plates += len(boxes)
                for b in boxes:
                    conf_list.append(float(b.conf))

            dt_total = time.perf_counter() - t0
            avg_infer_ms = round((dt_total / len(sample_frames)) * 1000.0, 1)
            fps = round(len(sample_frames) / max(0.001, dt_total), 1)
            avg_conf = round(sum(conf_list) / len(conf_list), 3) if conf_list else 0.0

            results_bench.append({
                "model_name": p.name,
                "model_path": str(p).replace("\\", "/"),
                "size_mb": round(p.stat().st_size / (1024 * 1024), 2),
                "frames_tested": len(sample_frames),
                "total_plates_found": total_plates,
                "plates_per_frame": round(total_plates / len(sample_frames), 2),
                "avg_conf": avg_conf,
                "infer_ms": avg_infer_ms,
                "fps": fps,
            })
        except Exception as e:
            results_bench.append({
                "model_name": p.name,
                "model_path": str(p).replace("\\", "/"),
                "error": str(e),
                "total_plates_found": 0,
                "infer_ms": 0,
                "fps": 0
            })

    if temp_video and temp_video.exists():
        try:
            temp_video.unlink()
        except Exception:
            pass

    return {
        "status": "success",
        "benchmark": results_bench,
        "frames_tested": len(sample_frames),
        "device": f"{device} ({torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU'})",
    }


# Serve evidence images & clips
evidence_dir = Path("evidence")
evidence_dir.mkdir(exist_ok=True)
app.mount("/evidence", StaticFiles(directory="evidence"), name="evidence")

# Serve React frontend dist directory if built, otherwise static/ index.html
dist_dir = Path("Dark-Themed Surveillance Dashboard/dist")
static_dir = Path("static")
if dist_dir.exists():
    app.mount("/", StaticFiles(directory=str(dist_dir), html=True), name="static")
elif static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=8765, reload=False)
