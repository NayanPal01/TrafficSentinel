"""YOLOv8 / YOLO26 detection + tracking.

YOLO26 (Jan 2026) key differences vs YOLOv8 that affect this module:

1. NMS-free end-to-end design — no Non-Maximum Suppression post-processing.
   ByteTrack still runs on top (it needs detections, not raw anchors), so
   the tracking call is unchanged.

2. DFL removed — simpler output head, marginally faster OpenVINO/ONNX export.

3. Same ultralytics YOLO() API — YOLO('yolo26n.pt') works identically to
   YOLO('yolov8n.pt'). No code changes needed in the hot loop.

4. Auto-download — on first use, ultralytics downloads yolo26n.pt (~5 MB)
   from GitHub releases automatically.

Backend selection is unchanged: OpenVINO on Intel CPU, TensorRT on Jetson.
Tracking is ALWAYS on — ByteTrack costs ~1 ms and every downstream
optimisation (OCR dedup, red-light crossing, wrong-way, near-miss) depends
on stable track_ids.
"""

from __future__ import annotations

import platform
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# COCO classes we care about -> our category taxonomy
COCO_MAP: Dict[int, tuple] = {
    0: ("person", "person", None),
    1: ("bicycle", "vehicle", "bicycle"),
    2: ("car", "vehicle", "car"),
    3: ("motorcycle", "vehicle", "motorcycle"),
    5: ("bus", "vehicle", "bus"),
    7: ("truck", "vehicle", "truck"),
    9: ("traffic light", "traffic_light", None),
}
KEEP_CLASSES = sorted(COCO_MAP.keys())

TWO_WHEELERS = {"motorcycle", "bicycle"}
ENCLOSED = {"car", "bus", "truck"}


def _detect_backend() -> str:
    """Pick the fastest available runtime for this machine."""
    machine = platform.machine().lower()
    try:
        import torch
        if torch.cuda.is_available():
            # Jetson boards report aarch64 and benefit hugely from TensorRT,
            # but export takes minutes - leave it opt-in via config.
            return "cuda"
    except Exception:
        pass
    if machine in ("aarch64", "arm64"):
        return "pytorch"          # RPi / Jetson CPU: NCNN is better, see README
    try:
        import openvino  # noqa: F401
        return "openvino"
    except Exception:
        pass
    try:
        import onnxruntime  # noqa: F401
        return "onnx"
    except Exception:
        pass
    return "pytorch"


