#!/usr/bin/env python3
"""Read-only Drive candidate intake. Local output is temporary; public workflows must not publish it."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path

NAME_RE = re.compile(
    r"^CARD-0001__(?:IND-1|IND-2)__(?:REAR|SIDE|WALKING_AWAY|TOP_DOWN|OBLIQUE)__v[0-9]{2,}\.(?:png|jpe?g|webp|json)$",
    re.IGNORECASE,
)
IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp"}
MAX_BYTES = 40 * 1024 * 1024


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def allowed_candidate(name: str, mime_type: str) -> bool:
    if not NAME_RE.fullmatch(name):
        return False
    if name.lower().endswith(".json"):
        return mime_type in {"application/json", "text/plain"}
    return mime_type in IMAGE_MIMES


def credentials_from_env():
    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError("GDRIVE_SERVICE_ACCOUNT_JSON secret is not configured")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GDRIVE_SERVICE_ACCOUNT_JSON is not valid JSON") from exc
    from google.oauth2.service_account import Credentials
    return Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )


def ingest(folder_id: str, out_dir: Path, state_path: Path | None = None) -> dict:
    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError as exc:
        raise RuntimeError("Install google-api-python-client and google-auth") from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = state_path or (out_dir / "state.json")
    state_path.parent.mkdir(parents=True, exist_ok=True)
    prior = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {"processed": {}}
    processed = dict(prior.get("processed", {}))

    service = build("drive", "v3", credentials=credentials_from_env(), cache_discovery=False)
    records = []
    page_token = None
    query = f"'{folder_id}' in parents and trashed = false"
    while True:
        page = service.files().list(
            q=query,
            pageSize=100,
            pageToken=page_token,
            orderBy="createdTime",
            fields="nextPageToken,files(id,name,mimeType,size,md5Checksum,createdTime,modifiedTime)",
        ).execute()
        for item in page.get("files", []):
            name = item.get("name", "")
            mime = item.get("mimeType", "")
            if not allowed_candidate(name, mime):
                continue
            drive_md5 = item.get("md5Checksum")
            if item["id"] in processed and processed[item["id"]].get("drive_md5") == drive_md5:
                continue
            size = int(item.get("size") or 0)
            if size > MAX_BYTES:
                records.append({"drive_file_id": item["id"], "name": name, "status": "REJECTED_TOO_LARGE", "size": size})
                continue
            safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", name)
            destination = out_dir / f"{item['id']}__{safe_name}"
            buffer = io.BytesIO()
            downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=item["id"]))
            done = False
            while not done:
                _, done = downloader.next_chunk()
            data = buffer.getvalue()
            if len(data) > MAX_BYTES:
                records.append({"drive_file_id": item["id"], "name": name, "status": "REJECTED_TOO_LARGE", "size": len(data)})
                continue
            digest = sha256_bytes(data)
            destination.write_bytes(data)
            processed[item["id"]] = {"drive_md5": drive_md5, "sha256": digest}
            records.append({
                "drive_file_id": item["id"],
                "name": name,
                "mime_type": mime,
                "drive_md5": drive_md5,
                "size_bytes": len(data),
                "sha256": digest,
                "local_path": str(destination),
                "created_time": item.get("createdTime"),
                "modified_time": item.get("modifiedTime"),
                "status": "INGESTED_UNREVIEWED",
            })
        page_token = page.get("nextPageToken")
        if not page_token:
            break

    state_path.write_text(json.dumps({"processed": processed}, indent=2) + "\n", encoding="utf-8")
    manifest = {
        "schema": "VNMV1_DRIVE_CANDIDATE_INTAKE_V1",
        "folder_id": folder_id,
        "scope": "Card 0001 candidate image and JSON sidecar names only",
        "review_status": "UNREVIEWED",
        "records": records,
    }
    (out_dir / "INTAKE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--folder-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--state")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = ingest(args.folder_id, Path(args.out), Path(args.state) if args.state else None)
    except Exception as exc:
        print(f"BLOCKED: {type(exc).__name__}; private details redacted", file=sys.stderr)
        return 2
    print("INTAKE_SCAN_COMPLETED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
