"""
Tests for server tracking API endpoints using FastAPI TestClient.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from fastapi.testclient import TestClient
from server import app, tracking_engine

class TestServerTrackingAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        tracking_engine.active_tracks.clear()
        tracking_engine.plate_to_instances.clear()

    def test_get_tracking_graph(self):
        res = self.client.get("/api/tracking/graph")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("nodes", data)
        self.assertIn("edges", data)
        self.assertGreaterEqual(len(data["nodes"]), 10)
        self.assertGreaterEqual(len(data["edges"]), 9)

    def test_simulate_sighting_and_fork(self):
        # Simulate sighting at fork junction CAM-03
        res = self.client.post("/api/tracking/simulate-sighting", json={
            "plate": "WB02TX9999",
            "camera_id": "CAM-03",
            "speed_kmh": 42.0
        })
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(len(data["active_instances"]), 2)

        # Verify live tracking endpoint
        live_res = self.client.get("/api/tracking/live")
        self.assertEqual(live_res.status_code, 200)
        live_data = live_res.json()
        self.assertEqual(live_data["count"], 2)

        # Confirm downstream sighting at CAM-08 with 1-char typo
        res_conf = self.client.post("/api/tracking/simulate-sighting", json={
            "plate": "WB02TX9998",  # 1-char OCR substitution
            "camera_id": "CAM-08",
            "speed_kmh": 45.0
        })
        self.assertEqual(res_conf.status_code, 200)

        # Check live tracking state: one confirmed, sibling vanished
        live_res2 = self.client.get("/api/tracking/live")
        vehicles = live_res2.json()["vehicles"]
        confirmed = [v for v in vehicles if v["status"] == "confirmed"]
        vanished = [v for v in vehicles if v["status"] == "vanished"]
        self.assertGreaterEqual(len(confirmed), 1)
        self.assertGreaterEqual(len(vanished), 1)

    def test_reset_tracking(self):
        self.client.post("/api/tracking/simulate-sighting", json={
            "plate": "WB02RST001",
            "camera_id": "CAM-06",
            "speed_kmh": 40.0
        })
        res = self.client.post("/api/tracking/reset")
        self.assertEqual(res.status_code, 200)
        live_res = self.client.get("/api/tracking/live")
        self.assertEqual(live_res.json()["count"], 0)

if __name__ == "__main__":
    unittest.main()
