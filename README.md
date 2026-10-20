# VNMV1 Drive Intake

A small public-code runner that checks a private Google Drive inbox. It contains no specimen images, private card inputs, or service-account key.

## What it does

- Checks the configured candidate-image Drive folder every five minutes.
- Accepts only the Card 0001 candidate image and JSON-sidecar naming pattern enforced by the intake script.
- Uses read-only Drive access for candidate intake and keeps temporary downloads on the runner.
- A separate research job checks a private Drive queue every 15 minutes or on manual dispatch. It queries GBIF, iNaturalist, and Wikimedia Commons for taxonomy and licensed-photo metadata, then writes a source-linked JSON packet to private Drive.
- Research photos are candidate references. Taxon matches and community identifications are not treated as confirmed specimen identifications.
- Each research packet carries a two-look comparison record and a 12-image plan: six named views for LOOK-A and six for LOOK-B. Visual review must fill both appearance records before generation; age or exuvia condition is never inferred from metadata.
- Neither workflow publishes candidate images, filenames, Drive IDs, manifests, or research packets as repository artifacts.
- The intake naming rules accept six views: FRONT, SIDE, REAR, OBLIQUE, TOP_DOWN, and WALKING_AWAY.
- The runner does not invoke built-in ChatGPT ImageGen. ChatGPT must inspect the reference photos, prepare the generation prompt, and run/refine ImageGen in a ChatGPT session.

## One-time setup

1. Keep `VNMV1_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` as a GitHub Actions secret.
2. Add `VNMV1_RESEARCH_QUEUE_FILE_ID` and `VNMV1_RESEARCH_OUTPUT_FOLDER_ID` as GitHub Actions secrets. Keep the queue and output folders private.
3. Share only the research queue/output folder with the service account's `client_email` as Editor. The research job needs to read the queue and write/update its packet. The existing image-intake folder can remain Viewer.
4. Add a JSON queue file in the private Drive folder, for example:
   `{"request_id":"card-0001-ind-1","scientific_name":"Abdomegaphobema mesomelas"}`
5. Confirm the Google Drive API is enabled for that service account's Cloud project. Do not put queue contents or service-account keys in this public repository.

The research job writes one `RESEARCH_PACKET_<request_id>_<queue-fingerprint>.json` per queue revision and skips revisions already processed. Edit the private queue JSON to request a fresh packet; use a new request_id for a new specimen/request. Do not put a specimen image, card export, or private reference board in the public repository.

## Privacy and cost

The public Actions workflows do not run on pull requests. Research output is written to private Drive; GitHub logs contain only fixed status messages and never print queue content, species names, card IDs, Drive IDs, or images. GitHub-hosted standard runners are free for public repositories. The built-in ChatGPT ImageGen tool is available in ChatGPT, not as a callable GitHub Actions service.
