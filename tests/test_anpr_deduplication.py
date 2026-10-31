import unittest
import time
import tempfile
from pathlib import Path
import numpy as np

from core.database import Database
from core.ocr_worker import OCRResult, get_car


class TestANPRDeduplication(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.db = Database(str(self.db_path), async_writes=False)

    def tearDown(self):
        self.db.close()
        self.temp_dir.cleanup()

    def test_database_sighting_deduplication(self):
        # 1. First sighting log should be recorded
        self.db.log_sighting("WB02TX9999", "CAM-01", 22.5, 88.3, False, speed_kmh=45.0)
        sightings = self.db.query("SELECT * FROM sightings WHERE plate_norm='WB02TX9999'")
        self.assertEqual(len(sightings), 1)

        # 2. Duplicate log attempt within 45s should be ignored by the cache
        self.db.log_sighting("WB02TX9999", "CAM-01", 22.5, 88.3, False, speed_kmh=45.0)
        sightings = self.db.query("SELECT * FROM sightings WHERE plate_norm='WB02TX9999'")
        self.assertEqual(len(sightings), 1, "Duplicate sighting within cooldown must not be logged twice")

        # 3. Different plate should be logged
        self.db.log_sighting("DL01AB1234", "CAM-01", 22.5, 88.3, False, speed_kmh=40.0)
        sightings_diff = self.db.query("SELECT * FROM sightings WHERE plate_norm='DL01AB1234'")
        self.assertEqual(len(sightings_diff), 1)

    def test_get_car_proximity_fallback(self):
        # Vehicle bbox at [100, 100, 300, 300]
        vehicle_bboxes = [[100, 100, 300, 300, 1]]
        
        # Plate bbox slightly below bottom bumper [180, 310, 240, 330] (10px below car bbox)
        car = get_car([180, 310, 240, 330], vehicle_bboxes)
        self.assertEqual(car[4], 1, "Should associate nearby bumper plate with vehicle ID")

    def test_ocr_result_crop_field(self):
        dummy_crop = np.zeros((30, 80, 3), dtype=np.uint8)
        res = OCRResult(track_id=5, plate="MH12DE1433", confidence=0.92, crop=dummy_crop)
        self.assertEqual(res.plate, "MH12DE1433")
        self.assertIsNotNone(res.crop)
        self.assertEqual(res.crop.shape, (30, 80, 3))

    def test_hsrp_prefix_stripping(self):
        from core.ocr_worker import strip_hsrp_prefix, validate_indian_plate
        self.assertEqual(strip_hsrp_prefix("INDWB02AK1928"), "WB02AK1928")
        self.assertEqual(strip_hsrp_prefix("1NDDL3CAB1234"), "DL3CAB1234")
        ok, plate = validate_indian_plate("INDWB02AK1928")
        self.assertTrue(ok)
        self.assertEqual(plate, "WB02AK1928")

    def test_disambiguate_indian_plate_no_series_corruption(self):
        from core.ocr_worker import disambiguate_indian_plate
        # Verify series letters like A, C, B, S are NOT converted into numbers
        self.assertEqual(disambiguate_indian_plate("DL3CAB1234"), "DL3CAB1234")
        self.assertEqual(disambiguate_indian_plate("DL3AB1234"), "DL3AB1234")
        self.assertEqual(disambiguate_indian_plate("WB2AK1928"), "WB2AK1928")
        self.assertEqual(disambiguate_indian_plate("MH12AB1234"), "MH12AB1234")
        # Verify genuine OCR confusion fixes (O->0 in district, B->8 in serial)
        self.assertEqual(disambiguate_indian_plate("MHO2AB1234"), "MH02AB1234")
        self.assertEqual(disambiguate_indian_plate("WB02AK192B"), "WB02AK1928")

    def test_sort_plate_detections_line_binning(self):
        from core.ocr_worker import sort_plate_detections
        # Simulated two-line plate with slight vertical jitter on line 1:
        # Box 'WB' at y=14, x=10; Box '02' at y=11, x=50 (should stay 'WB', '02', not swap)
        d1 = [[[10, 14], [35, 14], [35, 30], [10, 30]], 'WB', 0.9]
        d2 = [[[50, 11], [75, 11], [75, 28], [50, 28]], '02', 0.9]
        # Line 2 at y=45
        d3 = [[[10, 45], [40, 45], [40, 65], [10, 65]], 'AK', 0.9]
        d4 = [[[48, 46], [90, 46], [90, 66], [48, 66]], '1928', 0.9]
        sorted_dets = sort_plate_detections([d2, d1, d4, d3])
        texts = [d[1] for d in sorted_dets]
        self.assertEqual(texts, ['WB', '02', 'AK', '1928'])

    def test_plate_detector_model_present(self):
        p = Path("models/license_plate_detector.pt")
        self.assertTrue(p.exists(), "models/license_plate_detector.pt should exist")
        self.assertGreater(p.stat().st_size, 1024 * 1024, "Model should be > 1MB")

    def test_order_quad_points(self):
        from core.ocr_worker import order_quad_points
        pts = np.array([[10, 20], [180, 5], [195, 65], [20, 80]], dtype=np.float32)
        ordered = order_quad_points(pts)
        self.assertEqual(ordered.shape, (4, 2))
        # Top-left is (10, 20), Top-right is (180, 5), Bottom-right is (195, 65), Bottom-left is (20, 80)
        np.testing.assert_array_almost_equal(ordered[0], [10, 20])
        np.testing.assert_array_almost_equal(ordered[1], [180, 5])
        np.testing.assert_array_almost_equal(ordered[2], [195, 65])
        np.testing.assert_array_almost_equal(ordered[3], [20, 80])

    def test_correct_plate_perspective_straight_noop(self):
        from core.ocr_worker import correct_plate_perspective
        straight = np.ones((50, 180, 3), dtype=np.uint8) * 255
        out = correct_plate_perspective(straight)
        self.assertEqual(out.shape, (50, 180, 3))

    def test_correct_plate_perspective_tilted_trapezoid(self):
        import cv2
        from core.ocr_worker import correct_plate_perspective
        img = np.ones((80, 240, 3), dtype=np.uint8) * 255
        cv2.rectangle(img, (5, 5), (235, 75), (0, 0, 0), 2)
        cv2.putText(img, 'MH12DE1433', (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2)
        src = np.float32([[0, 0], [240, 0], [240, 80], [0, 80]])
        dst = np.float32([[30, 25], [250, 10], [240, 95], [40, 105]])
        M = cv2.getPerspectiveTransform(src, dst)
        tilted = cv2.warpPerspective(img, M, (280, 120), borderValue=(80, 80, 80))

        warped = correct_plate_perspective(tilted)
        self.assertIsNotNone(warped)
        self.assertGreater(warped.shape[1], warped.shape[0])
        # Aspect ratio of unwarped plate should be rectangular (~2.0 - 3.5)
        aspect = warped.shape[1] / warped.shape[0]
        self.assertGreaterEqual(aspect, 1.8)
        self.assertLessEqual(aspect, 4.0)

    def test_correct_plate_perspective_empty_fallback(self):
        from core.ocr_worker import correct_plate_perspective
        self.assertIsNone(correct_plate_perspective(None))
        empty = np.array([])
        self.assertEqual(len(correct_plate_perspective(empty)), 0)


if __name__ == "__main__":
    unittest.main()
