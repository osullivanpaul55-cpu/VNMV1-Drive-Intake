import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TOOLS"))

from vnmv1_drive_candidate_intake_v1 import allowed_candidate, sha256_bytes


class DriveCandidateIntakeTests(unittest.TestCase):
    def test_accepts_named_candidate_image(self):
        self.assertTrue(allowed_candidate("CARD-0001__IND-1__SIDE__v01.png", "image/png"))
        self.assertTrue(allowed_candidate("CARD-0001__IND-2__WALKING_AWAY__v12.webp", "image/webp"))

    def test_accepts_matching_json_sidecar_only(self):
        self.assertTrue(allowed_candidate("CARD-0001__IND-1__SIDE__v01.json", "application/json"))
        self.assertFalse(allowed_candidate("CARD-0002__IND-1__SIDE__v01.json", "application/json"))
        self.assertFalse(allowed_candidate("CARD-0001__IND-1__SIDE__v01.json", "image/png"))

    def test_rejects_unnamed_or_unsupported_candidates(self):
        self.assertFalse(allowed_candidate("candidate.png", "image/png"))
        self.assertFalse(allowed_candidate("CARD-0001__IND-1__SIDE__v01.gif", "image/gif"))
        self.assertFalse(allowed_candidate("CARD-0001__IND-3__SIDE__v01.png", "image/png"))

    def test_sha256_is_deterministic(self):
        digest = sha256_bytes(b"candidate")
        self.assertEqual(digest, sha256_bytes(b"candidate"))
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()
