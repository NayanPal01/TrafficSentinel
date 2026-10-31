"""Per-track state.

This replaces the original 150-pixel centre-distance deduplication heuristic.
With stable track IDs, "have I already fined this vehicle for this offence"
becomes a set lookup instead of a spatial guess - which also fixes the case
where two motorcycles pass within 150 px of each other and the second one is
silently swallowed as a duplicate of the first.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Set, Tuple

import numpy as np


@dataclass
class Track:
    track_id: int
    label: str
    vehicle_type: Optional[str]
    first_frame: int
    last_frame: int
    bbox: Tuple[float, float, float, float]
    conf: float

    # (frame_idx, image_foot_point, world_point or None)
    history: Deque = field(default_factory=lambda: deque(maxlen=90))

    speed_samples: Deque = field(default_factory=lambda: deque(maxlen=9))
    speed_kmh: Optional[float] = None
    world_velocity: Optional[Tuple[float, float]] = None

    plate: Optional[str] = None
    plate_conf: float = 0.0
    ocr_attempts: int = 0
    ocr_pending: bool = False
    sighting_logged: bool = False
    last_sighting_cam: Optional[str] = None

    helmet_status: str = "UNKNOWN"      # HELMET | NO_HELMET | UNCERTAIN
    helmet_conf: float = 0.0
    rider_ids: Set[int] = field(default_factory=set)

    logged: Set[str] = field(default_factory=set)   # violation types already filed
    stationary_since: Optional[int] = None

    def age_frames(self) -> int:
        return self.last_frame - self.first_frame

    def effective_speed_kmh(self, default_speed: float = 40.0) -> float:
        """Returns estimated speed in km/h or falls back to posted limit."""
        if self.speed_kmh is not None and self.speed_kmh > 5.0:
            return float(round(self.speed_kmh, 1))
        return float(default_speed)


class TrackRegistry:
    def __init__(self, fps: float, ground, max_missing: int = 45):
        self.tracks: Dict[int, Track] = {}
        self.fps = max(1.0, float(fps))
        self.ground = ground
        self.max_missing = max_missing

    # ------------------------------------------------------------------ #

    def update(self, detections, frame_idx: int) -> None:
        for det in detections:
            tid = det["track_id"]
            if tid < 0:
                continue
            tr = self.tracks.get(tid)
            if tr is None:
                # Track identity stitching: check if this is an ID switch of a recently seen track
                matched_prev_id = None
                best_iou = 0.0
                nx1, ny1, nx2, ny2 = det["bbox"]
                n_area = max(1.0, (nx2 - nx1) * (ny2 - ny1))

                for old_id, old_t in list(self.tracks.items()):
                    if old_id == tid or old_t.last_frame == frame_idx:
                        continue
                    if (frame_idx - old_t.last_frame <= 25) and old_t.label == det["label"]:
                        ox1, oy1, ox2, oy2 = old_t.bbox
                        ix1 = max(nx1, ox1)
                        iy1 = max(ny1, oy1)
                        ix2 = min(nx2, ox2)
                        iy2 = min(ny2, oy2)
                        if ix2 > ix1 and iy2 > iy1:
                            inter = (ix2 - ix1) * (iy2 - iy1)
                            union = n_area + max(1.0, (ox2 - ox1) * (oy2 - oy1)) - inter
                            iou = inter / union
                            if iou > 0.30 and iou > best_iou:
                                best_iou = iou
                                matched_prev_id = old_id

                if matched_prev_id is not None:
                    # Stitched! Inherit identity, plate, and violation status
                    old_t = self.tracks.pop(matched_prev_id)
                    old_t.track_id = tid
                    tr = old_t
                    self.tracks[tid] = tr
                else:
                    tr = Track(track_id=tid, label=det["label"],
                               vehicle_type=det["vehicle_type"],
                               first_frame=frame_idx, last_frame=frame_idx,
                               bbox=det["bbox"], conf=det["conf"])
                    self.tracks[tid] = tr

            tr.last_frame = frame_idx
            tr.bbox = det["bbox"]
            tr.conf = max(tr.conf, det["conf"])

            foot = det["foot"]
            world = self.ground.to_world(foot) if self.ground.calibrated else None
            tr.history.append((frame_idx, foot, world))
            det["_track"] = tr

            self._update_kinematics(tr)

        self._evict(frame_idx)

    def _update_kinematics(self, tr: Track) -> None:
        """Speed in km/h from world-plane displacement with trip-line fallback."""
        if len(tr.history) < 4:
            return
        # Compare against a sample ~0.5 s back for stable speed estimation
        lookback = max(3, int(self.fps * 0.5))
        idx = max(0, len(tr.history) - 1 - lookback)
        f0, foot0, w0 = tr.history[idx]
        f1, foot1, w1 = tr.history[-1]
        if f1 <= f0:
            return

        dt = (f1 - f0) / self.fps
        if dt <= 1e-3:
            return

        if self.ground.calibrated and w0 is not None and w1 is not None:
            # Avoid horizon singularity where tiny pixel jitter causes huge displacement
            if foot1[1] < 120 or foot0[1] < 120:
                return
            dx, dy = w1[0] - w0[0], w1[1] - w0[1]
            dist = float(np.hypot(dx, dy))
            raw_speed = (dist / dt) * 3.6
            if raw_speed <= 160.0:
                tr.world_velocity = (dx / dt, dy / dt)
                tr.speed_samples.append(raw_speed)
        else:
            # Virtual trip-line / optical displacement fallback
            dy_px = abs(foot1[1] - foot0[1])
            dx_px = abs(foot1[0] - foot0[0])
            pixel_dist = float(np.hypot(dx_px, dy_px))
            est_dist_m = pixel_dist * 0.045
            raw_speed = (est_dist_m / dt) * 3.6
            if 10.0 <= raw_speed <= 140.0:
                tr.speed_samples.append(raw_speed)

        if len(tr.speed_samples) >= 3:
            # Rolling median across clean samples
            tr.speed_kmh = float(np.median(list(tr.speed_samples)))

    def _evict(self, frame_idx: int) -> None:
        stale = [tid for tid, t in self.tracks.items()
                 if frame_idx - t.last_frame > self.max_missing]
        for tid in stale:
            del self.tracks[tid]

    # ------------------------------------------------------------------ #

    def get(self, tid: int) -> Optional[Track]:
        return self.tracks.get(tid)

    def already_logged(self, tid: int, vtype: str) -> bool:
        tr = self.tracks.get(tid)
        return bool(tr and vtype in tr.logged)

    def mark_logged(self, tid: int, vtype: str) -> None:
        tr = self.tracks.get(tid)
        if tr:
            tr.logged.add(vtype)

    def displacement_world(self, tr: Track, min_frames: int = 5):
        if len(tr.history) < min_frames:
            return None
        w_start = next((w for _, _, w in tr.history if w is not None), None)
        w_end = tr.history[-1][2]
        if w_start is None or w_end is None:
            return None
        return (w_end[0] - w_start[0], w_end[1] - w_start[1])


