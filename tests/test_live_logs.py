import unittest
from fastapi.testclient import TestClient

import server
from core.tracks import Track


class TestLiveLogsAPI(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)
        server.engine.reset()

    def tearDown(self):
        server.engine.reset()

    def test_live_logs_empty(self):
        res = self.client.get("/api/live-logs")
        self.assertEqual(res.status_code, 200)
        self.assertIsInstance(res.json(), list)

    def test_live_logs_with_active_track(self):
        # Register a live vehicle track in engine
        tr = Track(
            track_id=88,
            label="car",
            vehicle_type="car",
            first_frame=1,
            last_frame=10,
            bbox=(100, 100, 200, 200),
            conf=0.91,
        )
        tr.speed_kmh = 42.5
        server.engine.registry.tracks[88] = tr

        res = self.client.get("/api/live-logs")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(len(data) >= 1)
        found = [r for r in data if r["track_id"] == 88]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["type"], "CAR")
        self.assertEqual(found[0]["plate"], "SCANNING...")
        self.assertEqual(found[0]["status"], "tracking")

        # Now simulate OCR recognizing the plate
        tr.plate = "MH12DE1433"
        res2 = self.client.get("/api/live-logs")
        data2 = res2.json()
        found2 = [r for r in data2 if r["track_id"] == 88]
        self.assertEqual(len(found2), 1)
        self.assertEqual(found2[0]["plate"], "MH12DE1433")
        self.assertEqual(found2[0]["status"], "verified")

    def test_live_logs_with_violation_and_anpr(self):
        server.engine.live_violations.appendleft({
            "type": "SPEEDING",
            "track_id": 99,
            "confidence": 0.96,
            "fine": 2000,
            "severity": "HIGH",
            "plate": "DL01AB9999",
            "status": "issued",
            "reasons": ["Speed 82.0 km/h in 50.0 km/h zone"],
        })
        server.engine.live_violations.appendleft({
            "type": "ANPR_DETECT",
            "track_id": 100,
            "confidence": 0.94,
            "fine": 0,
            "severity": "INFO",
            "plate": "KA04MH1234",
            "status": "detected",
            "reasons": ["Plate KA04MH1234 verified"],
        })

        res = self.client.get("/api/live-logs")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["type"], "ANPR_DETECT")
        self.assertEqual(data[0]["status"], "detected")
        self.assertEqual(data[1]["type"], "SPEEDING")
        self.assertEqual(data[1]["fine"], "Rs 2000")
        self.assertEqual(data[1]["status"], "issued")

    def test_events_endpoint(self):
        # Insert a live violation
        server.engine.live_violations.appendleft({
            "type": "RED_LIGHT",
            "track_id": 55,
            "confidence": 0.98,
            "fine": 1000,
            "severity": "HIGH",
            "plate": "DL09CD1122",
            "status": "issued",
            "crop_path": "evidence/crops/crop_55.jpg",
            "plate_img": "evidence/plates/plate_55.jpg",
        })

        res = self.client.get("/api/events")
        self.assertEqual(res.status_code, 200)
        events = res.json()
        self.assertIsInstance(events, list)
        self.assertTrue(len(events) >= 1)

        # Check the live violation is present
        found = [e for e in events if e["plate"] == "DL09CD1122"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["violation"], "RED_LIGHT")
        self.assertEqual(found[0]["fine"], 1000)
        self.assertEqual(found[0]["type"], "violation")
        self.assertEqual(found[0]["plateImg"], "/evidence/plates/plate_55.jpg")


if __name__ == "__main__":
    unittest.main()

