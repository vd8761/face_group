import unittest
from dataclasses import dataclass

from app.services.selfie_quality import SelfieQualityError, select_selfie_face


@dataclass
class Face:
    bbox: list[int]
    quality_score: float
    is_low_quality: bool = False


class SelfieQualityTests(unittest.TestCase):
    def test_ignores_tiny_background_face(self):
        primary = Face([0, 0, 200, 200], 0.9)
        background = Face([220, 0, 250, 30], 0.8)
        self.assertIs(select_selfie_face([background, primary]), primary)

    def test_rejects_two_prominent_faces(self):
        with self.assertRaises(SelfieQualityError):
            select_selfie_face([
                Face([0, 0, 200, 200], 0.9),
                Face([210, 0, 400, 190], 0.85),
            ])

    def test_rejects_only_low_quality_faces(self):
        with self.assertRaises(SelfieQualityError):
            select_selfie_face([Face([0, 0, 200, 200], 0.3, True)])


if __name__ == "__main__":
    unittest.main()
