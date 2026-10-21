# VNMV1 Drive Intake

Public runner code for collecting species research into a private Google Drive folder. It does not publish queue contents, card IDs, specimen images, or research packets to GitHub.

## Research workflow

- GitHub Actions checks the configured Drive queue every 15 minutes and can also be started manually.
- A queue may be one JSON object, a JSON array, or an object with a `jobs` array. Each item needs a unique `request_id` and `scientific_name`.
- Each run creates at most one packet for the first queue item without a matching packet in the output folder. The next scheduled run continues with the next item. Existing packets are not duplicated.
- Packets include candidate taxonomic matches, source-linked licensed-photo metadata, two appearance groups awaiting visual evidence review, and a 12-view plan. Research candidates are not treated as confirmed specimen identifications.
- The workflow does not download/visually inspect reference photos and cannot call built-in ChatGPT ImageGen. In ChatGPT, inspect the referenced images, record supported appearance differences, then generate, review, and refine the 12 images. Keep each approved image and review notes in private Drive.
- Public Actions runs are free within GitHub's current public-repository policy. Google Drive API quotas and ChatGPT image generation remain subject to their respective limits.

## Required repository secrets

- `VNMV1_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`: service-account JSON.
- `VNMV1_RESEARCH_QUEUE_FILE_ID`: Drive file ID for the JSON queue.
- `VNMV1_RESEARCH_OUTPUT_FOLDER_ID`: Drive folder ID where packets should be created.

Enable the Google Drive API for the service-account project and share both the queue file and output folder with the service account email as Editor. The runner uses Drive API write access to read the queue and create private packet files. Keep the queue and output folders restricted.

## Queue example

```json
{
  "jobs": [
    {"request_id": "card-0001-pilot", "scientific_name": "Abdomegaphobema mesomelas"},
    {"request_id": "card-0002-pilot", "scientific_name": "Example species"}
  ]
}
```

Only add entries whose card identity and species name have been reconciled against the authoritative roster. The current roster audit contains unresolved membership, so do not bulk-queue all 526 cards until those identities are confirmed.
