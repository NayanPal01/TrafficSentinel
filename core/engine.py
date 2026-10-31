"""Pipeline orchestrator.

Per-frame ordering is chosen so nothing blocking sits on the critical path:

    decode (thread)  ->  detect+track  ->  scene graph  ->  rules
                                                  |
                        OCR (thread)  <-----------+
                        evidence (thread) <-------+
                        db writes (thread) <------+

The main loop only ever does: inference, a handful of geometry, and drawing.
Everything with unbounded or high latency is handed to a worker with a bounded,
drop-oldest queue What is the puurpose of the first.
"""

from __future__ import annotations

import time
def debug_log(msg):
    with open("telegram_debug.log", "a", encoding="utf-8") as f:
        f.write(msg + "\n")

from collections import deque
from typing import Dict, List, Optional

import numpy as np

from .annotator import Annotator
from .config import AppConfig
from .database import Database
from .detector import Detector
from .evidence import EvidenceWriter
from .geometry import GroundPlane
from .helmet import HelmetClassifier
from .ocr_worker import OCRWorker, plate_crop, get_car
from .scene_graph import SceneGraphBuilder
from .tracks import TrackRegistry
from .violations import ViolationEngine
from .anomaly import RouteAnomalyDetector


class TrafficSentinel:
    def __init__(self, cfg: AppConfig, fps: float = 25.0):
        self.cfg = cfg
        self.fps = fps

        self.detector = Detector(cfg.detector)
        self.ground = GroundPlane(cfg.geometry.homography_src,
                                  cfg.geometry.homography_dst)
        self.registry = TrackRegistry(fps, self.ground)
        self.builder = SceneGraphBuilder()
        self.helmet = HelmetClassifier(cfg.helmet)
        self.rules = ViolationEngine(cfg, cfg.geometry, self.ground,
                                     self.helmet)
        self.ocr = OCRWorker(cfg.ocr).start()
        self.alerts = TelegramAlertService(getattr(cfg, 'alerts', None) or AlertConfig()).start()
        self.db = Database(cfg.db_path)
        self.evidence = EvidenceWriter(cfg.evidence, fps,
                                       cfg.geometry.camera_id)
        self.annotator = Annotator(cfg.geometry)
        self._latest_plate_boxes: List[dict] = []

        self._frame_times = deque(maxlen=30)
        self._last_flow_log = 0.0
        self.live_violations: deque = deque(maxlen=60)
        self.explain_log: deque = deque(maxlen=40)
        self._blacklist_hits: List[dict] = []
        self._anomaly_hits: List[dict] = []
        self.anomaly_detector = RouteAnomalyDetector(self.db)

        # Multi-detection prevention caches & ANPR event queue
        self._new_anpr_events: List[dict] = []
        self._anpr_broadcast_cooldown: Dict[str, float] = {}
        self._plate_violation_cooldown: Dict[str, float] = {}
        self._recent_violation_boxes: deque = deque(maxlen=60)

        self.detector.warmup()

    # ------------------------------------------------------------------ #

    def process(self, frame: np.ndarray, frame_idx: int,
                draw: bool = True) -> Dict:
        t0 = time.perf_counter()
        self.rules.cfg = self.cfg.rules

        detections = self.detector.detect(frame, frame_idx=frame_idx)
        self.registry.update(detections, frame_idx)
        graph = self.builder.build(detections)
        violations = self.rules.evaluate(frame, graph, self.registry, frame_idx)

        self._dispatch_ocr(frame, graph)
        self._collect_ocr()
        new = self._commit(frame, violations, frame_idx)

        self.evidence.push_frame(frame)

        dt = time.perf_counter() - t0
        self._frame_times.append(dt)
        fps = 1.0 / max(1e-6, float(np.mean(self._frame_times)))

        hud = {
            "camera_id": self.cfg.geometry.camera_id,
            "fps": fps,
            "infer_ms": self.detector.last_infer_ms,
            "ocr_backlog": self.ocr.backlog,
            "light": self.rules.light_state,
            "tracks": len(self.registry.tracks),
            "calibrated": self.ground.calibrated,
        }

        annotated = None
        if draw:
            annotated = self.annotator.draw(frame.copy(), graph, violations,
                                            self.registry, hud,
                                            plate_boxes=self._latest_plate_boxes)

        self._log_flow(graph)
        self._log_sightings(frame_idx)
        self.explain_log.extend(self.builder.explain(graph))

        # Collect blacklist, anomaly hits, and ANPR events from this frame
        blacklist_hits = list(self._blacklist_hits)
        self._blacklist_hits.clear()
        anomaly_hits = list(self._anomaly_hits)
        self._anomaly_hits.clear()
        anpr_events = list(self._new_anpr_events)
        self._new_anpr_events.clear()

        return {
            "frame": annotated,
            "violations": violations,
            "new_violations": new,
            "anpr_events": anpr_events,
            "blacklist_hits": blacklist_hits,
            "anomaly_hits": anomaly_hits,
            "graph": graph,
            "hud": hud,
            "latency_ms": dt * 1000.0,
        }

    # ------------------------------------------------------------------ #

    def _dispatch_ocr(self, frame, graph) -> None:
        """Two-stage plate detection:

        Stage 1 (from reference main.py): Run YOLOv8 license_plate_detector on
        the FULL FRAME, crop each plate, threshold (BINARY_INV at 64), OCR, and
        assign to the parent vehicle via get_car() containment check.

        Stage 2 (fallback): For vehicles that Stage 1 missed, submit a bumper
        crop to the async OCR worker thread.
        """
        if not self.cfg.ocr.enabled:
            return

        # Skip full-frame plate detection if no vehicles are in the scene
        vehicles = list(graph.vehicles())
        if not vehicles:
            self._latest_plate_boxes = []
            return

        # ----- Stage 1: Ultra-fast GPU plate detection (~2-3ms on CUDA) -----
        plate_boxes = self.ocr.reader.detect_plate_boxes(frame)
        self._latest_plate_boxes = plate_boxes
        handled_tracks = set()

        frame_h = frame.shape[0]
        min_plate_h = getattr(self.cfg.ocr, 'min_plate_height', 20)
        min_plate_w = getattr(self.cfg.ocr, 'min_plate_width', 48)
        min_veh_h = getattr(self.cfg.ocr, 'min_vehicle_height', 65)
        min_y_ratio = getattr(self.cfg.ocr, 'min_proximity_y', 0.28)

        if plate_boxes:
            vehicle_bboxes = []
            track_map = {}
            for vnode in graph.vehicles():
                tr = vnode.det.get("_track")
                if tr is None:
                    continue
                x1, y1, x2, y2 = vnode.bbox
                vehicle_bboxes.append([x1, y1, x2, y2, tr.track_id])
                track_map[tr.track_id] = tr

            for p in plate_boxes:
                px1, py1, px2, py2 = p["bbox"]
                crop = p["crop"]
                crop_h, crop_w = crop.shape[:2]

                _, _, _, _, car_id = get_car([px1, py1, px2, py2], vehicle_bboxes)
                if car_id != -1 and car_id in track_map:
                    tr = track_map[car_id]
                    if not hasattr(tr, 'latest_plate_crop') or (crop_h * crop_w > tr.latest_plate_crop.shape[0] * tr.latest_plate_crop.shape[1]):
                        tr.latest_plate_crop = crop.copy()
                    if getattr(tr, "ocr_locked", False):
                        p["text"] = tr.plate
                        handled_tracks.add(car_id)
                        continue  # Confident OCR Lock: do not re-submit

                    # Proximity & Resolution Gate: wait until vehicle is close and sharp
                    veh_h = (tr.bbox[3] - tr.bbox[1]) if tr.bbox else 0
                    is_close = (
                        crop_h >= min_plate_h and
                        crop_w >= min_plate_w and
                        veh_h >= min_veh_h and
                        py2 >= (frame_h * min_y_ratio)
                    )

                    if not is_close:
                        # Vehicle is still too far/blurry: wait until it gets closer
                        p["text"] = "APPROACHING"
                        continue

                    if tr.ocr_attempts >= self.cfg.ocr.max_attempts_per_track:
                        handled_tracks.add(car_id)
                        continue

                    last_frame = getattr(tr, "_last_ocr_submit", -10)
                    if hasattr(tr, "last_frame") and tr.last_frame - last_frame >= 3:
                        if self.ocr.submit(car_id, crop):
                            tr.ocr_attempts += 1
                            tr._last_ocr_submit = getattr(tr, "last_frame", 0)
                            handled_tracks.add(car_id)
                elif car_id == -1:
                    # Untracked vehicle or standalone plate: check size gate before OCR
                    if crop_h >= min_plate_h and crop_w >= min_plate_w and py2 >= (frame_h * min_y_ratio):
                        synth_id = int((px1 % 1000) * 1000 + (py1 % 1000))
                        res = self.ocr.result(synth_id)
                        if res and res.plate:
                            p["text"] = res.plate
                        else:
                            self.ocr.submit(synth_id, crop)
                    else:
                        p["text"] = "APPROACHING"

        # ----- Stage 2: Async bumper-crop fallback only when no plates were detected -----
        if not plate_boxes:
            budget = 1
            for vnode in graph.vehicles():
                if budget <= 0:
                    break
                tr = vnode.det.get("_track")
                if tr is None or tr.track_id in handled_tracks:
                    continue
                if getattr(tr, "ocr_locked", False):
                    continue
                if tr.ocr_attempts >= self.cfg.ocr.max_attempts_per_track:
                    continue

                x1, y1, x2, y2 = vnode.bbox
                h = y2 - y1
                # Must be close enough (height >= min_veh_h and y2 >= min_y_ratio)
                if h < max(min_veh_h, self.cfg.ocr.min_crop_height) or y2 < (frame_h * min_y_ratio):
                    continue

                last_frame = getattr(tr, "_last_ocr_submit", -10)
                if hasattr(tr, "last_frame") and tr.last_frame - last_frame < 5:
                    continue

                crop = plate_crop(frame, vnode.bbox, self.cfg.ocr.min_crop_height)
                if crop is None:
                    continue
                if not hasattr(tr, 'latest_plate_crop') or tr.latest_plate_crop is None:
                    tr.latest_plate_crop = crop.copy()
                if self.ocr.submit(tr.track_id, crop):
                    tr.ocr_attempts += 1
                    tr._last_ocr_submit = getattr(tr, "last_frame", 0)
                    budget -= 1


    def _collect_ocr(self) -> None:
        now = time.time()
        for tid, tr in self.registry.tracks.items():
            if getattr(tr, "ocr_locked", False):
                continue
            res = self.ocr.result(tid)
            if not res or not res.plate:
                continue

            is_valid = self.ocr.reader.is_valid(res.plate)

            if res.confidence > tr.plate_conf:
                tr.plate = res.plate
                tr.plate_conf = res.confidence

                # Validation and high-confidence gate (>= 0.75) before locking
                if is_valid and res.confidence >= 0.75:
                    tr.ocr_locked = True
                else:
                    tr.ocr_locked = False

                # Get clean nameplate crop image
                crop = getattr(res, 'crop', None)
                if crop is None or getattr(crop, 'size', 0) == 0:
                    crop = getattr(tr, 'latest_plate_crop', None)
                if crop is not None and (crop.shape[0] > 70 or crop.shape[1] > 200):
                    isolated = self.ocr.reader.isolate_plate(crop)
                    if isolated is not None and isolated.size > 0:
                        crop = isolated

                plate_img_path = ""
                if crop is not None and getattr(crop, 'size', 0) > 0:
                    plate_img_path = self.evidence.save_plate_crop(crop, res.plate, tid)
                tr.plate_img = plate_img_path

                # Emit single clean ANPR event if not recently broadcasted (60s cooldown per plate)
                norm_plate = "".join(c for c in res.plate.upper() if c.isalnum())
                last_seen = self._anpr_broadcast_cooldown.get(norm_plate, 0.0)
                speed = tr.effective_speed_kmh(default_speed=float(self.cfg.rules.speed_limit_kmh))

                if (now - last_seen) > 60.0:
                    self._anpr_broadcast_cooldown[norm_plate] = now
                    self._new_anpr_events.append({
                        "plate": res.plate,
                        "track_id": tid,
                        "vehicle_type": tr.label.capitalize() if tr.label else "Vehicle",
                        "plate_img": plate_img_path,
                        "conf": res.confidence,
                        "speed_kmh": round(speed, 1),
                        "camera_id": self.cfg.geometry.camera_id,
                        "lat": self.cfg.geometry.latitude,
                        "lon": self.cfg.geometry.longitude,
                        "ts": now,
                    })

                    # Log OCR accuracy metric & checkpoint sighting ONCE per passage
                    self.db.log_ocr_attempt(tid, res.plate, res.plate, res.confidence, is_valid, 2)
                    self.db.log_sighting(res.plate, self.cfg.geometry.camera_id,
                                         self.cfg.geometry.latitude,
                                         self.cfg.geometry.longitude,
                                         bool(tr.logged),
                                         speed_kmh=speed)
                    tr.sighting_logged = True
                    tr.last_sighting_cam = self.cfg.geometry.camera_id

                # Retroactively update database record and live list so review queue shows plate
                self.db.update_violation_plate(tid, res.plate, res.confidence)
                updated_existing = False
                for item in self.live_violations:
                    if item.get("track_id") == tid:
                        if not item.get("plate") or item.get("plate") in ("UNREAD", "-"):
                            item["plate"] = res.plate
                        if plate_img_path and (not item.get("plate_img") or "/crops/" in item.get("plate_img", "")):
                            item["plate_img"] = plate_img_path
                        try:
                            if item.get("status") == "review" and item.get("fine", 0) > 0 and float(item.get("confidence", 0)) >= self.cfg.rules.auto_issue_confidence:
                                item["status"] = "issued"
                        except Exception:
                            pass
                        updated_existing = True

                # If this vehicle did not have a violation yet, show ANPR vehicle sighting in Live Logs
                if not updated_existing:
                    self.live_violations.appendleft({
                        "type": "ANPR_DETECT",
                        "track_id": tid,
                        "confidence": res.confidence,
                        "fine": 0,
                        "severity": "INFO",
                        "plate": res.plate,
                        "status": "detected",
                        "reasons": [f"Plate {res.plate} verified", f"Speed {round(speed, 1)} km/h"],
                        "evidence": plate_img_path,
                        "crop_path": "",
                        "plate_img": plate_img_path,
                        "clip": "",
                        "frame": getattr(tr, "last_frame", 0),
                        "vehicle_type": tr.label.capitalize() if tr and tr.label else "Vehicle",
                    })

    # ------------------------------------------------------------------ #

    def _commit(self, frame, violations, frame_idx) -> List:
        """Deduplicate by track_id, license plate, and spatial proximity to prevent multi-detection."""
        new = []
        now = time.time()
        for v in violations:
            if self.registry.already_logged(v.track_id, v.vtype):
                continue

            tr = self.registry.get(v.track_id)
            plate = tr.plate if tr else None
            plate_conf = tr.plate_conf if tr else 0.0

            # 1. Deduplication by License Plate (prevent same car logging same violation twice in 45s)
            if plate:
                plate_key = f"{plate}:{v.vtype}"
                last_time = self._plate_violation_cooldown.get(plate_key, 0.0)
                if (now - last_time) < 45.0:
                    continue
                self._plate_violation_cooldown[plate_key] = now
            else:
                # 2. Spatial Deduplication only for unread vehicles / ID switches
                vx1, vy1, vx2, vy2 = v.bbox
                v_cx = (vx1 + vx2) / 2.0
                v_cy = (vy1 + vy2) / 2.0
                is_spatial_dup = False
                for past_rec in self._recent_violation_boxes:
                    if past_rec["vtype"] == v.vtype and (now - past_rec["time"] < 6.0):
                        px1, py1, px2, py2 = past_rec["bbox"]
                        pcx = (px1 + px2) / 2.0
                        pcy = (py1 + py2) / 2.0
                        dist = ((v_cx - pcx) ** 2 + (v_cy - pcy) ** 2) ** 0.5
                        if dist < 60.0:
                            is_spatial_dup = True
                            break
                if is_spatial_dup:
                    continue

            # Mark this violation as logged on the track object
            self.registry.mark_logged(v.track_id, v.vtype)
            self._recent_violation_boxes.append({
                "vtype": v.vtype,
                "bbox": v.bbox,
                "time": now
            })

            # Two-tier enforcement: auto-issue only when confident AND we know
            # who to bill. Everything else queues for a human.
            issue = (v.confidence >= self.cfg.rules.auto_issue_confidence
                     and bool(plate) and v.fine > 0)
            status = "issued" if issue else "review"

            crop_path, clip_path = self.evidence.capture(
                frame, v.bbox, v.vtype, v.track_id)

            self.db.log_violation(
                camera_id=self.cfg.geometry.camera_id,
                track_id=v.track_id, vtype=v.vtype, severity=v.severity,
                confidence=v.confidence, fine=v.fine, plate=plate,
                plate_conf=plate_conf, status=status,
                measured_value=v.measured_value, reasons=v.reasons,
                evidence_path=crop_path, clip_path=clip_path,
                lat=self.cfg.geometry.latitude,
                lon=self.cfg.geometry.longitude)

            # Dispatch real-time Telegram mobile alert
            try:
                debug_log(f"[engine] Preparing to dispatch alert for track {v.track_id}, type {v.vtype}")
                job = AlertJob(
                    vtype=v.vtype,
                    track_id=v.track_id,
                    severity=v.severity,
                    confidence=v.confidence,
                    fine=v.fine,
                    plate=plate,
                    camera_id=self.cfg.geometry.camera_id,
                    lat=self.cfg.geometry.latitude,
                    lon=self.cfg.geometry.longitude,
                    reasons=v.reasons,
                    evidence_path=crop_path
                )
                res = self.alerts.dispatch(job)
                debug_log(f"[engine] Dispatch returned {res}")
            except Exception as e:
                import traceback
                debug_log(f"[engine] ERROR during dispatch: {e}\n{traceback.format_exc()}")

            # Plate image must ONLY be a license plate crop, never full vehicle evidence crop
            plate_img = getattr(tr, 'plate_img', '') if tr else ''

            record = {
                "type": v.vtype, "track_id": v.track_id,
                "confidence": v.confidence, "fine": v.fine,
                "severity": v.severity, "plate": plate, "status": status,
                "reasons": v.reasons, "evidence": crop_path,
                "crop_path": crop_path,
                "plate_img": plate_img,
                "clip": clip_path, "frame": frame_idx,
                "vehicle_type": tr.label.capitalize() if tr and tr.label else "Vehicle",
            }
            self.live_violations.appendleft(record)
            new.append(record)
        return new

    # ------------------------------------------------------------------ #

    # ------------------------------------------------------------------ #

    def _log_sightings(self, frame_idx: int) -> None:
        """Log a single checkpoint sighting per vehicle per camera passage.
        Also checks plates against the blacklist for instant alerts."""
        geo = self.cfg.geometry
        now = time.time()
        for tid, tr in self.registry.tracks.items():
            if not tr.plate:
                continue
            norm_plate = "".join(c for c in tr.plate.upper() if c.isalnum())
            if not norm_plate:
                continue

            # Log checkpoint sighting once per plate per camera passage
            if not getattr(tr, 'sighting_logged', False) or tr.last_sighting_cam != geo.camera_id:
                last_seen = self._anpr_broadcast_cooldown.get(norm_plate, 0.0)
                if (now - last_seen) > 60.0:
                    self._anpr_broadcast_cooldown[norm_plate] = now
                    speed = tr.effective_speed_kmh(default_speed=float(self.cfg.rules.speed_limit_kmh))
                    self.db.log_sighting(tr.plate, geo.camera_id,
                                         geo.latitude, geo.longitude, bool(tr.logged),
                                         speed_kmh=speed)
                    tr.sighting_logged = True
                    tr.last_sighting_cam = geo.camera_id

            # Blacklist & Anomaly checks (run once per vehicle passage)
            if not getattr(tr, '_blacklist_alerted', False):
                tr._blacklist_alerted = True
                # Anomaly detection
                anom = self.anomaly_detector.check_sighting(
                    tr.plate, geo.camera_id, geo.latitude, geo.longitude)
                if anom:
                    self._anomaly_hits.append({
                        "plate": anom.plate,
                        "type": anom.anomaly_type,
                        "description": anom.description,
                        "camera_id": anom.camera_id,
                        "severity": anom.severity,
                    })
                    self.alerts.enqueue(AlertJob(
                        vtype="ROUTE_ANOMALY",
                        track_id=tid,
                        severity=anom.severity,
                        confidence=1.0,
                        fine=0,
                        plate=anom.plate,
                        camera_id=anom.camera_id,
                        lat=anom.lat,
                        lon=anom.lon,
                        reasons=[f"⚠️ {anom.description}"],
                        evidence_path=None,
                    ))

                # Blacklist check
                bl = self.db.check_blacklist(tr.plate)
                if bl:
                    self._blacklist_hits.append({
                        "plate": tr.plate,
                        "reason": bl.get("reason", ""),
                        "severity": bl.get("severity", "high"),
                        "camera_id": geo.camera_id,
                        "track_id": tid,
                    })
                    # Dispatch immediate Telegram alert
                    self.alerts.enqueue(AlertJob(
                        vtype="BLACKLIST_HIT",
                        track_id=tid,
                        severity="critical",
                        confidence=1.0,
                        fine=0,
                        plate=tr.plate,
                        camera_id=geo.camera_id,
                        lat=geo.latitude,
                        lon=geo.longitude,
                        reasons=[f"🚨 BLACKLISTED: {bl.get('reason', 'Flagged vehicle')}"],
                        evidence_path=None,
                    ))

    def _log_flow(self, graph) -> None:
        """Congestion analytics. Nearly free, and arguably more useful to a
        city than the fines: queue length and mean speed per junction over time
        is exactly the data traffic engineers do not have."""
        now = time.time()
        if now - self._last_flow_log < 5.0:
            return
        self._last_flow_log = now
        vehicles = graph.vehicles()
        speeds = [t.speed_kmh for t in self.registry.tracks.values()
                  if t.speed_kmh is not None]
        stopped = sum(1 for t in self.registry.tracks.values()
                      if t.speed_kmh is not None and t.speed_kmh < 5.0)
        self.db.log_flow(self.cfg.geometry.camera_id, len(vehicles),
                         float(np.mean(speeds)) if speeds else 0.0, stopped)

    def reset(self) -> None:
        self.detector.reset_tracks()
        self.registry.tracks.clear()
        self.live_violations.clear()
        self._plate_violation_cooldown.clear()
        self._anpr_broadcast_cooldown.clear()
        self._recent_violation_boxes.clear()
        self._new_anpr_events.clear()
        self._blacklist_hits.clear()
        self._anomaly_hits.clear()
        self._frame_times.clear()

    def close(self) -> None:
        self.ocr.stop()
        self.alerts.stop()
        self.evidence.stop()
        self.db.close()





from .alerts import TelegramAlertService, AlertJob