class Detector:
    def __init__(self, cfg):
        from ultralytics import YOLO

        self.cfg = cfg
        backend = cfg.backend if cfg.backend != "auto" else _detect_backend()
        self.backend = backend
        weights = Path(cfg.weights)

        path, self.device = self._prepare(YOLO, weights, backend, cfg)
        self.model = YOLO(str(path), task="detect")
        self.warm = False
        self.last_infer_ms = 0.0
        self._last_detections: List[dict] = []
        self._last_frame_idx: int = -1

        # Enable cuDNN benchmark for auto-tuned tensor core convolutions
        try:
            import torch
            if torch.cuda.is_available():
                torch.backends.cudnn.benchmark = True
        except Exception:
            pass

    # ------------------------------------------------------------------ #

    def _prepare(self, YOLO, weights: Path, backend: str, cfg):
        """Export once, reuse forever. Returns (model_path, device_string).

        YOLO26 exports cleanly to OpenVINO/ONNX because DFL is removed,
        making the output head simpler. The export call is identical to YOLOv8.
        """
        stem = weights.with_suffix("")

        if backend == "openvino":
            target = Path(f"{stem}_openvino_model")
            if not target.exists():
                print(f"[detector] exporting {weights.name} -> OpenVINO "
                      f"(one-time, ~30s)...")
                YOLO(str(weights)).export(format="openvino", imgsz=cfg.imgsz,
                                          half=False, dynamic=False)
            return target, "cpu"

        if backend == "onnx":
            target = Path(f"{stem}.onnx")
            if not target.exists():
                print(f"[detector] exporting {weights.name} -> ONNX "
                      f"(one-time)...")
                YOLO(str(weights)).export(format="onnx", imgsz=cfg.imgsz,
                                          simplify=True, dynamic=False)
            return target, "cpu"

        if backend == "tensorrt":
            target = Path(f"{stem}.engine")
            if not target.exists():
                print("[detector] exporting -> TensorRT (one-time, minutes)...")
                YOLO(str(weights)).export(format="engine", imgsz=cfg.imgsz,
                                          half=True)
            return target, "cuda:0"

        if backend == "ncnn":
            target = Path(f"{stem}_ncnn_model")
            if not target.exists():
                print("[detector] exporting -> NCNN (one-time)...")
                YOLO(str(weights)).export(format="ncnn", imgsz=cfg.imgsz)
            return target, "cpu"

        return weights, ("cuda:0" if backend == "cuda" else cfg.device)

    # ------------------------------------------------------------------ #

    def warmup(self, shape=(720, 1280, 3)) -> None:
        """First inference is 5-10x slower (allocator + graph build). Burn it
        during startup rather than on the user's first frame."""
        if self.warm:
            return
        dummy = np.zeros(shape, dtype=np.uint8)
        for _ in range(2):
            self.model.track(dummy, imgsz=self.cfg.imgsz, verbose=False,
                             persist=True, classes=KEEP_CLASSES,
                             tracker=self.cfg.tracker, device=self.device)
        self.model.predictor.trackers[0].reset() if hasattr(
            self.model, "predictor") else None
        self.warm = True

    def reset_tracks(self) -> None:
        try:
            for t in self.model.predictor.trackers:
                t.reset()
        except Exception:
            pass

    # ------------------------------------------------------------------ #

    def detect(self, frame: np.ndarray, frame_idx: int = -1) -> List[dict]:
        """Run detection + tracking on one BGR frame with frame-stride optimization."""
        stride = getattr(self.cfg, "frame_stride", 1)
        if stride > 1 and frame_idx >= 0 and self._last_detections:
            if (frame_idx % stride) != 0:
                self.last_infer_ms = 0.2
                return [d.copy() for d in self._last_detections]

        t0 = time.perf_counter()
        results = self.model.track(
            frame,
            imgsz=self.cfg.imgsz,
            conf=self.cfg.conf,
            iou=self.cfg.iou,
            classes=KEEP_CLASSES,
            persist=True,
            tracker=self.cfg.tracker,
            device=self.device,
            verbose=False,
        )
        self.last_infer_ms = (time.perf_counter() - t0) * 1000.0

        if not results:
            self._last_detections = []
            return []
        boxes = results[0].boxes
        if boxes is None or boxes.id is None and len(boxes) == 0:
            self._last_detections = []
            return []

        xyxy = boxes.xyxy.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)
        conf = boxes.conf.cpu().numpy()
        ids = (boxes.id.cpu().numpy().astype(int)
               if boxes.id is not None else np.full(len(cls), -1))

        out: List[dict] = []
        for i in range(len(cls)):
            meta = COCO_MAP.get(int(cls[i]))
            if meta is None:
                continue
            label, category, vtype = meta
            x1, y1, x2, y2 = [float(v) for v in xyxy[i]]
            out.append({
                "bbox": (x1, y1, x2, y2),
                "cls_id": int(cls[i]),
                "label": label,
                "conf": float(conf[i]),
                "category": category,
                "vehicle_type": vtype,
                "track_id": int(ids[i]),
                "cx": (x1 + x2) / 2.0,
                "cy": (y1 + y2) / 2.0,
                "foot": ((x1 + x2) / 2.0, y2),   # ground contact point
                "w": x2 - x1,
                "h": y2 - y1,
            })

        self._last_detections = out
        self._last_frame_idx = frame_idx
        return out
