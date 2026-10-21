# VNMV1 Drive Intake

Public GitHub Actions runner for a private Google Drive research queue. The queue and credentials stay private; source-linked research packets are committed to this public repository.

## Research workflow

- GitHub Actions checks the configured Drive queue every 15 minutes and can also be started manually.
- The queue can be one JSON object, a JSON array, or an object with a `jobs` array. Each item needs a unique `request_id` and `scientific_name`. Card-linked jobs should also carry `card_id`, `original_drive_file_id`, `original_sha256`, and `original_filename` so the public packet can be bound back to the private original.
- Each run handles at most one item without a matching `research-output/<request_id>.json` packet. The next scheduled run continues with the next item. Committed packets are not duplicated.
- Packets include candidate taxonomy matches, source-linked licensed-photo metadata, two appearance groups awaiting visual evidence review, and a 12-view plan. Candidate matches are not confirmed specimen identification.
- The Drive queue is read-only from Actions and stays restricted. Research packets are public in this repository, including request IDs and species names. Do not place private personal data in the queue.
- The runner does not download or visually inspect references and cannot invoke built-in ChatGPT ImageGen. In ChatGPT, inspect reference images, record supported appearance differences, then generate, review, and refine images. Keep generated image assets and image review notes in Drive.
- Public Actions runners are free within GitHub's current public-repository policy. Google Drive API quotas and ChatGPT image generation remain subject to their respective limits.

## Required repository secrets

- `VNMV1_GOOGLE_DRIVE_SERVICE_ACCOUNT_JSON`: service-account JSON, with read access to the queue file.
- `VNMV1_RESEARCH_QUEUE_FILE_ID`: Drive file ID for the JSON queue.

Enable the Drive API for the service-account project and share the queue file or its containing folder with the service account as Viewer. No Drive write permission, OAuth refresh token, output folder, or user storage quota is needed.

## Queue example

```json
{
  "jobs": [
    {"request_id": "card-0001-pilot", "scientific_name": "Abdomegaphobema mesomelas"},
    {"request_id": "card-0002-pilot", "scientific_name": "Example species"}
  ]
}
```

Only add entries whose card identity and scientific name have been reconciled against the authoritative roster. The current roster audit contains unresolved membership, so do not bulk-queue all 526 cards until those identities are confirmed.
