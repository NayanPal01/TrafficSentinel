"""
Unit tests for MultiCameraTracker, PolylineInterpolator, and Levenshtein matcher.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.road_network import RoadNetwork
from core.tracking_engine import (
    MultiCameraTracker,
    PolylineInterpolator,
    compute_bearing,
    levenshtein_distance,
)


class TestTrackingEngine(unittest.TestCase):
    def setUp(self):
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "road_network.json")
        self.rn = RoadNetwork(json_path)
        self.events = []
        self.tracker = MultiCameraTracker(self.rn, on_event_callback=lambda ev: self.events.append(ev))

    def test_levenshtein(self):
        self.assertEqual(levenshtein_distance("WB02AB1234", "WB02AB1234"), 0)
        self.assertEqual(levenshtein_distance("WB02AB1234", "WB02AB1238"), 1)
        self.assertEqual(levenshtein_distance("WB02AB1234", "WB02AB1288"), 2)
        self.assertGreater(levenshtein_distance("WB02AB1234", "DL01XY9999"), 4)

    def test_polyline_interpolator(self):
        edge = self.rn.get_edge("CAM-06", "CAM-11")
        self.assertIsNotNone(edge)

        # Start of edge
        lat0, lon0, bearing0, pct0 = PolylineInterpolator.interpolate(edge, 0.0)
        self.assertAlmostEqual(lat0, edge.polyline[0][0], places=4)
        self.assertAlmostEqual(lon0, edge.polyline[0][1], places=4)
        self.assertEqual(pct0, 0.0)

        # Midpoint of edge
        half_dist = edge.distance_m * 0.5
        lat_m, lon_m, bearing_m, pct_m = PolylineInterpolator.interpolate(edge, half_dist)
        self.assertGreater(pct_m, 45.0)
        self.assertLess(pct_m, 55.0)

        # End of edge
        lat_e, lon_e, bearing_e, pct_e = PolylineInterpolator.interpolate(edge, edge.distance_m + 10.0)
        self.assertAlmostEqual(lat_e, edge.polyline[-1][0], places=4)
        self.assertAlmostEqual(lon_e, edge.polyline[-1][1], places=4)
        self.assertEqual(pct_e, 100.0)

    def test_single_edge_sighting(self):
        # CAM-06 has single outgoing edge to CAM-11
        ids = self.tracker.register_sighting("WB02AB1234", "CAM-06", speed_kmh=40.0, ts=1000.0)
        self.assertEqual(len(ids), 1)
        tr = self.tracker.active_tracks[ids[0]]
        self.assertEqual(tr.status, "confirmed")
        self.assertEqual(tr.confidence, 1.0)
        self.assertEqual(tr.to_node, "CAM-11")

    def test_fork_branch_spawning(self):
        # CAM-03 is a fork junction (forks to CAM-09 and CAM-08)
        ids = self.tracker.register_sighting("WB02CD5678", "CAM-03", speed_kmh=40.0, ts=1000.0)
        self.assertEqual(len(ids), 2)

        tracks = [self.tracker.active_tracks[i] for i in ids]
        destinations = {t.to_node for t in tracks}
        self.assertEqual(destinations, {"CAM-09", "CAM-08"})

        for t in tracks:
            self.assertEqual(t.status, "predicted")
            self.assertEqual(t.confidence, 0.5)
            self.assertEqual(len(t.sibling_ids), 2)
            self.assertIn(ids[0], t.sibling_ids)
            self.assertIn(ids[1], t.sibling_ids)

    def test_downstream_confirmation_and_sibling_pruning(self):
        # Sighting at fork CAM-03
        t0 = 1000.0
        ids = self.tracker.register_sighting("WB02EF9012", "CAM-03", speed_kmh=36.0, ts=t0)
        self.assertEqual(len(ids), 2)

        # Simulate time tick halfway along branches
        self.tracker.tick(current_time=t0 + 5.0)

        # Vehicle is detected at downstream camera CAM-08
        conf_ids = self.tracker.register_sighting("WB02EF9012", "CAM-08", speed_kmh=38.0, ts=t0 + 15.0)

        # One track should be confirmed for CAM-08
        # Sibling branch to CAM-09 should be marked 'vanished'
        branch_cam08 = [t for t in self.tracker.active_tracks.values() if t.from_node == "CAM-08" or t.to_node == "CAM-07"]
        self.assertTrue(len(branch_cam08) > 0)

        vanished = [t for t in self.tracker.active_tracks.values() if t.status == "vanished"]
        self.assertEqual(len(vanished), 1)
        self.assertEqual(vanished[0].to_node, "CAM-09")

    def test_fuzzy_plate_matching(self):
        # Vehicle registered as WB02KL3456 at CAM-06
        t0 = 1000.0
        self.tracker.register_sighting("WB02KL3456", "CAM-06", speed_kmh=40.0, ts=t0)

        # Downstream camera CAM-11 detects with 1-character OCR typo: WB02KL3458
        ids = self.tracker.register_sighting("WB02KL3458", "CAM-11", speed_kmh=42.0, ts=t0 + 30.0)
        self.assertTrue(len(ids) > 0)
        tr = self.tracker.active_tracks[ids[0]]
        self.assertEqual(tr.status, "confirmed")
        # Should be confirmed with updated plate
        self.assertEqual(tr.plate, "WB02KL3458")

    def test_lost_track_timeout(self):
        # Sighting at CAM-06
        t0 = 1000.0
        ids = self.tracker.register_sighting("WB02ZZ9999", "CAM-06", speed_kmh=40.0, ts=t0)
        inst_id = ids[0]

        # Fast forward time beyond grace window (expected transit is ~60s, test at 250s)
        self.tracker.tick(current_time=t0 + 250.0)

        tr = self.tracker.active_tracks[inst_id]
        self.assertEqual(tr.status, "lost")

        # After another 5 seconds, should be fully purged from active tracks
        self.tracker.tick(current_time=t0 + 256.0)
        self.assertNotIn(inst_id, self.tracker.active_tracks)


if __name__ == "__main__":
    unittest.main()
