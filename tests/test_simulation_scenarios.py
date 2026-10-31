"""
End-to-End multi-camera simulation scenario verification.
Tests 3 concurrent vehicles, fork branch spawning, downstream confirmation,
fuzzy Levenshtein OCR matching, and timeout cleanup.
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.road_network import RoadNetwork
from core.tracking_engine import MultiCameraTracker

class TestSimulationScenarios(unittest.TestCase):
    def setUp(self):
        json_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "road_network.json")
        self.rn = RoadNetwork(json_path)
        self.events = []
        self.tracker = MultiCameraTracker(self.rn, on_event_callback=lambda ev: self.events.append(ev))

    def test_fork_and_fuzzy_confirmation_scenario(self):
        t0 = 1000.0

        # 1. Car 1 arrives at fork CAM-03
        ids1 = self.tracker.register_sighting("WB02AA1111", "CAM-03", speed_kmh=40.0, ts=t0)
        self.assertEqual(len(ids1), 2, "CAM-03 fork must spawn 2 predicted branches")
        for bid in ids1:
            self.assertEqual(self.tracker.active_tracks[bid].status, "predicted")
            self.assertEqual(self.tracker.active_tracks[bid].confidence, 0.5)

        # 2. Advance simulation 5 seconds along branches
        ticks = self.tracker.tick(current_time=t0 + 5.0)
        self.assertEqual(len(ticks), 2)

        # 3. Downstream camera CAM-08 reports the vehicle with a 1-character OCR substitution:
        # Detected plate: "WB02AA1119" (typo on last digit, Levenshtein = 1)
        conf_ids = self.tracker.register_sighting("WB02AA1119", "CAM-08", speed_kmh=42.0, ts=t0 + 12.0)
        self.assertTrue(len(conf_ids) > 0, "Fuzzy match must succeed for Levenshtein = 1")

        # 4. Check that CAM-08 branch is confirmed and sibling CAM-09 branch is vanished
        cam08_active = [t for t in self.tracker.active_tracks.values() if t.to_node == "CAM-07" or t.from_node == "CAM-08"]
        self.assertTrue(len(cam08_active) > 0)
        self.assertEqual(cam08_active[0].status, "confirmed")

        vanished = [t for t in self.tracker.active_tracks.values() if t.status == "vanished"]
        self.assertEqual(len(vanished), 1)
        self.assertEqual(vanished[0].to_node, "CAM-09")

        # 5. After 3 seconds, vanished track must be fully purged
        self.tracker.tick(current_time=t0 + 16.0)
        self.assertNotIn(vanished[0].instance_id, self.tracker.active_tracks)

    def test_concurrent_vehicles(self):
        t0 = 2000.0

        # Car A enters at CAM-01
        ids_a = self.tracker.register_sighting("WB01CA0001", "CAM-01", speed_kmh=38.0, ts=t0)
        # Car B enters at CAM-06
        ids_b = self.tracker.register_sighting("WB02CB0002", "CAM-06", speed_kmh=45.0, ts=t0 + 2.0)
        # Car C enters at Fork CAM-03
        ids_c = self.tracker.register_sighting("WB03CC0003", "CAM-03", speed_kmh=40.0, ts=t0 + 4.0)

        self.assertEqual(len(ids_a), 1)
        self.assertEqual(len(ids_b), 1)
        self.assertEqual(len(ids_c), 2)  # 2 branches

        # Total 4 active tracks
        ticks = self.tracker.tick(current_time=t0 + 6.0)
        self.assertEqual(len(ticks), 4)

        # Confirm Car C along CAM-09 (Park Street East Branch)
        self.tracker.register_sighting("WB03CC0003", "CAM-09", speed_kmh=44.0, ts=t0 + 20.0)

        # Check Car C branch to CAM-08 is vanished
        vanished_c = [t for t in self.tracker.active_tracks.values() if t.plate == "WB03CC0003" and t.status == "vanished"]
        self.assertEqual(len(vanished_c), 1)
        self.assertEqual(vanished_c[0].to_node, "CAM-08")

        # Car A and Car B remain unaffected and active
        self.assertIn("WB01CA0001", self.tracker.plate_to_instances)
        self.assertIn("WB02CB0002", self.tracker.plate_to_instances)

if __name__ == "__main__":
    unittest.main()
