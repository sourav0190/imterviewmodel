import unittest
import base64
import numpy as np
import cv2
from starlette.testclient import TestClient

from main import app

class TestExistingProctoringCompatibility(unittest.TestCase):
    """
    Verifies non-negotiable requirement:
    Existing proctoring behavior, routes, response schemas, and logic remain 100% intact.
    """

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        
        # Create a valid synthetic black frame encoded in base64
        dummy_img = np.zeros((480, 640, 3), dtype=np.uint8)
        _, buffer = cv2.imencode('.jpg', dummy_img)
        cls.valid_base64 = "data:image/jpeg;base64," + base64.b64encode(buffer).decode('utf-8')

    def test_root_endpoint_compatibility(self):
        """Verify root endpoint returns original fields and 200 OK."""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("message", data)
        self.assertIn("test_ui", data)
        self.assertEqual(data["test_ui"], "/test")

    def test_test_ui_endpoint(self):
        """Verify /test endpoint returns test_frontend.html."""
        res = self.client.get("/test")
        self.assertEqual(res.status_code, 200)
        self.assertIn("AI Proctoring", res.text)

    def test_proctoring_analyze_endpoint_contract(self):
        """Verify /api/v1/analyze accepts base64 image and returns exact existing schema."""
        payload = {"image": self.valid_base64}
        res = self.client.post("/api/v1/analyze", json=payload)
        self.assertEqual(res.status_code, 200)
        
        data = res.json()
        # Verify all existing schema keys
        expected_keys = [
            "suspicion_score",
            "face_present",
            "multiple_people",
            "person_count",
            "looking_away",
            "gaze_direction",
            "pitch_score",
            "is_talking",
            "phone_detected",
            "book_detected",
            "hands_count",
            "malpractices"
        ]
        for key in expected_keys:
            self.assertIn(key, data, f"Missing expected key '{key}' in proctoring response")

        self.assertIsInstance(data["suspicion_score"], (int, float))
        self.assertIsInstance(data["face_present"], bool)
        self.assertIsInstance(data["malpractices"], list)

    def test_proctoring_invalid_image_handling(self):
        """Verify 400 response when sending invalid base64."""
        payload = {"image": "invalid_base64_string"}
        res = self.client.post("/api/v1/analyze", json=payload)
        self.assertEqual(res.status_code, 400)


if __name__ == "__main__":
    unittest.main()
