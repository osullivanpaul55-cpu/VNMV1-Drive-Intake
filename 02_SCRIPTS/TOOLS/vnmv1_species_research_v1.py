#!/usr/bin/env python3
"""Build a source-linked species research packet from a private Drive queue."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCOPES = ["https://www.googleapis.com/auth/drive"]
USER_AGENT = "VNMV1-research-runner/1.0"
LICENSES = {"cc0", "cc-by", "cc-by-sa"}
MAX_PHOTOS = 12


def fetch_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def api_url(base: str, params: dict) -> str:
    return base + "?" + urlencode(params)


def gbif_match(name: str) -> dict:
    data = fetch_json(api_url("https://api.gbif.org/v1/species/match", {"name": name}))
    return {
        "scientific_name": data.get("scientificName"),
        "canonical_name": data.get("canonicalName"),
        "rank": data.get("rank"),
        "status": data.get("status"),
        "confidence": data.get("confidence"),
        "usage_key": data.get("usageKey"),
        "match_type": data.get("matchType"),
        "source_url": api_url("https://api.gbif.org/v1/species/match", {"name": name}),
        "authority_note": "GBIF name match is a candidate; verify against the taxonomic authority for this group.",
    }


def inat_taxa(name: str) -> list[dict]:
    data = fetch_json(api_url("https://api.inaturalist.org/v1/taxa/autocomplete", {"q": name, "per_page": 8}))
    return [{
        "taxon_id": item.get("id"),
        "name": item.get("name"),
        "rank": item.get("rank"),
        "preferred_common_name": item.get("preferred_common_name"),
        "observations_count": item.get("observations_count"),
        "source_url": f"https://www.inaturalist.org/taxa/{item.get('id')}",
        "is_exact_name": str(item.get("name", "")).casefold() == name.casefold(),
    } for item in data.get("results", [])]


def inat_photo_candidates(taxon_id: int) -> list[dict]:
    data = fetch_json(api_url("https://api.inaturalist.org/v1/observations", {
        "taxon_id": taxon_id, "photos": "true", "quality_grade": "research",
        "photo_license": ",".join(sorted(LICENSES)), "per_page": MAX_PHOTOS,
        "order": "desc", "order_by": "votes",
    }))
    candidates = []
    for obs in data.get("results", []):
        for photo in obs.get("photos", []):
            license_code = (photo.get("license_code") or "").lower()
            if license_code not in LICENSES:
                continue
            candidates.append({
                "source": "iNaturalist",
                "observation_id": obs.get("id"),
                "observation_url": obs.get("uri"),
                "taxon_name_as_recorded": (obs.get("taxon") or {}).get("name"),
                "photo_id": photo.get("id"),
                "image_url": photo.get("url"),
                "license": license_code,
                "attribution": photo.get("attribution"),
                "observed_on": obs.get("observed_on"),
                "place_guess": obs.get("place_guess"),
                "source_warning": "Identification and photo license are user supplied; inspect the image and source before reuse.",
            })
            if len(candidates) >= MAX_PHOTOS:
                return candidates
    return candidates


def commons_candidates(name: str) -> list[dict]:
    data = fetch_json(api_url("https://commons.wikimedia.org/w/api.php", {
        "action": "query", "generator": "search",
        "gsrsearch": f'filetype:bitmap "{name}"', "gsrnamespace": 6,
        "gsrlimit": MAX_PHOTOS, "prop": "imageinfo",
        "iiprop": "url|size|extmetadata", "iiurlwidth": 1000,
        "format": "json", "formatversion": 2,
    }))
    candidates = []
    for page in (data.get("query") or {}).get("pages", []):
        info = (page.get("imageinfo") or [{}])[0]
        metadata = info.get("extmetadata") or {}

        def plain(key):
            value = metadata.get(key) or {}
            text = value.get("value")
            return re.sub(r"<[^>]*>", "", text).strip() if text else None

        license_name = plain("LicenseShortName")
        license_link = (metadata.get("License") or {}).get("value", "").lower()
        combined = (license_link + " " + (license_name or "")).lower()
        if not any(tag in combined for tag in ("cc0", "cc by", "cc-by")):
            continue
        candidates.append({
            "source": "Wikimedia Commons", "page_id": page.get("pageid"),
            "title": page.get("title"),
            "page_url": page.get("canonicalurl") or page.get("fullurl"),
            "image_url": info.get("thumburl") or info.get("url"),
            "width": info.get("width"), "height": info.get("height"),
            "license": license_name, "artist": plain("Artist"),
            "credit": plain("Credit"), "attribution_required": plain("AttributionRequired"),
            "source_warning": "Search results can show a different species or synonym; inspect the image and page before reuse.",
        })
    return candidates[:MAX_PHOTOS]


def build_packet(name: str, request_id: str) -> dict:
    gbif = gbif_match(name)
    taxa = inat_taxa(name)
    exact = next((taxon for taxon in taxa if taxon["is_exact_name"]), None)
    photos = inat_photo_candidates(exact["taxon_id"]) if exact and exact.get("taxon_id") else []
    commons = commons_candidates(name)
    views = ["FRONT", "SIDE", "REAR", "OBLIQUE", "TOP_DOWN", "WALKING_AWAY"]
    look_ids = ["LOOK-A", "LOOK-B"]
    pose_assignments = [
        {"look_id": look_id, "view": view, "status": "NOT_GENERATED"}
        for look_id in look_ids for view in views
    ]
    return {
        "schema": "VNMV1_SPECIES_RESEARCH_PACKET_V1",
        "request_id": request_id,
        "scientific_name_requested": name,
        "collected_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_status": "REFERENCE_CANDIDATES_READY_HUMAN_REVIEW_REQUIRED",
        "taxonomy": {
            "gbif_match": gbif,
            "inat_taxon_candidates": taxa,
            "inat_exact_name_match": bool(exact),
            "identity_note": "Name matching does not confirm specimen identity. Verify accepted name and synonyms with the specialist authority before using references.",
        },
        "reference_photos": {
            "inat": photos, "wikimedia_commons": commons,
            "photo_count": len(photos) + len(commons),
            "reuse_note": "Confirm image identity, license, attribution, source page, and reuse terms before use.",
        },
        "image_analysis_status": "NOT_ANALYSED_BY_VISION_MODEL",
        "specimen_appearance_pair": {
            "status": "UNASSESSED_REQUIRES_VISUAL_REVIEW",
            "species_name": name,
            "appearance_groups": [
                {
                    "look_id": look_id,
                    "age_or_condition": "UNASSESSED",
                    "visual_notes": None,
                    "supporting_reference_ids": [],
                    "review_status": "UNASSIGNED",
                }
                for look_id in look_ids
            ],
            "comparison_rule": "Assign two looks only after visual source review. Describe age, molt/exuvia state, wear, or freshness only when evidence supports it.",
        },
        "pose_plan": {
            "target_image_count": 12,
            "looks": 2,
            "views_per_look": len(views),
            "view_ids": views,
            "assignments": pose_assignments,
            "consistency_rule": "Keep each look identity stable across its six views; keep the two looks distinct from each other.",
        },
        "generation_handoff": {
            "status": "READY_FOR_CHATGPT_REVIEW",
            "species_name": name,
            "required_next_steps": [
                "Inspect reference images and reject wrong taxa or unsuitable views.",
                "Record visible proportions, color, hair density, texture, and specimen condition with source links.",
                "Fill the LOOK-A and LOOK-B evidence fields from visually reviewed references; never infer age or exuvia condition from name metadata.",
                "Generate six views for each accepted look, preserving each look consistently across its views, then review and refine each result.",
            ],
            "automatic_image_generation": "BUILT_IN_CHATGPT_IMAGEGEN_CANNOT_BE_INVOKED_BY_GITHUB_ACTIONS",
        },
        "request_fingerprint": hashlib.sha256(" ".join(name.casefold().split()).encode()).hexdigest(),
    }


def _drive_service():
    oauth_client_id = os.environ.get("GDRIVE_OAUTH_CLIENT_ID", "").strip()
    oauth_client_secret = os.environ.get("GDRIVE_OAUTH_CLIENT_SECRET", "").strip()
    oauth_refresh_token = os.environ.get("GDRIVE_OAUTH_REFRESH_TOKEN", "").strip()
    from googleapiclient.discovery import build

    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        # Prefer service-account auth when configured. OAuth secrets remain as
        # a fallback for environments where service accounts cannot be used.
        try:
            info = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Drive service-account secret is invalid") from exc
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    elif oauth_client_id and oauth_client_secret and oauth_refresh_token:
        # OAuth writes into the authenticated person's My Drive and uses their
        # Drive quota, which is required for personal Gmail accounts.
        from google.oauth2.credentials import Credentials
        creds = Credentials(
            token=None,
            refresh_token=oauth_refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=oauth_client_id,
            client_secret=oauth_client_secret,
            scopes=SCOPES,
        )
    else:
        raise RuntimeError("Google Drive service-account JSON or OAuth credentials are required")
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value or ""):
        raise ValueError("request_id contains invalid characters")
    return value


def _read_queue(service, file_id: str) -> tuple[list[dict], str]:
    from googleapiclient.http import MediaIoBaseDownload
    meta = service.files().get(fileId=file_id, fields="mimeType").execute()
    if meta.get("mimeType") != "application/json":
        raise ValueError("Queue file must be application/json")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    raw = buffer.getvalue()
    payload = json.loads(raw.decode("utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("jobs"), list):
        records = payload["jobs"]
    elif isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = [payload]
    else:
        raise ValueError("Queue content must be an object, jobs object, or array")
    jobs = []
    for job in records:
        if not isinstance(job, dict):
            continue
        name = job.get("scientific_name")
        request_id = _safe_id(job.get("request_id", ""))
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,119}", name.strip()):
            raise ValueError("Queue item has a missing or invalid scientific_name")
        jobs.append({
            "scientific_name": name.strip(),
            "request_id": request_id,
            "queue_fingerprint": hashlib.sha256(
                json.dumps(job, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:12],
        })
    if not jobs:
        raise ValueError("Queue contains no valid jobs")
    return jobs, hashlib.sha256(raw).hexdigest()[:12]


def _packet_exists(service, folder_id: str, request_id: str) -> bool:
    from googleapiclient.errors import HttpError
    filename = f"RESEARCH_PACKET_{request_id}.json"
    escaped = filename.replace("'", "\\'")
    response = service.files().list(
        q=f"name='{escaped}' and '{folder_id}' in parents and trashed=false",
        pageSize=1, fields="files(id,name)"
    ).execute()
    return bool(response.get("files"))


def _write_packet(service, folder_id: str, packet: dict, request_id: str) -> None:
    from googleapiclient.http import MediaIoBaseUpload
    filename = f"RESEARCH_PACKET_{request_id}.json"
    body = {
        "name": filename,
        "mimeType": "application/json",
        "parents": [folder_id],
    }
    payload = json.dumps(packet, ensure_ascii=False, indent=2).encode("utf-8")
    media = MediaIoBaseUpload(io.BytesIO(payload), mimetype="application/json", resumable=False)
    service.files().create(body=body, media_body=media, fields="id").execute()



def main() -> int:
    stage = ["drive_authentication"]
    try:
        service = _drive_service()
        set_stage = lambda value: stage.__setitem__(0, value)
        set_stage("queue_read")
        jobs, queue_fingerprint = _read_queue(service, os.environ["RESEARCH_QUEUE_FILE_ID"])
        output_folder_id = os.environ["RESEARCH_OUTPUT_FOLDER_ID"].strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", output_folder_id):
            raise ValueError("Research output folder is missing or invalid")
        selected = None
        set_stage("output_deduplication_check")
        for job in jobs:
            if not _packet_exists(service, output_folder_id, job["request_id"]):
                selected = job
                break
        if selected is None:
            print("RESEARCH_QUEUE_COMPLETE_NO_UNPROCESSED_ITEMS")
            return 0
        set_stage("reference_research")
        packet = build_packet(selected["scientific_name"], selected["request_id"])
        packet["queue_fingerprint"] = queue_fingerprint
        packet["request_fingerprint"] = selected["queue_fingerprint"]
        set_stage("drive_packet_write")
        _write_packet(service, output_folder_id, packet, selected["request_id"])
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status is None:
            status = getattr(exc, "code", None)
        safe_detail = f"HTTP_{status}" if isinstance(status, int) else type(exc).__name__
        print(f"RESEARCH_BLOCKED: stage={stage[0]}; {safe_detail}; private details redacted",
              file=sys.stderr)
        return 2
    print("PRIVATE_DRIVE_RESEARCH_PACKET_CREATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
