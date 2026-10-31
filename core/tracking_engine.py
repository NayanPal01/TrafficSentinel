"""
Multi-Camera ANPR Vehicle Tracking with Branch Prediction.

Handles:
1. Dead-reckoning along road polylines at estimated vehicle speed.
2. Fork detection and multi-branch spawning with equal/weighted probability.
3. Downstream camera confirmation with fuzzy plate matching (Levenshtein <= 2).
4. Pruning / vanishing of unconfirmed sibling branches.
5. ETA computation, grace windows, and lost-track timeout cleanup.
6. Event streaming for real-time WebSockets and Leaflet map visualization.
"""

from __future__ import annotations
import copy
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from core.road_network import RoadEdge, RoadNetwork

logger = logging.getLogger("trafficsentinel.tracking_engine")


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculates Levenshtein edit distance between two strings."""
    if s1 == s2:
        return 0
    if not s1:
        return len(s2)
    if not s2:
        return len(s1)
    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def compute_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates compass heading (0-360 degrees) from point 1 to point 2."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    bearing = (math.degrees(math.atan2(y, x)) + 360.0) % 360.0
    return round(bearing, 1)


class PolylineInterpolator:
    """Interpolates position and heading along a polyline given traveled distance in meters."""

    @staticmethod
    def interpolate(edge: RoadEdge, distance_traveled_m: float) -> Tuple[float, float, float, float]:
        """
        Returns (latitude, longitude, bearing, progress_pct).
        Progress percentage is bounded 0.0 - 100.0%.
        """
        polyline = edge.polyline
        if not polyline:
            return 0.0, 0.0, 0.0, 0.0
        if len(polyline) == 1 or distance_traveled_m <= 0.0:
            p0 = polyline[0]
            p1 = polyline[1] if len(polyline) > 1 else p0
            bearing = compute_bearing(p0[0], p0[1], p1[0], p1[1])
            return p0[0], p0[1], bearing, 0.0

        cum = edge.cum_distances
        total_dist = edge.distance_m
        if distance_traveled_m >= total_dist or not cum:
            p_end = polyline[-1]
            p_prev = polyline[-2] if len(polyline) > 1 else p_end
            bearing = compute_bearing(p_prev[0], p_prev[1], p_end[0], p_end[1])
            return p_end[0], p_end[1], bearing, 100.0

        # Binary or linear search for segment
        seg_idx = 0
        for i in range(len(cum) - 1):
            if cum[i] <= distance_traveled_m <= cum[i + 1]:
                seg_idx = i
                break
        else:
            seg_idx = max(0, len(cum) - 2)

        seg_start = cum[seg_idx]
        seg_end = cum[seg_idx + 1]
        seg_len = seg_end - seg_start
        t = (distance_traveled_m - seg_start) / seg_len if seg_len > 1e-4 else 0.0
        t = max(0.0, min(1.0, t))

        p1 = polyline[seg_idx]
        p2 = polyline[seg_idx + 1]

        lat = p1[0] + (p2[0] - p1[0]) * t
        lon = p1[1] + (p2[1] - p1[1]) * t
        bearing = compute_bearing(p1[0], p1[1], p2[0], p2[1])
        progress_pct = min(100.0, max(0.0, (distance_traveled_m / total_dist) * 100.0))

        return round(lat, 6), round(lon, 6), bearing, round(progress_pct, 1)


@dataclass
class VehicleBranchTrack:
    """Represents an active track instance (either confirmed or predicted fork branch)."""
    instance_id: str
    plate: str
    plate_norm: str
    camera_origin: str        # Initial camera sighting
    current_edge_id: str
    from_node: str
    to_node: str
    speed_kmh: float
    start_ts: float           # Time when travel began on current edge
    status: str = "confirmed" # 'confirmed' | 'predicted' | 'vanished' | 'lost'
    confidence: float = 1.0   # 1.0 for confirmed; 1/N for predicted forks
    branch_label: str = "Direct Route"
    sibling_ids: List[str] = field(default_factory=list)
    vanish_ts: Optional[float] = None
    last_lat: float = 0.0
    last_lon: float = 0.0
    last_bearing: float = 0.0
    progress_pct: float = 0.0
    eta_seconds: float = 0.0
    history_nodes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "plate": self.plate,
            "plate_norm": self.plate_norm,
            "camera_origin": self.camera_origin,
            "edge_id": self.current_edge_id,
            "from_node": self.from_node,
            "to_node": self.to_node,
            "speed_kmh": round(self.speed_kmh, 1),
            "status": self.status,
            "confidence": round(self.confidence, 2),
            "branch_label": self.branch_label,
            "lat": self.last_lat,
            "lon": self.last_lon,
            "bearing": self.last_bearing,
            "progress_pct": self.progress_pct,
            "eta_seconds": round(max(0.0, self.eta_seconds), 1),
            "sibling_ids": self.sibling_ids,
            "vanish_ts": self.vanish_ts,
            "history_nodes": self.history_nodes
        }


class MultiCameraTracker:
    """
    Continuous dead-reckoning engine with branch prediction,
    fuzzy plate matching across cameras, and branch lifecycle management.
    """

    def __init__(self, road_network: RoadNetwork,
                 on_event_callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.rn = road_network
        self.on_event = on_event_callback
        # instance_id -> VehicleBranchTrack
        self.active_tracks: Dict[str, VehicleBranchTrack] = {}
        # plate_norm -> list of instance_ids
        self.plate_to_instances: Dict[str, Set[str]] = {}
        # Tracking history for audit and analytics
        self.completed_tracks: List[Dict[str, Any]] = []

    def _emit(self, event_type: str, data: Dict[str, Any]) -> None:
        if self.on_event:
            try:
                payload = {"type": event_type, "ts": time.time(), **data}
                self.on_event(payload)
            except Exception as e:
                logger.error(f"Error emitting tracking event: {e}")

    # ------------------------------------------------------------------ #
    # Sighting Registration & Downstream Confirmation
    # ------------------------------------------------------------------ #

    def register_sighting(self, plate: str, camera_id: str,
                          speed_kmh: Optional[float] = None,
                          ts: Optional[float] = None) -> List[str]:
        """
        Called when any camera detects a plate.
        1. Searches existing tracks for exact or fuzzy match (Levenshtein <= 2).
        2. If matched: confirms target branch, prunes siblings with vanish animation.
        3. If no match: initiates new confirmed track along downstream edges.
        Returns list of active instance_ids for this vehicle.
        """
        now = ts if ts is not None else time.time()
        plate_clean = plate.strip().upper()
        plate_norm = "".join(ch for ch in plate_clean if ch.isalnum())
        if not plate_norm:
            return []

        # 1. Fuzzy match against all active tracks
        matched_instance = self._find_fuzzy_match(plate_norm, camera_id)

        if matched_instance:
            if matched_instance.from_node == camera_id and (now - matched_instance.start_ts < 30.0):
                # Vehicle is still in vicinity of origin camera; do not duplicate tracking trip
                return [matched_instance.instance_id]
            return self._handle_downstream_confirmation(matched_instance, plate_clean,
                                                        camera_id, speed_kmh, now)
        else:
            return self._handle_new_vehicle_sighting(plate_clean, plate_norm,
                                                     camera_id, speed_kmh, now)

    def _find_fuzzy_match(self, plate_norm: str, camera_id: str) -> Optional[VehicleBranchTrack]:
        """
        Finds active track matching plate with Levenshtein distance <= 2.
        Prioritizes tracks whose destination edge leads to this camera.
        """
        best_track: Optional[VehicleBranchTrack] = None
        best_score = 999

        for tr in list(self.active_tracks.values()):
            if tr.status == "vanished" or tr.status == "lost":
                continue

            dist = levenshtein_distance(plate_norm, tr.plate_norm)
            max_allowed = 1 if len(plate_norm) < 6 else 2

            if dist <= max_allowed:
                # Bonus if track is approaching this camera
                is_approaching = (tr.to_node == camera_id)
                effective_score = dist - (0.5 if is_approaching else 0.0)

                if effective_score < best_score:
                    best_score = effective_score
                    best_track = tr

        return best_track

    def _handle_downstream_confirmation(self, matched_track: VehicleBranchTrack,
                                        confirmed_plate: str, camera_id: str,
                                        speed_kmh: Optional[float],
                                        now: float) -> List[str]:
        """
        Confirms target branch, prunes sibling branches, and advances onto downstream path.
        """
        confirmed_id = matched_track.instance_id
        original_plate = matched_track.plate
        effective_speed = speed_kmh if (speed_kmh and speed_kmh > 5.0) else matched_track.speed_kmh

        # 1. Prune / vanish all sibling branches spawned from same fork
        pruned_ids = []
        for sib_id in matched_track.sibling_ids:
            if sib_id in self.active_tracks and sib_id != confirmed_id:
                sib = self.active_tracks[sib_id]
                sib.status = "vanished"
                sib.vanish_ts = now
                pruned_ids.append(sib_id)

        # 2. Confirm matched branch
        matched_track.status = "confirmed"
        matched_track.confidence = 1.0
        matched_track.plate = confirmed_plate
        matched_track.plate_norm = "".join(ch for ch in confirmed_plate if ch.isalnum())
        matched_track.speed_kmh = effective_speed
        matched_track.history_nodes.append(camera_id)
        matched_track.sibling_ids = []

        logger.info(f"[Tracker] Confirmed branch {confirmed_id} for plate {confirmed_plate} at {camera_id}. "
                    f"Pruned siblings: {pruned_ids}")

        # Emit confirmation event
        self._emit("branch_confirmed", {
            "confirmed_id": confirmed_id,
            "plate": confirmed_plate,
            "original_plate": original_plate,
            "camera_id": camera_id,
            "speed_kmh": effective_speed,
            "pruned_ids": pruned_ids
        })

        # 3. Transition forward from this confirmed camera node
        return self._transition_from_node(matched_track, camera_id, effective_speed, now)

    def _handle_new_vehicle_sighting(self, plate: str, plate_norm: str,
                                     camera_id: str, speed_kmh: Optional[float],
                                     now: float) -> List[str]:
        """Initiates tracking from a camera capture node."""
        node = self.rn.get_node(camera_id)
        if not node:
            # Fallback to nearest network node so tracking is never silently dropped
            nearest_id = self.rn.get_nearest_node(22.5520, 88.3590) or "CAM-03"
            logger.info(f"[Tracker] Camera node '{camera_id}' mapped to network node '{nearest_id}'")
            node = self.rn.get_node(nearest_id)
            camera_id = nearest_id

        speed = speed_kmh if (speed_kmh and speed_kmh > 5.0) else 40.0
        outgoing = self.rn.get_outgoing_edges(camera_id)

        # Emit initial sighting event
        self._emit("vehicle_sighting", {
            "plate": plate,
            "camera_id": camera_id,
            "speed_kmh": speed,
            "lat": node.latitude if node else 22.5520,
            "lon": node.longitude if node else 88.3590
        })

        if not outgoing:
            # If camera has no outgoing edges (terminal node), spawn stationary confirmed marker
            inst_id = f"{plate_norm}_{int(now)}_station"
            track = VehicleBranchTrack(
                instance_id=inst_id,
                plate=plate,
                plate_norm=plate_norm,
                camera_origin=camera_id,
                current_edge_id=f"{camera_id}->{camera_id}",
                from_node=camera_id,
                to_node=camera_id,
                speed_kmh=speed,
                start_ts=now,
                status="confirmed",
                confidence=1.0,
                branch_label=f"At {node.name if node else camera_id}",
                sibling_ids=[],
                last_lat=node.latitude if node else 22.5520,
                last_lon=node.longitude if node else 88.3590,
                last_bearing=0.0,
                progress_pct=100.0,
                eta_seconds=0.0,
                history_nodes=[camera_id]
            )
            self.active_tracks[inst_id] = track
            self.plate_to_instances.setdefault(plate_norm, set()).add(inst_id)
            logger.info(f"[Tracker] Spawned station track at {camera_id} for {plate}")
            return [inst_id]

        # Spawn track(s)
        return self._spawn_tracks_at_node(plate, plate_norm, camera_id, speed, now, outgoing)

    def _spawn_tracks_at_node(self, plate: str, plate_norm: str,
                              from_camera: str, speed_kmh: float, now: float,
                              edges: List[RoadEdge]) -> List[str]:
        """
        If 1 outgoing edge: spawns single confirmed track.
        If N > 1 outgoing edges (fork): spawns N predicted ghost tracks with equal confidence split.
        """
        is_fork = len(edges) > 1
        instance_ids = []
        sibling_ids = []

        # Generate unique instance IDs first so siblings can cross-reference
        base_id = f"{plate_norm}_{int(now)}"
        for i, edge in enumerate(edges):
            inst_id = f"{base_id}_b{i}_{edge.to_node}"
            instance_ids.append(inst_id)
            sibling_ids.append(inst_id)

        confidence = 1.0 if not is_fork else round(1.0 / len(edges), 2)
        status = "confirmed" if not is_fork else "predicted"

        for i, edge in enumerate(edges):
            inst_id = instance_ids[i]
            branch_label = f"Direct Route to {edge.to_node}" if not is_fork else f"Predicted Branch ({edge.to_node})"

            p0 = edge.polyline[0]
            track = VehicleBranchTrack(
                instance_id=inst_id,
                plate=plate,
                plate_norm=plate_norm,
                camera_origin=from_camera,
                current_edge_id=edge.edge_id,
                from_node=edge.from_node,
                to_node=edge.to_node,
                speed_kmh=speed_kmh,
                start_ts=now,
                status=status,
                confidence=confidence,
                branch_label=branch_label,
                sibling_ids=sibling_ids if is_fork else [],
                last_lat=p0[0],
                last_lon=p0[1],
                last_bearing=0.0,
                progress_pct=0.0,
                eta_seconds=(edge.distance_m / max(1.0, speed_kmh / 3.6)),
                history_nodes=[from_camera]
            )

            self.active_tracks[inst_id] = track
            self.plate_to_instances.setdefault(plate_norm, set()).add(inst_id)

        if is_fork:
            logger.info(f"[Tracker] Spawned {len(edges)} predicted branches at fork {from_camera} for {plate}: {instance_ids}")
            self._emit("branch_fork", {
                "parent_plate": plate,
                "fork_camera_id": from_camera,
                "spawned_branches": [self.active_tracks[tid].to_dict() for tid in instance_ids]
            })

        return instance_ids

    def _transition_from_node(self, track: VehicleBranchTrack, current_node: str,
                              speed_kmh: float, now: float) -> List[str]:
        """
        Advances track past a confirmed camera node into subsequent edges.
        """
        outgoing = self.rn.get_outgoing_edges(current_node)
        if not outgoing:
            # End of network
            logger.info(f"[Tracker] Vehicle {track.plate} reached perimeter node {current_node}.")
            track.status = "completed"
            return [track.instance_id]

        if len(outgoing) == 1:
            # Single downstream road
            edge = outgoing[0]
            track.current_edge_id = edge.edge_id
            track.from_node = edge.from_node
            track.to_node = edge.to_node
            track.start_ts = now
            track.speed_kmh = speed_kmh
            track.branch_label = f"Corridor to {edge.to_node}"
            track.progress_pct = 0.0
            track.eta_seconds = (edge.distance_m / max(1.0, speed_kmh / 3.6))
            return [track.instance_id]
        else:
            # Node is another downstream fork! Remove old single track and spawn predicted branches
            old_id = track.instance_id
            plate = track.plate
            plate_norm = track.plate_norm
            history = copy.deepcopy(track.history_nodes)

            # Clean up old single instance
            if old_id in self.active_tracks:
                del self.active_tracks[old_id]
            if plate_norm in self.plate_to_instances and old_id in self.plate_to_instances[plate_norm]:
                self.plate_to_instances[plate_norm].remove(old_id)

            new_ids = self._spawn_tracks_at_node(plate, plate_norm, current_node, speed_kmh, now, outgoing)
            for nid in new_ids:
                if nid in self.active_tracks:
                    self.active_tracks[nid].history_nodes = history
            return new_ids

    # ------------------------------------------------------------------ #
    # Dead-Reckoning Simulation Tick Loop
    # ------------------------------------------------------------------ #

    def tick(self, current_time: Optional[float] = None) -> List[Dict[str, Any]]:
        """
        Executes one dead-reckoning cycle:
        1. Advances every active vehicle along its edge polyline.
        2. Computes lat, lon, bearing, progress, and remaining ETA.
        3. Checks for edge arrival, fork transition, and lost-track timeouts.
        4. Purges vanished and expired tracks.
        Returns serialized list of vehicle positions for live map display.
        """
        now = current_time if current_time is not None else time.time()
        to_purge = []
        active_payloads = []

        for inst_id, tr in list(self.active_tracks.items()):
            # 1. Vanished track cleanup after fade grace window (2.5 seconds)
            if tr.status == "vanished":
                if tr.vanish_ts and (now - tr.vanish_ts > 2.5):
                    to_purge.append(inst_id)
                else:
                    active_payloads.append(tr.to_dict())
                continue

            # 2. Lost track cleanup after fade grace window
            if tr.status == "lost":
                if tr.vanish_ts and (now - tr.vanish_ts > 3.0):
                    to_purge.append(inst_id)
                else:
                    active_payloads.append(tr.to_dict())
                continue

            # 3. Dead reckoning calculation along edge
            if tr.from_node == tr.to_node:
                # Stationary vehicle at terminal camera node (remain visible for 60s)
                if now - tr.start_ts > 60.0:
                    to_purge.append(inst_id)
                else:
                    active_payloads.append(tr.to_dict())
                continue

            edge = self.rn.get_edge(tr.from_node, tr.to_node)
            if not edge:
                to_purge.append(inst_id)
                continue

            elapsed_s = max(0.0, now - tr.start_ts)
            speed_m_s = max(1.0, (tr.speed_kmh * 1000.0) / 3600.0)
            distance_traveled_m = elapsed_s * speed_m_s
            total_dist_m = edge.distance_m
            expected_transit_s = total_dist_m / speed_m_s

            # Interpolate position
            lat, lon, bearing, progress = PolylineInterpolator.interpolate(edge, distance_traveled_m)
            tr.last_lat = lat
            tr.last_lon = lon
            tr.last_bearing = bearing
            tr.progress_pct = progress
            tr.eta_seconds = max(0.0, (total_dist_m - distance_traveled_m) / speed_m_s)

            # 4. Check for Lost / Timeout Grace Window
            # Grace window: 1.8x expected transit time or transit + 45s
            timeout_thresh_s = max(expected_transit_s + 45.0, expected_transit_s * 1.8)
            if elapsed_s > timeout_thresh_s:
                logger.info(f"[Tracker] Track {inst_id} ({tr.plate}) timed out on {edge.edge_id}. Marking lost.")
                tr.status = "lost"
                tr.vanish_ts = now
                self._emit("track_expired", {
                    "instance_id": inst_id,
                    "plate": tr.plate,
                    "reason": "eta_timeout",
                    "last_edge": edge.edge_id
                })
                active_payloads.append(tr.to_dict())
                continue

            # 5. Check if vehicle reached the end node of the edge
            if distance_traveled_m >= total_dist_m:
                # Arrived at destination node
                end_node = tr.to_node
                outgoing = self.rn.get_outgoing_edges(end_node)

                if not outgoing:
                    # Perimeter edge reached, stay parked at camera waiting for sighting or timeout
                    tr.progress_pct = 100.0
                    tr.eta_seconds = 0.0
                    active_payloads.append(tr.to_dict())
                    continue

                if len(outgoing) == 1:
                    # Single road continuation: seamless handoff
                    next_edge = outgoing[0]
                    tr.current_edge_id = next_edge.edge_id
                    tr.from_node = next_edge.from_node
                    tr.to_node = next_edge.to_node
                    tr.start_ts = now
                    tr.progress_pct = 0.0
                    tr.eta_seconds = (next_edge.distance_m / speed_m_s)
                    tr.history_nodes.append(end_node)
                else:
                    # Fork reached without camera sighting: spawn next level fork branches
                    self._transition_from_node(tr, end_node, tr.speed_kmh, now)
                    continue

            active_payloads.append(tr.to_dict())

        # Purge dead instances
        for pid in to_purge:
            if pid in self.active_tracks:
                p_track = self.active_tracks.pop(pid)
                p_norm = p_track.plate_norm
                if p_norm in self.plate_to_instances:
                    self.plate_to_instances[p_norm].discard(pid)
                    if not self.plate_to_instances[p_norm]:
                        del self.plate_to_instances[p_norm]

        # Broadcast tracking tick
        if active_payloads or to_purge:
            self._emit("tracking_tick", {"vehicles": active_payloads})

        return active_payloads
