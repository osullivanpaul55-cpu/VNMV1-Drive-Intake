#!/usr/bin/env python3
"""Build a private, source-linked species research packet from a Drive queue."""
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
        "generation_handoff": {
            "status": "READY_FOR_CHATGPT_REVIEW",
            "species_name": name,
            "required_next_steps": [
                "Inspect reference images and reject wrong taxa or unsuitable views.",
                "Record visible proportions, color, hair density, texture, and specimen condition with source links.",
                "Keep distinct specimen appearances separate unless sources support the difference.",
                "Use accepted references to prepare an ImageGen request, then review and refine the output.",
            ],
            "automatic_image_generation": "BUILT_IN_CHATGPT_IMAGEGEN_CANNOT_BE_INVOKED_BY_GITHUB_ACTIONS",
        },
        "request_fingerprint": hashlib.sha256(" ".join(name.casefold().split()).encode()).hexdigest(),
    }


def _drive_service():
    raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "")
    if not raw:
        raise RuntimeError("Drive service-account secret is missing")
    try:
        info = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Drive service-account secret is invalid") from exc
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build
    creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _safe_id(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", value or ""):
        raise ValueError("request_id contains invalid characters")
    return value


def _read_queue(service, file_id: str) -> dict:
    from googleapiclient.http import MediaIoBaseDownload
    meta = service.files().get(fileId=file_id, fields="mimeType").execute()
    if meta.get("mimeType") != "application/json":
        raise ValueError("Queue file must be application/json")
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=file_id))
    done = False
    while not done:
        _, done = downloader.next_chunk()
    job = json.loads(buffer.getvalue().decode("utf-8"))
    if not isinstance(job, dict):
        raise ValueError("Queue content must be a JSON object")
    name = job.get("scientific_name")
    request_id = _safe_id(job.get("request_id", ""))
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,119}", name.strip()):
        raise ValueError("scientific_name is missing or invalid")
    return {"scientific_name": name.strip(), "request_id": request_id}


def _write_packet(service, folder_id: str, request_id: str, packet: dict) -> None:
    from googleapiclient.http import MediaIoBaseUpload
    name = f"RESEARCH_PACKET_{request_id}.json"
    query = f"name = '{name}' and '{folder_id}' in parents and trashed = false"
    existing = service.files().list(q=query, pageSize=10, fields="files(id)").execute().get("files", [])
    media = MediaIoBaseUpload(io.BytesIO(json.dumps(packet, ensure_ascii=False, indent=2).encode()),
                              mimetype="application/json", resumable=False)
    if existing:
        service.files().update(fileId=existing[0]["id"], media_body=media).execute()
    else:
        service.files().create(body={"name": name, "mimeType": "application/json", "parents": [folder_id]},
                               media_body=media, fields="id").execute()


def main() -> int:
    try:
        service = _drive_service()
        job = _read_queue(service, os.environ["RESEARCH_QUEUE_FILE_ID"])
        packet = build_packet(job["scientific_name"], job["request_id"])
        _write_packet(service, os.environ["RESEARCH_OUTPUT_FOLDER_ID"], job["request_id"], packet)
    except Exception as exc:
        print(f"RESEARCH_BLOCKED: {type(exc).__name__}; private details redacted", file=sys.stderr)
        return 2
    print("PRIVATE_SPECIES_RESEARCH_PACKET_SAVED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
