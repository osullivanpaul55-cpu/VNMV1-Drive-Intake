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

    def test_public_artifact_omits_queue_request_identifier(self):
        packet = {"request_id": "card-0001-private", "scientific_name_requested": "Testa specimen"}
        with tempfile.TemporaryDirectory() as temp_dir, chdir(temp_dir):
            name = research._write_packet(packet, "abc123")
            self.assertEqual(name, "species-research-abc123")
            with open("research-output/species-research-abc123.json", encoding="utf-8") as source:
                saved = json.load(source)
        self.assertNotIn("request_id", saved)
        self.assertEqual(saved["scientific_name_requested"], "Testa specimen")

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


if __name__ == "__main__":
    unittest.main()
