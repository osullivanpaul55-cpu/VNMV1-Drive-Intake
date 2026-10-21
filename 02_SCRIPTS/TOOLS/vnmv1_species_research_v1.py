#!/usr/bin/env python3
"""Build a source-linked species research packet from a private Drive queue."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCOPES = ["https://www.googleapis.com/auth/drive"]
USER_AGENT = "VNMV1-research-runner/1.0"
LICENSES = {"cc0", "cc-by", "cc-by-sa"}
MAX_PHOTOS = 24
MIN_PACKET_IMAGES = 14
MAX_IMAGE_BYTES = 12 * 1024 * 1024


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


def build_packet(name: str, request_id: str, specimen_context: dict | None = None) -> dict:
    gbif = gbif_match(name)
    taxa = inat_taxa(name)
    exact = next((taxon for taxon in taxa if taxon["is_exact_name"]), None)
    photos = inat_photo_candidates(exact["taxon_id"]) if exact and exact.get("taxon_id") else []
    commons = commons_candidates(name)
    views = ["FRONT", "SIDE", "REAR", "OBLIQUE", "TOP_DOWN", "WALKING_AWAY"]
    look_defs = [
        {"look_id": "YOUNGER_FEMALE", "label": "Younger/juvenile female study track", "life_stage": "YOUNG_OR_JUVENILE"},
        {"look_id": "OLDER_FEMALE", "label": "Older/adult female study track", "life_stage": "ADULT_OR_OLDER"},
    ]
    look_ids = [look["look_id"] for look in look_defs]
    specimen_context = specimen_context or {}
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
            "image_bundle_target": MIN_PACKET_IMAGES,
            "reuse_note": "Confirm image identity, license, attribution, source page, and reuse terms before use.",
        },
        "source_specimen": {
            "card_id": specimen_context.get("card_id"),
            "original_drive_file_id": specimen_context.get("original_drive_file_id"),
            "original_sha256": specimen_context.get("original_sha256"),
            "original_filename": specimen_context.get("original_filename"),
            "original_manifest_status": specimen_context.get("original_status"),
            "original_match_method": specimen_context.get("original_match_method"),
            "original_match_confidence": specimen_context.get("original_match_confidence"),
            "taxon_input_status": specimen_context.get("identity_input_status", "UNASSESSED_CANDIDATE_INPUT"),
            "taxon_input_note": specimen_context.get("taxon_input_note"),
            "sex_default": "FEMALE",
            "sex_default_basis": "USER_ASSUMPTION_FOR_PACKETING",
            "photographed_individual_sex": "UNKNOWN_UNVERIFIED",
            "photographed_individual_life_stage": "UNKNOWN_UNVERIFIED",
            "original_image_embedded_in_public_packet": False,
            "original_image_note": "Original remains in private Drive; this public packet records its source binding only.",
        },
        "image_analysis_status": "NOT_ANALYSED_BY_VISION_MODEL",
        "specimen_appearance_pair": {
            "status": "UNASSESSED_REQUIRES_VISUAL_REVIEW",
            "species_name": name,
            "appearance_groups": [
                {
                    **look,
                    "sex_for_study": "FEMALE_ASSUMED_BY_USER",
                    "age_or_condition": look["life_stage"],
                    "life_stage_status": "STUDY_CATEGORY_ONLY_RESEARCH_REQUIRED",
                    "visual_notes": None,
                    "supporting_reference_ids": [],
                    "review_status": "UNASSIGNED_REQUIRES_VISUAL_REVIEW",
                }
                for look in look_defs
            ],
            "comparison_rule": "These are two comparative study tracks, not claims about the photographed individual. Assign age/stage traits only after visual source review; retain unknowns.",
        },
        "closeup_plan": {
            "target_image_count": 6,
            "views_per_look": 3,
            "view_ids": ["FACE_EYES_PEDIPALPS", "LEG_JOINT_COLOR_BOUNDARIES", "BODY_SURFACE_SETAE"],
            "assignments": [
                {"look_id": look_id, "view": view, "status": "REFERENCE_RESEARCH_AND_REVIEW_PENDING"}
                for look_id in look_ids
                for view in ["FACE_EYES_PEDIPALPS", "LEG_JOINT_COLOR_BOUNDARIES", "BODY_SURFACE_SETAE"]
            ],
            "evidence_rule": "Use source-linked, visually reviewed images; do not treat synthetic close-ups as specimen evidence.",
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
                "Fill the younger-female and older/adult-female evidence fields from visually reviewed references; never infer the photographed specimen's sex or age from name metadata.",
                "Research three close-up evidence targets for each look: face/eyes/pedipalps, leg-joint color boundaries, and body surface/setae.",
                "Generate six views for each accepted look, preserving each look consistently across its views, then review and refine each result.",
            ],
            "automatic_image_generation": "BUILT_IN_CHATGPT_IMAGEGEN_CANNOT_BE_INVOKED_BY_GITHUB_ACTIONS",
        },
        "request_fingerprint": hashlib.sha256(" ".join(name.casefold().split()).encode()).hexdigest(),
    }


def _drive_service():
    from googleapiclient.discovery import build
    oauth_raw = os.environ.get("GDRIVE_OAUTH_USER_JSON", "").strip()
    service_raw = os.environ.get("GDRIVE_SERVICE_ACCOUNT_JSON", "").strip()
    if oauth_raw:
        try:
            info = json.loads(oauth_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Drive OAuth user secret is invalid") from exc
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_info(info, scopes=SCOPES)
    elif service_raw:
        try:
            info = json.loads(service_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Drive service-account secret is invalid") from exc
        from google.oauth2.service_account import Credentials
        creds = Credentials.from_service_account_info(info, scopes=SCOPES)
    else:
        raise RuntimeError("Google Drive OAuth-user or service-account JSON is required")
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
        original_drive_file_id = job.get("original_drive_file_id")
        original_sha256 = job.get("original_sha256")
        if original_drive_file_id is not None and not re.fullmatch(r"[A-Za-z0-9_-]{10,100}", str(original_drive_file_id)):
            raise ValueError("Queue item has an invalid original_drive_file_id")
        if original_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", str(original_sha256)):
            raise ValueError("Queue item has an invalid original_sha256")
        jobs.append({
            "scientific_name": name.strip(),
            "request_id": request_id,
            "card_id": job.get("card_id"),
            "original_drive_file_id": original_drive_file_id,
            "original_sha256": original_sha256,
            "original_filename": job.get("original_filename"),
            "original_status": job.get("original_status"),
            "original_match_method": job.get("original_match_method"),
            "original_match_confidence": job.get("original_match_confidence"),
            "identity_input_status": job.get("identity_input_status", "UNASSESSED_CANDIDATE_INPUT"),
            "taxon_input_note": job.get("taxon_input_note"),
            "queue_fingerprint": hashlib.sha256(
                json.dumps(job, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()[:12],
        })
    if not jobs:
        raise ValueError("Queue contains no valid jobs")
    return jobs, hashlib.sha256(raw).hexdigest()[:12]



def _image_extension(content_type: str | None, data: bytes) -> str | None:
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    if data.startswith(bytes.fromhex("89504e470d0a1a0a")): return ".png"
    if data.startswith(bytes.fromhex("ffd8ff")): return ".jpg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP": return ".webp"
    return None

def _find_original_file(service, job: dict) -> dict | None:
    file_id = job.get("original_drive_file_id")
    if file_id:
        return service.files().get(fileId=file_id, fields="id,name,mimeType,webViewLink").execute()
    match = re.search(r"(\d{4})$", str(job.get("card_id") or ""))
    if not match: return None
    number = match.group(1)
    for extension in ("png", "jpg", "jpeg", "webp"):
        name = f"Specimen_Final_{number}.{extension}"
        result = service.files().list(q=f"name = '{name}' and trashed = false", pageSize=10, fields="files(id,name,mimeType,webViewLink)", includeItemsFromAllDrives=True, supportsAllDrives=True).execute()
        found = result.get("files") or []
        if found: return found[0]
    return None

def _drive_file_bytes(service, file_id: str) -> bytes:
    from googleapiclient.http import MediaIoBaseDownload
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, service.files().get_media(fileId=file_id))
    done = False
    while not done: _, done = downloader.next_chunk()
    return buffer.getvalue()

def _download_external_image(candidate: dict) -> tuple[bytes | None, str | None]:
    from urllib.parse import urlparse
    url = candidate.get("image_url")
    if not isinstance(url, str): return None, None
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = ("inaturalist.org", "inaturalist-open-data.s3.amazonaws.com", "wikimedia.org")
    if parsed.scheme != "https" or not any(host == x or host.endswith("." + x) for x in allowed): return None, None
    try:
        request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "image/*"})
        with urlopen(request, timeout=25) as response:
            content_type = response.headers.get("Content-Type")
            data = response.read(MAX_IMAGE_BYTES + 1)
        if len(data) > MAX_IMAGE_BYTES: return None, None
        ext = _image_extension(content_type, data)
        return (data, ext) if ext else (None, None)
    except Exception:
        return None, None


def _make_and_upload_image_packet(service, packet: dict, queue_fingerprint: str) -> dict:
    from googleapiclient.http import MediaIoBaseUpload
    folder_id = os.environ.get("VNMV1_PACKET_DRIVE_FOLDER_ID", "").strip()
    if not folder_id:
        raise RuntimeError("VNMV1_PACKET_DRIVE_FOLDER_ID is required")
    packet["queue_fingerprint"] = queue_fingerprint
    source_job = packet.get("_source_job") or {}
    source = packet.get("source_specimen") or {}
    card = source.get("card_id") or packet.get("request_id")
    safe_card = re.sub(r"[^A-Za-z0-9_-]", "_", str(card))
    candidates = []
    refs = packet.get("reference_photos", {})
    for group in ("inat", "wikimedia_commons"):
        candidates.extend(refs.get(group, []))
    for item in candidates:
        item["bundle_status"] = "LINK_ONLY"
    image_blobs = []
    original_verified = False
    original_link = None
    original = _find_original_file(service, source_job)
    expected = source.get("original_sha256")
    if original:
        original_link = original.get("webViewLink") or ("https://drive.google.com/open?id=" + original["id"])
        try:
            data = _drive_file_bytes(service, original["id"])
            ext = _image_extension(original.get("mimeType"), data)
            if ext and expected and hashlib.sha256(data).hexdigest().casefold() == expected.casefold():
                image_blobs.append(("images/{}_ORIGINAL{}".format(safe_card, ext), data))
                original_verified = True
        except Exception:
            pass
    for candidate in candidates:
        if len(image_blobs) >= MIN_PACKET_IMAGES:
            break
        data, ext = _download_external_image(candidate)
        if data and ext:
            image_blobs.append(("images/reference_{:02d}{}".format(len(image_blobs), ext), data))
            candidate["bundle_status"] = "IMAGE_INCLUDED"
        else:
            candidate["bundle_status"] = "LINK_ONLY_FETCH_OR_FORMAT_UNAVAILABLE"
    image_index = {
        "schema": "VNMV1_IMAGE_INGEST_PACKET_V1",
        "card_id": card,
        "request_id": packet.get("request_id"),
        "minimum_image_target": MIN_PACKET_IMAGES,
        "image_count": len(image_blobs),
        "original_image_verified": original_verified,
        "original_sha256_expected": expected,
        "original_drive_source_url": original_link,
        "reference_images_included": sum(x.get("bundle_status") == "IMAGE_INCLUDED" for x in candidates),
        "reference_links_only": sum(x.get("bundle_status") != "IMAGE_INCLUDED" for x in candidates),
        "image_target_met": len(image_blobs) >= MIN_PACKET_IMAGES,
        "rights_note": "Reference sources and license metadata are in research_packet.json; verify before reuse.",
        "images": [
            {"path": path, "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
            for path, data in image_blobs
        ],
    }
    packet["image_packet"] = {
        "status": "IMAGE_TARGET_MET" if image_index["image_target_met"] and original_verified else "PARTIAL_IMAGES_LINKS_RETAINED",
        "minimum_image_target": MIN_PACKET_IMAGES,
        "image_count": len(image_blobs),
        "original_image_sha256_verified": original_verified,
        "reference_images_included": image_index["reference_images_included"],
        "reference_links_only": image_index["reference_links_only"],
        "shortfall": max(0, MIN_PACKET_IMAGES - len(image_blobs)),
        "target_met": image_index["image_target_met"] and original_verified,
    }
    packet_zip = json.loads(json.dumps(packet))
    packet_zip.pop("drive_bundle", None)
    packet_zip.pop("_source_job", None)
    packet_zip.get("source_specimen", {}).pop("original_drive_file_id", None)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("research_packet.json", json.dumps(packet_zip, ensure_ascii=False, indent=2))
        zf.writestr("image_index.json", json.dumps(image_index, ensure_ascii=False, indent=2))
        for path, data in image_blobs:
            zf.writestr(path, data)
    bundle_name = "{}_FEMALE_STAGE_PAIR_IMAGE_PACKET_V1.zip".format(safe_card)
    media = MediaIoBaseUpload(io.BytesIO(archive.getvalue()), mimetype="application/zip", resumable=True)
    uploaded = service.files().create(
        body={"name": bundle_name, "parents": [folder_id]},
        media_body=media,
        fields="id,name,webViewLink",
        supportsAllDrives=True,
    ).execute()
    packet["drive_bundle"] = {
        "status": "UPLOADED_TO_PRIVATE_DRIVE",
        "file_id": uploaded.get("id"),
        "file_name": uploaded.get("name", bundle_name),
        "url": uploaded.get("webViewLink") or ("https://drive.google.com/open?id=" + uploaded["id"]),
    }
    source["original_drive_file_id"] = None
    source["original_image_note"] = (
        "Original included only if its bytes match the queue SHA-256; otherwise source link retained."
    )
    return packet



def _write_packet(packet: dict, queue_fingerprint: str) -> str:
    os.makedirs("research-output", exist_ok=True)
    request_id = _safe_id(packet.get("request_id", ""))
    path = os.path.join("research-output", f"{request_id}.json")
    packet["queue_fingerprint"] = queue_fingerprint
    public_packet = json.loads(json.dumps(packet))
    public_packet.get("source_specimen", {})["original_drive_file_id"] = None
    with open(path, "w", encoding="utf-8") as output:
        json.dump(public_packet, output, ensure_ascii=False, indent=2)
        output.write("\n")
    return path



def main() -> int:
    stage = ["drive_authentication"]
    try:
        service = _drive_service()
        stage[0] = "queue_read"
        jobs, queue_fingerprint = _read_queue(service, os.environ["RESEARCH_QUEUE_FILE_ID"])
        os.makedirs("research-output", exist_ok=True)
        selected = next(
            (job for job in jobs if not os.path.exists(
                os.path.join("research-output", f"{job['request_id']}.json")
            )),
            None,
        )
        if selected is None:
            print("RESEARCH_QUEUE_COMPLETE_NO_UNPROCESSED_ITEMS")
            return 0
        stage[0] = "reference_research"
        packet = build_packet(selected["scientific_name"], selected["request_id"], selected)
        packet["_source_job"] = selected
        stage[0] = "private_drive_image_packet_upload"
        packet = _make_and_upload_image_packet(service, packet, queue_fingerprint)
        packet.pop("_source_job", None)
        packet_path = _write_packet(packet, queue_fingerprint)
    except Exception as exc:
        status = getattr(getattr(exc, "resp", None), "status", None)
        if status is None:
            status = getattr(exc, "code", None)
        safe_detail = f"HTTP_{status}" if isinstance(status, int) else type(exc).__name__
        if type(exc).__name__ == "RefreshError":
            safe_detail = "OAUTH_REFRESH_REJECTED"
            safe_args = " ".join(str(arg) for arg in getattr(exc, "args", ())).lower()
            for code in ("invalid_grant", "invalid_client", "unauthorized_client",
                         "invalid_scope", "access_denied", "invalid_request"):
                if code in safe_args:
                    safe_detail = f"OAUTH_{code.upper()}"
                    break
        print(f"RESEARCH_BLOCKED: stage={stage[0]}; {safe_detail}; private details redacted",
              file=sys.stderr)
        return 2
    print("PRIVATE_DRIVE_IMAGE_PACKET_UPLOADED_PUBLIC_METADATA_READY_FOR_COMMIT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
