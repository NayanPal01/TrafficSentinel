"""SQLite persistence.

Writes happen on a background thread with a bounded queue, for the same reason
OCR does: a synchronous INSERT plus an fsync is 5-15 ms, and at 25 FPS with a
busy junction that is enough to visibly hitch the loop. WAL mode also lets the
dashboard read while the pipeline writes.

The `status` column implements the two-tier enforcement model: violations above
the auto-issue confidence threshold become challans, everything else lands in a
human review queue. That is how real enforcement systems work, and it is the
honest place to put an uncertain helmet call.
"""

from __future__ import annotations

import queue
import sqlite3
import threading
import time
from pathlib import Path
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS violations (
    violation_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts             REAL    NOT NULL,
    camera_id      TEXT    NOT NULL,
    track_id       INTEGER,
    violation_type TEXT    NOT NULL,
    severity       TEXT,
    confidence     REAL,
    fine_amount    INTEGER,
    plate_number   TEXT,
    plate_conf     REAL,
    status         TEXT    NOT NULL DEFAULT 'review',
    measured_value REAL,
    reasons        TEXT,
    evidence_path  TEXT,
    clip_path      TEXT,
    latitude       REAL,
    longitude      REAL
);
CREATE INDEX IF NOT EXISTS idx_v_type   ON violations(violation_type);
CREATE INDEX IF NOT EXISTS idx_v_plate  ON violations(plate_number);
CREATE INDEX IF NOT EXISTS idx_v_status ON violations(status);
CREATE INDEX IF NOT EXISTS idx_v_ts     ON violations(ts);

CREATE TABLE IF NOT EXISTS sightings (
    sighting_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    ts           REAL NOT NULL,
    plate_number TEXT NOT NULL,
    plate_norm   TEXT NOT NULL,
    camera_id    TEXT,
    latitude     REAL,
    longitude    REAL,
    is_violation INTEGER DEFAULT 0,
    speed_kmh    REAL
);
CREATE INDEX IF NOT EXISTS idx_s_norm ON sightings(plate_norm);

