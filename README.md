# VNMV1 Drive Intake

A small public-code runner that checks one private Google Drive image inbox. It contains no specimen images, species research, private card inputs, or service-account key.

## What it does

- Checks the configured Drive folder every five minutes, or on manual dispatch.
- Accepts only the Card 0001 candidate image and JSON-sidecar naming pattern enforced by the intake script.
- Uses a read-only Drive scope and downloads matching candidates only into the temporary GitHub-hosted runner while it computes hashes.
- Keeps a private deduplication cache of Drive file IDs and checksums; it does not cache image bytes.
- Does not commit or upload candidate images, filenames, Drive IDs, manifests, or research inputs as GitHub artifacts.
- Does not generate images or invoke ChatGPT ImageGen. Image generation and visual review remain in ChatGPT; use the Drive connector to review files that stay in the Drive inbox.

The runner's temporary files are deleted when the GitHub job ends. Public workflows are configured for schedule and manual dispatch only; they do not run on pull requests.

## One-time setup

1. Add a repository Actions secret named `VNMV1_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON` containing a Google service-account JSON key. GitHub secrets from `VNMV1_CORE` do not transfer to this repository; GitHub does not reveal existing secret values. If you no longer have the original JSON key file, create a new key for the same service account in Google Cloud.
2. Add repository variable `VNMV1_IMAGEGEN_DRIVE_FOLDER_ID` with the intake folder ID.
3. Share only the intake folder with the service account's `client_email` as Viewer.
4. Confirm Google Drive API is enabled for the service account's Cloud project.

Do not place key JSON files, images, sidecars, reference boards, or card research in this repository.

## Cost and privacy

GitHub states standard hosted runners are free for public repositories. This workflow does not upload candidate artifacts. The actual Drive-to-runner access still depends on the secret and folder permission being correct. The Actions run log contains no filenames, file IDs, hashes, or image contents.
