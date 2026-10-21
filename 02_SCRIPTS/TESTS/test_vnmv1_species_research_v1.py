import io
import json
import sys
import tempfile
import unittest
from contextlib import chdir, redirect_stderr
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "TOOLS"))
import vnmv1_species_research_v1 as research


class SpeciesResearchTests(unittest.TestCase):
    def test_failure_log_reports_stage_and_status_without_exception_details(self):
        class FakeResponse:
            status = 403

        class FakeDriveError(Exception):
            resp = FakeResponse()

        stderr = io.StringIO()
        with patch.object(research, "_drive_service",
                          side_effect=FakeDriveError("private file id and response body")), \
             redirect_stderr(stderr):
            result = research.main()

        self.assertEqual(result, 2)
        self.assertIn("stage=drive_authentication; HTTP_403", stderr.getvalue())
        self.assertNotIn("private file id", stderr.getvalue())
        self.assertNotIn("response body", stderr.getvalue())

    def test_gbif_match_preserves_authority_warning(self):
        with patch.object(research, "fetch_json", return_value={
            "scientificName": "Testa specimen", "canonicalName": "Testa specimen",
            "rank": "SPECIES", "status": "ACCEPTED", "confidence": 98,
            "usageKey": 123, "matchType": "EXACT",
        }):
            result = research.gbif_match("Testa specimen")
        self.assertEqual(result["canonical_name"], "Testa specimen")
        self.assertIn("verify", result["authority_note"])

    def test_inat_photo_candidate_keeps_license_and_warning(self):
        with patch.object(research, "fetch_json", return_value={"results": [{
            "id": 55, "uri": "https://www.inaturalist.org/observations/55",
            "taxon": {"name": "Testa specimen"},
            "photos": [{"id": 88, "url": "https://example.org/photo.jpg",
                        "license_code": "cc-by", "attribution": "A Photographer"}],
        }]}):
            result = research.inat_photo_candidates(55)
        self.assertEqual(result[0]["license"], "cc-by")
        self.assertIn("inspect", result[0]["source_warning"])

    def test_rejects_nonpermissive_photo_license(self):
        with patch.object(research, "fetch_json", return_value={"results": [
            {"photos": [{"license_code": "all-rights-reserved"}]}
        ]}):
            self.assertEqual(research.inat_photo_candidates(55), [])

    def test_request_id_is_filename_safe(self):
        self.assertEqual(research._safe_id("card-0001-ind-1"), "card-0001-ind-1")
        with self.assertRaises(ValueError):
            research._safe_id("../../private")

    def test_packet_writer_persists_request_in_public_repo_output(self):
        packet = {"request_id": "card-0001-pilot", "scientific_name_requested": "Testa specimen"}
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            path = research._write_packet(packet, "abc123")
            self.assertEqual(path, "research-output/card-0001-pilot.json")
            with open(path, encoding="utf-8") as source:
                saved = json.load(source)
        self.assertEqual(saved["request_id"], "card-0001-pilot")
        self.assertEqual(saved["queue_fingerprint"], "abc123")

    def test_packet_does_not_claim_analysis_or_imagegen(self):
        with patch.object(research, "gbif_match", return_value={"canonical_name": "Testa specimen"}), \
             patch.object(research, "inat_taxa", return_value=[
                 {"taxon_id": 55, "name": "Testa specimen", "is_exact_name": True}
             ]), \
             patch.object(research, "inat_photo_candidates", return_value=[]), \
             patch.object(research, "commons_candidates", return_value=[]):
            packet = research.build_packet("Testa specimen", "pilot-01")
        self.assertEqual(packet["image_analysis_status"], "NOT_ANALYSED_BY_VISION_MODEL")
        self.assertIn("CANNOT_BE_INVOKED", packet["generation_handoff"]["automatic_image_generation"])
        self.assertEqual(packet["reference_photos"]["photo_count"], 0)
        self.assertEqual(packet["pose_plan"]["target_image_count"], 12)
        self.assertEqual(packet["pose_plan"]["views_per_look"], 6)
        self.assertEqual(len(packet["pose_plan"]["assignments"]), 12)
        self.assertEqual(len(packet["specimen_appearance_pair"]["appearance_groups"]), 2)
        groups = packet["specimen_appearance_pair"]["appearance_groups"]
        self.assertEqual([group["look_id"] for group in groups], ["YOUNGER_FEMALE", "OLDER_FEMALE"])
        self.assertTrue(all(group["sex_for_study"] == "FEMALE_ASSUMED_BY_USER" for group in groups))
        self.assertEqual(len(packet["closeup_plan"]["assignments"]), 6)
        self.assertFalse(packet["source_specimen"]["original_image_embedded_in_public_packet"])


    def test_image_bundle_target_is_fourteen(self):
        self.assertEqual(research.MIN_PACKET_IMAGES, 14)

    def test_image_extension_checks_file_signature(self):
        self.assertEqual(research._image_extension("image/png", bytes.fromhex("89504e470d0a1a0a") + b"data"), ".png")
        self.assertEqual(research._image_extension("image/jpeg", bytes.fromhex("ffd8ff") + b"data"), ".jpg")
        self.assertIsNone(research._image_extension("image/png", b"not an image"))

    def test_external_image_download_rejects_untrusted_host(self):
        result = research._download_external_image({"image_url": "https://example.com/fake.png"})
        self.assertEqual(result, (None, None))


if __name__ == "__main__":
    unittest.main()
