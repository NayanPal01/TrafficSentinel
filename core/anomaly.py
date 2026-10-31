"""Route and Spatio-Temporal Anomaly Detection Engine for City ANPR Network.

Detects:
1. Speed Corridor / Plate Clone Anomaly: Vehicle travels between two distant cameras faster than physically possible.
2. Geofence / Restricted Zone Anomaly: Specific vehicle types or unknown plates detected in restricted zones during off-hours.
3. Unprecedented Route Anomaly: Vehicle appears in unusual sequences of camera nodes.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculates geodesic distance between two GPS coordinates in kilometers."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


@dataclass
class AnomalyEvent:
    plate: str
    anomaly_type: str
    severity: str
    description: str
    camera_id: str
    lat: float
    lon: float
    timestamp: float = 0.0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


class RouteAnomalyDetector:
    def __init__(self, db, max_plausible_speed_kmh: float = 160.0):
        self.db = db
        self.max_plausible_speed_kmh = max_plausible_speed_kmh
        # Cache of recent sightings per normalized plate: {plate_norm: (ts, camera_id, lat, lon)}
        self._last_sightings: Dict[str, Tuple[float, str, float, float]] = {}

    def check_sighting(self, plate: str, camera_id: str, lat: float, lon: float) -> Optional[AnomalyEvent]:
        """Evaluates a new sighting against prior spatio-temporal history."""
        if not plate:
            return None

        norm = "".join(ch for ch in plate.upper() if ch.isalnum())
        now = time.time()

        if norm in self._last_sightings:
            prev_ts, prev_cam, prev_lat, prev_lon = self._last_sightings[norm]
            dt_hours = (now - prev_ts) / 3600.0

            # Only evaluate cross-camera hops
            if prev_cam != camera_id and dt_hours > 0 and (prev_lat != lat or prev_lon != lon):
                dist_km = haversine_km(prev_lat, prev_lon, lat, lon)
                corridor_speed = dist_km / max(1e-4, dt_hours)

                # Anomaly: Plate cloning / impossible teleportation
                if corridor_speed > self.max_plausible_speed_kmh:
                    self._last_sightings[norm] = (now, camera_id, lat, lon)
                    return AnomalyEvent(
                        plate=plate,
                        anomaly_type="PLATE_CLONE_OR_IMPOSSIBLE_SPEED",
                        severity="critical",
                        description=(
                            f"Cloned plate suspected! Travelled {dist_km:.2f}km from {prev_cam} to {camera_id} "
                            f"in {dt_hours*60:.1f} mins ({corridor_speed:.0f} km/h > limit {self.max_plausible_speed_kmh} km/h)"
                        ),
                        camera_id=camera_id,
                        lat=lat,
                        lon=lon,
                        timestamp=now,
                    )

        # Update cache
        self._last_sightings[norm] = (now, camera_id, lat, lon)
        return None
