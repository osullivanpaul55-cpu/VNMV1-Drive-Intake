# VNMV1 Drive Intake

GitHub Actions compiles one card research packet per scheduled run. Packet ZIPs and image bytes stay in a private Google Drive folder; GitHub receives only the research JSON and Drive link.

## Packet workflow

- The private queue contains 526 card jobs. Scheduled/manual runs process one card at a time; the full queue takes about 5.5 days at the 15-minute schedule, plus retries.
- Each Drive ZIP targets at least 14 images: the source specimen image plus relevant reference photos. The original is included only when its downloaded bytes match the queue SHA-256.
- The collector downloads reference photos only from the allowlisted iNaturalist and Wikimedia domains and only when the result has an accepted CC0, CC BY, or CC BY-SA license record. It stores source/attribution/license metadata with the image.
- If an image cannot be fetched or validated, the packet keeps its source link and reports the image-count shortfall. The 14-image target is not padded with generated images.
- Candidate taxa and reference-photo identifications still need human review. This runner does not invoke ChatGPT ImageGen. Open/attach the Drive ZIP in ChatGPT to research visually, generate, review, and refine.
- Public GitHub output contains research JSON and the authenticated Drive packet URL, never specimen or reference image bytes.

## GitHub Actions secrets

Set these repository secrets:

- `VNMV1_RESEARCH_QUEUE_FILE_ID`: private Drive JSON queue file ID.
- `VNMV1_PACKET_DRIVE_FOLDER_ID`: output folder ID for packet ZIP files.
- One of:
  - `VNMV1_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`: service-account JSON. Share the specimen source folder as Viewer and the output folder as Editor with its `client_email`.
  - `VNMV1_GOOGLE_DRIVE_OAUTH_USER_JSON`: authorized-user OAuth JSON with a refresh token and Drive write access. This is needed for uploads into a personal My Drive folder. Do not commit credentials.

Service accounts have no personal Drive storage quota. For service-account uploads, the destination must be a Shared Drive that permits the service account to create files; otherwise use user OAuth credentials for the personal Drive folder. The runner checks for all required secrets and skips processing if configuration is incomplete.

The currently prepared private output folder is `VNMV1_IMAGE_INGEST_PACKETS_V1` under the research queue folder. Set its ID as `VNMV1_PACKET_DRIVE_FOLDER_ID`.

## Queue record requirements

Each item needs a unique `request_id` and `scientific_name`. Card jobs should include `card_id`, `original_sha256`, and `original_filename`; an optional `original_drive_file_id` takes priority. When the Drive file ID is absent, the runner searches for `Specimen_Final_NNNN` image files and verifies the file hash before bundling.

## Limits

The runner processes one card per run and currently allows 24 candidate images from each research source. Candidate sources and the 14-image target depend on what is available online and whether downloads pass license, host, file-signature, and size checks. User-managed Google Drive storage and API quotas may apply.