CREATE TABLE IF NOT EXISTS flow_stats (
    ts         REAL,
    camera_id  TEXT,
    vehicles   INTEGER,
    mean_speed REAL,
    queue_len  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_fs_ts ON flow_stats(ts);
CREATE INDEX IF NOT EXISTS idx_fs_cam ON flow_stats(camera_id);

CREATE TABLE IF NOT EXISTS blacklist (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plate_norm   TEXT UNIQUE NOT NULL,
    plate_display TEXT NOT NULL,
    reason       TEXT,
    severity     TEXT DEFAULT 'high',
    added_ts     REAL,
    active       INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_bl_norm ON blacklist(plate_norm);

CREATE TABLE IF NOT EXISTS ocr_accuracy_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          REAL,
    track_id    INTEGER,
    raw_text    TEXT,
    final_text  TEXT,
    confidence  REAL,
    regex_valid INTEGER,
    pass_index  INTEGER
);

CREATE TABLE IF NOT EXISTS cameras (
    camera_id  TEXT PRIMARY KEY,
    name       TEXT NOT NULL,
    kind       TEXT DEFAULT 'junction',
    latitude   REAL NOT NULL,
    longitude  REAL NOT NULL,
    is_active  INTEGER DEFAULT 0
);
"""


def normalise_plate(text: Optional[str]) -> str:
    if not text:
        return ""
    return "".join(ch for ch in text.upper() if ch.isalnum())


class Database:
    def __init__(self, path: str, async_writes: bool = True):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()
        self._q: "queue.Queue[tuple]" = queue.Queue(maxsize=512)
        self._stop = threading.Event()
        self._thread = None
        self._async_writes = async_writes
        self._recent_sightings_cache: Dict[str, float] = {}
        if async_writes:
            self._thread = threading.Thread(target=self._writer, daemon=True)
            self._thread.start()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=5.0,
                              check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.row_factory = sqlite3.Row
        return con

    def _init_schema(self) -> None:
        con = self._connect()
        con.executescript(SCHEMA)
        # Migrate existing table if missing speed_kmh
        try:
            con.execute("ALTER TABLE sightings ADD COLUMN speed_kmh REAL")
            con.commit()
        except Exception:
            pass
        # Seed initial camera network if empty
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM cameras")
        if cur.fetchone()[0] == 0:
            initial_cams = [
                ("CAM-01", "Park St & Mirza Ghalib St (Junction)", "junction", 22.5526, 88.3539, 1),
                ("CAM-02", "Park St & Chowringhee Rd (Junction)", "junction", 22.5538, 88.3510, 0),
                ("CAM-03", "Park St - Free School Midway Corridor", "midway", 22.5522, 88.3555, 0),
                ("CAM-04", "Park St & Camac St (Junction)", "junction", 22.5512, 88.3585, 0),
                ("CAM-05", "Park St - Wood St Midway Corridor", "midway", 22.5505, 88.3605, 0),
                ("CAM-06", "Park St & Loudon/Rawdon St (Junction)", "junction", 22.5496, 88.3628, 0),
                ("CAM-07", "Park St - Mullick Bazar Midway", "midway", 22.5488, 88.3650, 0),
                ("CAM-08", "Mullick Bazar & AJC Bose Rd (Junction)", "junction", 22.5478, 88.3672, 0),
                ("CAM-09", "Muzaffar Ahmed St & Rafi Ahmed Kidwai (Junction)", "junction", 22.5580, 88.3585, 0),
                ("CAM-10", "Eliot Road - Royd St Midway Corridor", "midway", 22.5552, 88.3615, 0),
                ("CAM-11", "Eliot Road & Acharya JC Bose Rd (Junction)", "junction", 22.5528, 88.3678, 0),
                ("CAM-12", "SH1 / Bijli Road & Flyover Entry (Junction)", "junction", 22.5448, 88.3668, 0),
                ("CAM-13", "Park Lane & McLeod St Midway Corridor", "midway", 22.5532, 88.3572, 0),
            ]
            cur.executemany(
                "INSERT INTO cameras (camera_id, name, kind, latitude, longitude, is_active) VALUES (?,?,?,?,?,?)",
                initial_cams
            )
        con.commit()
        con.close()

    # ------------------------------------------------------------------ #

    def _writer(self) -> None:
        con = self._connect()
        pending: List[tuple] = []
        last_flush = time.time()
        while not self._stop.is_set() or not self._q.empty():
            try:
                pending.append(self._q.get(timeout=0.2))
            except queue.Empty:
                pass
            if pending and (len(pending) >= 16 or time.time() - last_flush > 0.5):
                for sql, params in pending:
                    try:
                        con.execute(sql, params)
                    except Exception as exc:
                        print(f"[db] write failed: {exc}")
                con.commit()
                pending.clear()
                last_flush = time.time()
        con.commit()
        con.close()

    def _submit(self, sql: str, params: tuple) -> None:
        if not self._async_writes:
            con = self._connect()
            try:
                con.execute(sql, params)
                con.commit()
            finally:
                con.close()
            return
        try:
            self._q.put_nowait((sql, params))
        except queue.Full:
            pass  # analytics rows are droppable; never stall the pipeline

    # ------------------------------------------------------------------ #

    def log_violation(self, *, camera_id, track_id, vtype, severity,
                      confidence, fine, plate, plate_conf, status,
                      measured_value, reasons, evidence_path, clip_path,
                      lat, lon) -> None:
        self._submit(
            """INSERT INTO violations
               (ts, camera_id, track_id, violation_type, severity, confidence,
                fine_amount, plate_number, plate_conf, status, measured_value,
                reasons, evidence_path, clip_path, latitude, longitude)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (time.time(), camera_id, track_id, vtype, severity, confidence,
             fine, plate, plate_conf, status, measured_value,
             " | ".join(reasons or []), evidence_path, clip_path, lat, lon))

    def log_sighting(self, plate, camera_id, lat, lon, is_violation, speed_kmh=None, min_interval_s=45.0) -> None:
        if not plate:
            return
        p_norm = normalise_plate(plate)
        if not p_norm:
            return
        now = time.time()
        key = f"{p_norm}:{camera_id}"
        last_sighting = self._recent_sightings_cache.get(key, 0.0)
        if (now - last_sighting) < min_interval_s:
            return  # Prevent duplicate sighting logs for the same vehicle passage
        self._recent_sightings_cache[key] = now

        self._submit(
            """INSERT INTO sightings
               (ts, plate_number, plate_norm, camera_id, latitude, longitude,
                is_violation, speed_kmh) VALUES (?,?,?,?,?,?,?,?)""",
            (now, plate, p_norm, camera_id, lat, lon,
             int(bool(is_violation)), speed_kmh))

    def log_flow(self, camera_id, vehicles, mean_speed, queue_len) -> None:
        self._submit(
            "INSERT INTO flow_stats VALUES (?,?,?,?,?)",
            (time.time(), camera_id, vehicles, mean_speed, queue_len))

    def update_violation_plate(self, track_id: int, plate: str, plate_conf: float) -> None:
        """Retroactively updates plate number on previously logged violations for this track."""
        if not plate:
            return
        self._submit(
            """UPDATE violations
               SET plate_number = ?, plate_conf = ?
               WHERE track_id = ? AND (plate_number IS NULL OR plate_number = '' OR plate_conf < ?)""",
            (plate, plate_conf, track_id, plate_conf))

    # ------------------------------------------------------------------ #
    # Reads (synchronous - dashboard side)
    # ------------------------------------------------------------------ #

    def query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        con = self._connect()
        try:
            return con.execute(sql, params).fetchall()
        finally:
            con.close()

    def recent(self, limit: int = 200, status: Optional[str] = None):
        if status:
            return self.query(
                "SELECT * FROM violations WHERE status=? "
                "ORDER BY ts DESC LIMIT ?", (status, limit))
        return self.query(
            "SELECT * FROM violations ORDER BY ts DESC LIMIT ?", (limit,))

    def fetch_all(self, limit: int = 100):
        """API compatibility wrapper."""
        return self.recent(limit=limit)

    def vehicle_route(self, plate: str):
        return self.query(
            "SELECT * FROM sightings WHERE plate_norm=? ORDER BY ts",
            (normalise_plate(plate),))

    def set_status(self, violation_id: int, status: str) -> None:
        con = self._connect()
        con.execute("UPDATE violations SET status=? WHERE violation_id=?",
                    (status, violation_id))
        con.commit()
        con.close()

    def stats(self):
        return {
            "total": self.query("SELECT COUNT(*) c FROM violations")[0]["c"],
            "issued": self.query(
                "SELECT COUNT(*) c FROM violations WHERE status='issued'"
            )[0]["c"],
            "review": self.query(
                "SELECT COUNT(*) c FROM violations WHERE status='review'"
            )[0]["c"],
            "fines": self.query(
                "SELECT COALESCE(SUM(fine_amount),0) s FROM violations "
                "WHERE status='issued'")[0]["s"],
        }

    # ------------------------------------------------------------------ #
    # Blacklist
    # ------------------------------------------------------------------ #

    def add_blacklist(self, plate: str, reason: str = "",
                     severity: str = "high") -> bool:
        """Add a plate to the blacklist. Returns True if added."""
        norm = normalise_plate(plate)
        if not norm:
            return False
        con = self._connect()
        try:
            con.execute(
                "INSERT OR IGNORE INTO blacklist "
                "(plate_norm, plate_display, reason, severity, added_ts) "
                "VALUES (?,?,?,?,?)",
                (norm, plate.upper().strip(), reason, severity, time.time()))
            con.commit()
            return True
        except Exception:
            return False
        finally:
            con.close()

    def remove_blacklist(self, plate: str) -> bool:
        norm = normalise_plate(plate)
        con = self._connect()
        con.execute("DELETE FROM blacklist WHERE plate_norm=?", (norm,))
        con.commit()
        con.close()
        return True

    def get_blacklist(self) -> List[dict]:
        rows = self.query(
            "SELECT * FROM blacklist WHERE active=1 ORDER BY added_ts DESC")
        return [dict(r) for r in rows]

    def check_blacklist(self, plate: str) -> Optional[dict]:
        """Returns blacklist entry if plate is blacklisted, else None."""
        norm = normalise_plate(plate)
        if not norm:
            return None
        rows = self.query(
            "SELECT * FROM blacklist WHERE plate_norm=? AND active=1",
            (norm,))
        return dict(rows[0]) if rows else None

    # ------------------------------------------------------------------ #
    # OCR Accuracy
    # ------------------------------------------------------------------ #

    def log_ocr_attempt(self, track_id: int, raw_text: str,
                        final_text: str, confidence: float,
                        regex_valid: bool, pass_index: int) -> None:
        self._submit(
            "INSERT INTO ocr_accuracy_log "
            "(ts, track_id, raw_text, final_text, confidence, regex_valid, pass_index) "
            "VALUES (?,?,?,?,?,?,?)",
            (time.time(), track_id, raw_text, final_text, confidence,
             int(regex_valid), pass_index))

    def ocr_accuracy_stats(self) -> dict:
        """Returns OCR accuracy metrics."""
        total = self.query(
            "SELECT COUNT(*) c FROM ocr_accuracy_log")[0]["c"]
        valid = self.query(
            "SELECT COUNT(*) c FROM ocr_accuracy_log WHERE regex_valid=1"
        )[0]["c"] if total else 0
        avg_conf = self.query(
            "SELECT COALESCE(AVG(confidence),0) a FROM ocr_accuracy_log"
        )[0]["a"] if total else 0.0
        by_pass = []
        if total:
            by_pass = [dict(r) for r in self.query(
                "SELECT pass_index, COUNT(*) c, AVG(confidence) avg_conf "
                "FROM ocr_accuracy_log WHERE regex_valid=1 "
                "GROUP BY pass_index ORDER BY pass_index")]
        return {
            "total_attempts": total,
            "valid_reads": valid,
            "accuracy_pct": round((valid / total * 100), 1) if total else 0.0,
            "avg_confidence": round(avg_conf, 3),
            "by_pass": by_pass,
        }

    # ------------------------------------------------------------------ #
    # Flow / Heatmap / Congestion Analytics
    # ------------------------------------------------------------------ #

    def flow_heatmap_data(self) -> List[dict]:
        """Returns aggregated vehicle density per camera for heatmap."""
        rows = self.query(
            "SELECT camera_id, "
            "       COUNT(*) total_readings, "
            "       SUM(vehicles) total_vehicles, "
            "       AVG(mean_speed) avg_speed "
            "FROM flow_stats "
            "GROUP BY camera_id")
        return [dict(r) for r in rows]

    def flow_timeseries(self, camera_id: str = None, hours: int = 24) -> List[dict]:
        """Returns hourly vehicle counts for a time-series chart."""
        cutoff = time.time() - (hours * 3600)
        if camera_id:
            rows = self.query(
                "SELECT CAST((ts - ?) / 3600 AS INTEGER) AS hour_bucket, "
                "       SUM(vehicles) total, AVG(mean_speed) avg_speed "
                "FROM flow_stats WHERE ts > ? AND camera_id = ? "
                "GROUP BY hour_bucket ORDER BY hour_bucket",
                (cutoff, cutoff, camera_id))
        else:
            rows = self.query(
                "SELECT CAST((ts - ?) / 3600 AS INTEGER) AS hour_bucket, "
                "       SUM(vehicles) total, AVG(mean_speed) avg_speed "
                "FROM flow_stats WHERE ts > ? "
                "GROUP BY hour_bucket ORDER BY hour_bucket",
                (cutoff, cutoff))
        return [dict(r) for r in rows]

    def congestion_zones(self, speed_threshold: float = 15.0) -> List[dict]:
        """Returns cameras where average speed is below threshold (congested)."""
        rows = self.query(
            "SELECT camera_id, AVG(mean_speed) avg_speed, SUM(vehicles) total_vehicles "
            "FROM flow_stats WHERE ts > ? "
            "GROUP BY camera_id HAVING AVG(mean_speed) < ? "
            "ORDER BY avg_speed ASC",
            (time.time() - 3600, speed_threshold))
        return [dict(r) for r in rows]

    def origin_destination_matrix(self, date_str: str = None) -> List[dict]:
        """Build O-D matrix: first and last camera sighting per vehicle per day."""
        if date_str:
            # Parse date string to timestamp range
            import datetime
            dt = datetime.datetime.strptime(date_str, "%Y-%m-%d")
            day_start = dt.timestamp()
            day_end = day_start + 86400
        else:
            day_end = time.time()
            day_start = day_end - 86400

        rows = self.query(
            "SELECT plate_norm, "
            "  (SELECT camera_id FROM sightings s2 WHERE s2.plate_norm = s.plate_norm "
            "   AND s2.ts BETWEEN ? AND ? ORDER BY s2.ts ASC LIMIT 1) AS origin, "
            "  (SELECT camera_id FROM sightings s3 WHERE s3.plate_norm = s.plate_norm "
            "   AND s3.ts BETWEEN ? AND ? ORDER BY s3.ts DESC LIMIT 1) AS destination "
            "FROM sightings s WHERE s.ts BETWEEN ? AND ? "
            "GROUP BY plate_norm HAVING COUNT(*) >= 2",
            (day_start, day_end, day_start, day_end, day_start, day_end))

        # Aggregate into matrix
        matrix = {}
        for r in rows:
            key = (r["origin"], r["destination"])
            if key[0] != key[1]:  # only count actual journeys
                matrix[key] = matrix.get(key, 0) + 1

        return [{"origin": k[0], "destination": k[1], "count": v}
                for k, v in matrix.items()]

    # ------------------------------------------------------------------ #
    # Cameras Management (Junction & Midway Nodes)
    # ------------------------------------------------------------------ #

    def add_camera(self, camera_id: str, name: str, kind: str,
                   latitude: float, longitude: float, is_active: int = 0) -> bool:
        con = self._connect()
        try:
            con.execute(
                "INSERT OR REPLACE INTO cameras (camera_id, name, kind, latitude, longitude, is_active) "
                "VALUES (?,?,?,?,?,?)",
                (camera_id, name, kind, latitude, longitude, is_active)
            )
            con.commit()
            return True
        except Exception:
            return False
        finally:
            con.close()

    def delete_camera(self, camera_id: str) -> bool:
        con = self._connect()
        con.execute("DELETE FROM cameras WHERE camera_id=?", (camera_id,))
        con.commit()
        con.close()
        return True

    def get_all_cameras(self) -> List[dict]:
        rows = self.query("SELECT * FROM cameras ORDER BY camera_id")
        return [dict(r) for r in rows]

    def clear_all(self, clear_evidence: bool = True) -> None:
        """Delete all violation logs, sightings, and flow statistics."""
        con = self._connect()
        con.execute("DELETE FROM violations")
        con.execute("DELETE FROM sightings")
        con.execute("DELETE FROM flow_stats")
        con.commit()
        con.close()

        if clear_evidence:
            for folder in ("evidence/crops", "evidence/clips"):
                p = Path(folder)
                if p.exists():
                    for f in p.glob("*.*"):
                        try:
                            f.unlink()
                        except Exception:
                            pass

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

