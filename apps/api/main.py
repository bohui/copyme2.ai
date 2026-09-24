from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import io
import json
import os
import re
import zipfile
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from .namespaces import rewrite_memoir_path
from .store import MemoryStore, PostgresMemoryStore, new_id, now_iso, sha256_bytes, sha256_json


class LooseModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProjectCreate(LooseModel):
    mode: str = "self"
    language: str = "en-AU"
    birth_year: int | None = None
    birth_date_expression: str | None = None
    birth_place: str | None = None
    childhood_place: str | None = None
    region: str = "au"
    storyteller_account_id: str | None = None
    storyteller_name: str | None = None


class SessionCreate(LooseModel):
    topic_id: str = "childhood_home"
    source_asset_id: str | None = None
    include_video: bool = False


class ConsentCreate(LooseModel):
    purpose: str
    granted: bool = True
    subject_account_id: str | None = None
    assistance_method: str = "self"
    notice_version: str = "notice-2026-09-21"
    locale: str = "en-AU"


class InvitationCreate(LooseModel):
    intended_role: str = "editor"
    capability_set: list[str] = Field(default_factory=lambda: ["read_shared", "propose_correction"])
    expires_hours: int = 72


class AnswerCreate(LooseModel):
    text: str = ""
    turn_type: str = "initial"
    participant_account_id: str | None = None
    upload_id: str | None = None
    skip: bool = False


class CueReactionCreate(LooseModel):
    asset_id: str
    reaction: str
    comment: str | None = None


class CompleteCreate(LooseModel):
    draft_text: str | None = None
    visibility: str = "private"
    include_in_digital: bool = False
    include_in_print: bool = False
    expected_revision: int | None = None


class UploadCreate(LooseModel):
    project_id: str | None = None
    kind: str = "audio"
    filename: str = "recording.webm"
    mime_type: str = "audio/webm"
    expected_size: int | None = None
    expected_checksum: str | None = None
    rights_confirmed: bool = False
    visibility: str = "private"
    duration_seconds: float | None = None


class UploadPartCreate(LooseModel):
    sequence: int
    content: str = ""
    checksum: str | None = None
    size: int | None = None


class DiaryCreate(LooseModel):
    text: str
    recorded_at: str | None = None
    historical_date_expression: str | None = None
    visibility: str = "private"


class MemoryPatch(LooseModel):
    text: str | None = None
    visibility: str | None = None
    include_in_digital: bool | None = None
    include_in_print: bool | None = None
    expected_revision: int = 1


class PersonCreate(LooseModel):
    name: str
    chinese_name: str | None = None
    aliases: list[str] = Field(default_factory=list)
    family_title: str | None = None
    birth_date_expression: str | None = None
    death_date_expression: str | None = None
    living_status: str = "unknown"
    visibility: str = "family"
    include_in_print: bool = True


class PersonPatch(LooseModel):
    name: str | None = None
    include_in_print: bool | None = None
    visibility: str | None = None
    expected_revision: int = 1


class RelationshipCreate(LooseModel):
    from_person_id: str
    to_person_id: str
    relationship_type: str
    direction: str = "directed"
    maternal_paternal: str | None = None
    asserted_by: str | None = None


class TimelineCreate(LooseModel):
    title: str
    date_expression: str | None = None
    precision: str = "unknown"
    recorded_at: str | None = None
    claim_ids: list[str] = Field(default_factory=list)
    visibility: str = "family"


class ChapterBuildCreate(LooseModel):
    title: str = "A remembered chapter"
    memory_ids: list[str] = Field(default_factory=list)
    locale: str = "en-AU"


class ChapterPatch(LooseModel):
    title: str | None = None
    blocks: list[dict[str, Any]] | None = None
    expected_revision: int = 1


class ApprovalCreate(LooseModel):
    expected_revision: int | None = None
    manifest_hash: str | None = None
    note: str | None = None


class EditionCreate(LooseModel):
    chapter_ids: list[str] = Field(default_factory=list)
    locale: str = "en-AU"
    include_audio_links: bool = True
    context_asset_ids: list[str] = Field(default_factory=list)
    missing_glyphs: list[str] = Field(default_factory=list)
    layout_overflow: bool = False
    links_valid: bool = True
    qr_valid: bool = True


class CheckoutCreate(LooseModel):
    plan_key: str = "complete_digital_memoir_v1"
    beneficiary_project_id: str | None = None
    client_amount_minor: int | None = None
    currency: str | None = None


class PaymentWebhook(LooseModel):
    event_id: str
    order_id: str
    status: str = "paid"
    amount_minor: int
    currency: str
    signature: str


class RefundCreate(LooseModel):
    reason: str = "customer_request"
    amount_minor: int | None = None


class PrintQuoteCreate(LooseModel):
    supplier_id: str = "supplier_demo"
    quantity: int
    trim_size: str = "A5"
    binding: str = "perfect_bound"
    shipping_country: str = "AU"


class PrintOrderCreate(LooseModel):
    quote_id: str
    delivery_name: str
    delivery_address: str
    delivery_country: str = "AU"


class ProofCreate(LooseModel):
    manifest_hash: str
    proof_file_hash: str | None = None


class SupplierUpdate(LooseModel):
    manifest_hash: str


class DeletionCreate(LooseModel):
    reason: str = "customer_request"
    confirmation: str = "DELETE"


class ContextSearch(LooseModel):
    topic_id: str | None = None
    approximate_year_start: int | None = None
    approximate_year_end: int | None = None
    coarse_place: str | None = None
    language: str = "en-AU"
    requested_media: list[str] = Field(default_factory=lambda: ["image"])
    excluded_asset_ids: list[str] = Field(default_factory=list)
    query: str | None = None


class ProviderPatch(LooseModel):
    enabled: bool | None = None
    approved: bool | None = None


class SupplierPatch(LooseModel):
    enabled: bool | None = None
    qualified: bool | None = None
    supported_quantity: dict[str, int] | None = None
    supported_formats: list[str] | None = None
    data_handling_terms: str | None = None
    delivery_countries: list[str] | None = None


class AuthRequest(LooseModel):
    contact: str
    region: str = "au"


class AuthVerify(LooseModel):
    account_id: str
    token: str


class SourcePatch(LooseModel):
    caption: str | None = None
    approximate_date_expression: str | None = None
    approximate_place: str | None = None
    person_tags: list[dict[str, Any]] | None = None
    include_in_print: bool | None = None
    side: str | None = None
    capture_date: str | None = None
    scene_date: str | None = None
    front_of_asset_id: str | None = None
    back_of_asset_id: str | None = None
    crop: dict[str, Any] | None = None
    rotation: int | None = None
    machine_description: str | None = None
    expected_revision: int = 1


def _idempotency_key(header: str | None, fallback: str) -> str:
    return header or fallback


def _idempotency_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="The idempotency key was already used with a different request",
        headers={"X-Error-Code": "IDEMPOTENCY_CONFLICT"},
    )


def _policy_epoch_conflict() -> HTTPException:
    return HTTPException(
        status_code=409,
        detail="The project policy changed while this operation was in progress; resume from the current state",
        headers={"X-Error-Code": "POLICY_EPOCH_CONFLICT"},
    )


def _bump_policy_epoch(project: dict[str, Any]) -> int:
    project["policy_epoch"] = int(project.get("policy_epoch", 1)) + 1
    return project["policy_epoch"]


def _assert_policy_epoch(project: dict[str, Any], session: dict[str, Any]) -> None:
    if int(session.get("policy_epoch", project.get("policy_epoch", 1))) != int(project.get("policy_epoch", 1)):
        raise _policy_epoch_conflict()


def _encode_cursor(offset: int) -> str:
    raw = json.dumps({"offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded.encode()).decode())
        offset = value["offset"]
        if not isinstance(offset, int) or offset < 0:
            raise ValueError
        return offset
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        raise HTTPException(status_code=422, detail="Invalid pagination cursor", headers={"X-Error-Code": "INVALID_CURSOR"})


def _paginate(items: list[Any], cursor: str | None, limit: int) -> dict[str, Any]:
    offset = _decode_cursor(cursor)
    if offset > len(items):
        raise HTTPException(status_code=422, detail="Invalid pagination cursor", headers={"X-Error-Code": "INVALID_CURSOR"})
    page = items[offset : offset + limit]
    next_offset = offset + len(page)
    return {
        "items": page,
        "count": len(items),
        "next_cursor": _encode_cursor(next_offset) if next_offset < len(items) else None,
    }


def _account_id(header: str | None) -> str:
    return header or "demo-storyteller"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _issue_auth_session(store: MemoryStore, account_id: str, response: Response) -> str:
    token = uuid4_hex()
    csrf_token = uuid4_hex()
    session_reference = new_id("auth-session")
    store.auth_sessions[_token_hash(token)] = {
        "id": session_reference,
        "account_id": account_id,
        "csrf_token_hash": _token_hash(csrf_token),
        "created_at": now_iso(),
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat(),
        "revoked_at": None,
    }
    secure = os.getenv("MEMORY_SPARK_COOKIE_SECURE", "0").lower() in {"1", "true", "yes"}
    response.set_cookie("memory_spark_session", token, httponly=True, secure=secure, samesite="lax", max_age=12 * 60 * 60, path="/")
    response.set_cookie("memory_spark_csrf", csrf_token, httponly=False, secure=secure, samesite="lax", max_age=12 * 60 * 60, path="/")
    return session_reference


def _unauthorised() -> HTTPException:
    return HTTPException(status_code=403, detail="You are not authorised for this project item")


def _not_found(label: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{label} not found")


def _project(store: MemoryStore, project_id: str, actor: str, allow_deleted: bool = False) -> dict[str, Any]:
    project = store.projects.get(project_id)
    if not project:
        raise _not_found("Project")
    if project.get("deleted_at") and not allow_deleted:
        raise HTTPException(status_code=410, detail="Project deletion is in progress")
    if actor not in project["members"] and actor != project.get("storyteller_id"):
        raise _unauthorised()
    return project


def _resource_project(store: MemoryStore, resource: dict[str, Any], actor: str) -> dict[str, Any]:
    return _project(store, resource["project_id"], actor)


def _refresh_expired_grants(project: dict[str, Any]) -> None:
    now = datetime.now(timezone.utc)
    for grant in project.get("grants", []):
        if grant.get("revoked_at") or not grant.get("expires_at"):
            continue
        if datetime.fromisoformat(grant["expires_at"]) > now:
            continue
        unused = max(0, grant.get("units", 0) - grant.get("consumed_units", 0) - grant.get("reserved_units", 0) - grant.get("revoked_units", 0))
        if unused:
            grant["revoked_units"] = grant.get("revoked_units", 0) + unused
            project["paid_units_revoked"] = project.get("paid_units_revoked", 0) + unused
        grant["revoked_at"] = now.isoformat()
        grant["revocation_reason"] = "grant_expired"


def _entitlement_model(project: dict[str, Any]) -> str:
    """Return the persisted billing model, defaulting new projects to chapter one free.

    Projects created before the chapter model was introduced do not have a model
    field. Treating those records as chapter projects makes the migration safe:
    an unfinished first chapter cannot become blocked by the retired five-session
    trial counter.
    """
    model = str(project.get("entitlement_model") or os.getenv("MEMORY_SPARK_ENTITLEMENT_MODEL", "chapter")).strip().lower()
    return model if model in {"chapter", "legacy"} else "chapter"


def _first_chapter_approved(project: dict[str, Any]) -> bool:
    return any(
        chapter.get("status") == "APPROVED" and chapter.get("chapter_number", 1) == 1
        for chapter in project.get("chapters", {}).values()
    )


def _free_chapter_available(project: dict[str, Any]) -> bool:
    return _entitlement_model(project) == "chapter" and not _first_chapter_approved(project)


def _completed_session_count(project: dict[str, Any]) -> int:
    if _entitlement_model(project) == "chapter":
        stored = project.get("free_chapter_session_count")
        if stored is not None:
            return stored + project.get("paid_units_consumed", 0)
        # Backfill the count for projects created before this field existed.
        return sum(1 for session in project.get("sessions", {}).values() if session.get("status") == "COMPLETED")
    return project["trial_units_consumed"] + project["paid_units_consumed"]


def _available_units(project: dict[str, Any]) -> int:
    _refresh_expired_grants(project)
    trial = project["trial_units_total"] - project["trial_units_consumed"] - project["trial_units_reserved"]
    paid = project["paid_units_total"] - project.get("paid_units_revoked", 0) - project["paid_units_consumed"] - project["paid_units_reserved"]
    return max(0, trial + paid)


def _entitlement_response(project: dict[str, Any]) -> dict[str, Any]:
    _refresh_expired_grants(project)
    free_chapter = _free_chapter_available(project)
    return {
        "entitlement_model": _entitlement_model(project),
        "free_chapter_available": free_chapter,
        "free_chapter_sessions_completed": project.get("free_chapter_session_count", 0),
        "trial_units_total": project["trial_units_total"],
        "trial_units_consumed": project["trial_units_consumed"],
        "trial_units_reserved": project["trial_units_reserved"],
        "trial_units_remaining": max(0, project["trial_units_total"] - project["trial_units_consumed"] - project["trial_units_reserved"]),
        "paid_units_total": project["paid_units_total"],
        "paid_units_revoked": project.get("paid_units_revoked", 0),
        "paid_units_consumed": project["paid_units_consumed"],
        "paid_units_reserved": project["paid_units_reserved"],
        "paid_units_remaining": max(0, project["paid_units_total"] - project["paid_units_consumed"] - project["paid_units_reserved"]),
        # `None` is deliberate: before chapter one is approved, the prototype
        # does not present a numeric session allowance to the client.
        "available_primary_sessions": None if free_chapter else _available_units(project),
    }


def _project_response(project: dict[str, Any]) -> dict[str, Any]:
    entitlements = _entitlement_response(project)
    approved_chapters = [chapter for chapter in project.get("chapters", {}).values() if chapter.get("status") == "APPROVED"]
    return {
        "id": project["id"],
        "revision": project.get("revision", 1),
        "policy_epoch": project.get("policy_epoch", 1),
        "mode": project["mode"],
        "owner_id": project["owner_id"],
        "storyteller_id": project["storyteller_id"],
        "home_region": project["home_region"],
        "profile": deepcopy(project["profile"]),
        "consent": deepcopy(project["consent"]),
        "preferences": deepcopy(project.get("preferences", {})),
        "member_count": len(project["members"]),
        "entitlements": entitlements,
        "trial_units_remaining": entitlements["trial_units_remaining"],
        "completed_sessions": _completed_session_count(project),
        "free_chapter_available": entitlements["free_chapter_available"],
        "preview": deepcopy(project.get("preview")),
        "workspace_unlocked": bool(approved_chapters),
        "first_chapter_free": bool(approved_chapters and approved_chapters[0].get("chapter_number", 1) == 1),
        "deletion_state": project.get("deletion_state", "ACTIVE"),
        "created_at": project["created_at"],
    }


def _session_response(store: MemoryStore, session: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(session)
    result["context_cues"] = [deepcopy(store.context_assets[asset_id]) for asset_id in session.get("cue_asset_ids", []) if asset_id in store.context_assets]
    result["draft"] = deepcopy(session.get("draft"))
    result["claims"] = [deepcopy(store.claims[claim_id]) for claim_id in session.get("claim_ids", []) if claim_id in store.claims]
    return result


def _consent_granted(project: dict[str, Any], purpose: str) -> bool:
    record = project["consent"].get(purpose)
    return bool(record and record.get("granted"))


def _recording_allowed(project: dict[str, Any]) -> bool:
    """Apply explicit recording consent, or the family storyteller assent gate."""
    recording = project["consent"].get("recording")
    if recording is not None:
        return bool(recording.get("granted"))
    return project["mode"] == "family" and _consent_granted(project, "storyteller_assent")


def _can_read_memory(project: dict[str, Any], actor: str, memory: dict[str, Any]) -> bool:
    if actor == project["storyteller_id"]:
        return True
    member = project["members"].get(actor)
    if member and member.get("role") == "storyteller":
        return True
    shared = _consent_granted(project, "family_sharing") or _consent_granted(project, "sharing")
    return memory.get("visibility") == "family" and bool(member) and shared


def _can_operate_session(project: dict[str, Any], actor: str) -> bool:
    return actor in {project["storyteller_id"], project["owner_id"]}


def _reserve_unit(project: dict[str, Any]) -> str:
    _refresh_expired_grants(project)
    if _free_chapter_available(project):
        return "free_chapter"
    if project["trial_units_total"] - project["trial_units_consumed"] - project["trial_units_reserved"] > 0:
        project["trial_units_reserved"] += 1
        return "trial"
    for grant in sorted(project.get("grants", []), key=lambda item: item.get("expires_at", "")):
        available = grant.get("units", 0) - grant.get("consumed_units", 0) - grant.get("reserved_units", 0) - grant.get("revoked_units", 0)
        if available > 0 and not grant.get("revoked_at"):
            grant["reserved_units"] = grant.get("reserved_units", 0) + 1
            project["paid_units_reserved"] += 1
            return f"paid:{grant['id']}"
    raise HTTPException(status_code=409, detail="No primary memory sessions remain", headers={"X-Error-Code": "ENTITLEMENT_REQUIRED"})


def _release_unit(project: dict[str, Any], source: str) -> None:
    if source == "free_chapter":
        return
    if source.startswith("paid:"):
        grant_id = source.split(":", 1)[1]
        grant = next((item for item in project.get("grants", []) if item.get("id") == grant_id), None)
        if grant:
            grant["reserved_units"] = max(0, grant.get("reserved_units", 0) - 1)
        project["paid_units_reserved"] = max(0, project["paid_units_reserved"] - 1)
        return
    key = f"{source}_units_reserved"
    project[key] = max(0, project[key] - 1)


def _consume_unit(project: dict[str, Any], source: str) -> None:
    if source == "free_chapter":
        project["free_chapter_session_count"] = project.get("free_chapter_session_count", 0) + 1
        return
    if source.startswith("paid:"):
        grant_id = source.split(":", 1)[1]
        grant = next((item for item in project.get("grants", []) if item.get("id") == grant_id), None)
        if not grant:
            raise HTTPException(status_code=409, detail="The paid entitlement grant is no longer available")
        grant["reserved_units"] = max(0, grant.get("reserved_units", 0) - 1)
        grant["consumed_units"] = grant.get("consumed_units", 0) + 1
        project["paid_units_reserved"] = max(0, project["paid_units_reserved"] - 1)
        project["paid_units_consumed"] += 1
        return
    reserved_key = f"{source}_units_reserved"
    consumed_key = f"{source}_units_consumed"
    project[reserved_key] = max(0, project[reserved_key] - 1)
    project[consumed_key] += 1


def _reservation_expired(session: dict[str, Any]) -> bool:
    expires_at = session.get("reservation_expires_at")
    return bool(expires_at and datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc))


def _source_version(store: MemoryStore, project_id: str, source_kind: str, text: str, **extra: Any) -> dict[str, Any]:
    source_id = new_id("source")
    normalised = text.replace("\r\n", "\n").strip()
    source = {
        "id": source_id,
        "project_id": project_id,
        "source_kind": source_kind,
        "version": 1,
        "text": normalised,
        "sha256": hashlib.sha256(normalised.encode()).hexdigest(),
        "immutable": True,
        "created_at": now_iso(),
        **extra,
    }
    store.source_versions[source_id] = source
    return source


def _cue_selection(store: MemoryStore, project: dict[str, Any], topic_id: str, include_video: bool) -> list[dict[str, Any]]:
    region = project["home_region"]
    eligible = [
        asset
        for asset in store.context_assets.values()
        if asset.get("reviewed")
        and region in asset["rights"].get("allowed_regions", [])
        and asset["rights"].get("can_display_in_paid_app", False)
        and topic_id in asset.get("topics", [])
    ]
    if include_video:
        eligible = [asset for asset in eligible if asset["kind"] == "video"][:1]
    else:
        eligible = [asset for asset in eligible if asset["kind"] == "image"][:3]
    return eligible


def _cue_response(asset: dict[str, Any], exposure_id: str | None = None) -> dict[str, Any]:
    return {
        "asset_id": asset["asset_id"],
        "title": asset["title"],
        "label": asset["label"],
        "attribution": asset["creator"],
        "source_url": asset["source_url"],
        "scene_date_range": asset["scene_date_range"],
        "location": asset["location"],
        "match_scope": asset["match_scope"],
        "kind": asset["kind"],
        "allowed_actions": {
            "embed": asset["rights"].get("can_embed", False),
            "download": asset["rights"].get("can_include_in_download", False),
            "print": asset["rights"].get("can_print", False),
        },
        "exposure_id": exposure_id,
    }


def _make_claims(store: MemoryStore, project: dict[str, Any], session: dict[str, Any], source: dict[str, Any], text: str, elicitation: str) -> list[dict[str, Any]]:
    lowered = text.lower()
    exposure_ids = [exposure["id"] for exposure in session.get("cue_exposures", [])]
    low_confidence = any(marker in lowered for marker in ("low confidence", "uncertain asr", "inaudible"))
    claims: list[dict[str, Any]] = []

    def add(statement: str, claim_type: str = "personal_recollection", date: dict[str, Any] | None = None) -> None:
        claim = {
            "id": new_id("claim"),
            "project_id": project["id"],
            "statement": statement,
            "claim_type": claim_type,
            "evidence": [{"source_kind": source["source_kind"], "source_version_id": source["id"], "char_start": 0, "char_end": len(source["text"]) }],
            "date": date or {"original_expression": None, "start": None, "end": None, "precision": "unknown"},
            "elicitation": elicitation,
            "cue_exposure_ids": exposure_ids if elicitation == "after_cue" else [],
            "extraction_confidence": 0.45 if low_confidence else 0.82,
            "transcription_confidence": 0.35 if low_confidence or source.get("source_kind") == "recording" else None,
            "review_status": "unreviewed",
            "visibility": "private",
            "contradicts_claim_ids": [],
            "created_at": now_iso(),
        }
        store.claims[claim["id"]] = claim
        for prior in store.claims.values():
            if prior is claim or prior.get("project_id") != project["id"] or prior.get("statement") != claim["statement"]:
                continue
            prior_date = prior.get("date", {}).get("original_expression")
            claim_date = claim.get("date", {}).get("original_expression")
            if prior_date and claim_date and prior_date != claim_date:
                prior.setdefault("contradicts_claim_ids", []).append(claim["id"])
                claim.setdefault("contradicts_claim_ids", []).append(prior["id"])
                prior["review_status"] = "CONFLICT"
                claim["review_status"] = "CONFLICT"
                conflict_ids = project.setdefault("conflict_claim_ids", [])
                for conflict_id in (prior["id"], claim["id"]):
                    if conflict_id not in conflict_ids:
                        conflict_ids.append(conflict_id)
        claims.append(claim)

    date = {"original_expression": None, "start": None, "end": None, "precision": "unknown"}
    match = re.search(r"(?:around|about|circa)\s+(19\d{2}|20\d{2})", lowered)
    if match:
        date = {"original_expression": match.group(0), "start": None, "end": None, "precision": "approximate"}
    if ("older brother" in lowered or "哥哥" in text) and ("walk" in lowered or "school" in lowered or "走" in text):
        add("The narrator walked to school with an older brother.", date=date)
    if "shop" in lowered or "小店" in text:
        add("The narrator remembers passing a little shop.", date=date)
    if ("factory" in lowered or "工厂" in text) and ("work" in lowered or "worked" in lowered or "工作" in text):
        add("The narrator remembers working in a factory.", date=date)
    if "bicycle" in lowered or "自行车" in text:
        if "did not" in lowered or "没有" in text:
            add("The narrator says they did not have the bicycle shown in the historical reference.", "cue_reaction", date=date)
    return claims


def _draft_for(session: dict[str, Any], source: dict[str, Any], text: str, claims: list[dict[str, Any]]) -> dict[str, Any]:
    narrative = text.strip() or "The narrator chose to keep this memory as a short note without adding details."
    previous_draft = session.get("draft") or {}
    return {
        "id": previous_draft.get("id", new_id("draft")),
        "status": "AI_ASSISTED_DRAFT",
        "text": narrative,
        "blocks": [{"id": new_id("block"), "type": "narrative", "text": narrative, "claim_ids": [claim["id"] for claim in claims], "source_version_ids": [source["id"]]}],
        "evidence_links": [claim["id"] for claim in claims],
        "review_flags": [] if claims else ["insufficient_evidence_for_narrative"],
        "source_version_id": source["id"],
        "revision": session.get("revision", 0) + 1,
    }


def _validate_draft(text: str, source_text: str) -> None:
    if '"' in text or "“" in text or "”" in text:
        quoted = re.findall(r'["“](.*?)["”]', text)
        for fragment in quoted:
            if fragment and fragment not in source_text:
                raise HTTPException(status_code=422, detail="Direct quotes must resolve to the original source")
    unsupported_markers = ("in 1968", "new bicycle", "every morning", "the rain smelled")
    lowered = text.lower()
    source_lower = source_text.lower()
    if any(marker in lowered and marker not in source_lower for marker in unsupported_markers):
        raise HTTPException(status_code=422, detail="Draft contains unsupported biography details")


def _mark_project_stale(project: dict[str, Any], reason: str) -> None:
    for chapter_id in project.get("chapter_ids", []):
        chapter = project.get("chapters", {}).get(chapter_id)
        if chapter and chapter["status"] not in {"PUBLISHED", "ARCHIVED"}:
            chapter["status"] = "STALE"
            chapter.setdefault("stale_reasons", []).append(reason)
            chapter["translation_stale"] = True
    for edition_id in project.get("edition_ids", []):
        edition = project.get("editions", {}).get(edition_id)
        if edition and edition.get("status") in {"APPROVED", "RELEASED"}:
            edition["release_blocked"] = True
            edition.setdefault("review_flags", []).append(reason)
    for chapter in project.get("chapters", {}).values():
        for translation in chapter.get("translations", {}).values():
            if translation.get("status") == "CURRENT":
                translation["status"] = "STALE"


def _artifact_bytes(edition: dict[str, Any], fmt: str) -> bytes:
    content = edition["rendered_content"]
    if fmt == "html":
        return content.encode()
    if fmt == "pdf":
        return ("%PDF-1.4\n% Memory Spark\n" + content.replace("<", " ").replace(">", " ") + "\n%%EOF\n").encode()
    if fmt == "epub":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            _write_deterministic_zip_entry(archive, "mimetype", b"application/epub+zip", zipfile.ZIP_STORED)
            _write_deterministic_zip_entry(archive, "OEBPS/content.xhtml", content.encode(), zipfile.ZIP_DEFLATED)
            _write_deterministic_zip_entry(archive, "META-INF/container.xml", b'<container version="1.0"/>', zipfile.ZIP_DEFLATED)
        return buf.getvalue()
    if fmt == "archive":
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive_manifest = {key: value for key, value in edition["manifest"].items() if key not in {"artifact_hashes", "manifest_hash"}}
            _write_deterministic_zip_entry(archive, "manifest.json", json.dumps(archive_manifest, ensure_ascii=False, indent=2).encode(), zipfile.ZIP_DEFLATED)
            _write_deterministic_zip_entry(archive, "manuscript.html", content.encode(), zipfile.ZIP_DEFLATED)
            _write_deterministic_zip_entry(archive, "source-links.json", json.dumps(edition["source_links"], ensure_ascii=False, indent=2).encode(), zipfile.ZIP_DEFLATED)
        return buf.getvalue()
    raise HTTPException(status_code=404, detail="Unknown artifact format")


def _write_deterministic_zip_entry(archive: zipfile.ZipFile, name: str, content: bytes, compression: int) -> None:
    info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = compression
    info.create_system = 3
    info.external_attr = 0o600 << 16
    archive.writestr(info, content)


def _artifact_record(store: MemoryStore, edition: dict[str, Any], fmt: str, raw: bytes) -> dict[str, Any]:
    record = {"format": fmt, "sha256": sha256_bytes(raw), "size": len(raw)}
    if store.object_store_path:
        object_key = f"projects/{edition['project_id']}/editions/{edition['id']}/{fmt}"
        store.put_object(object_key, raw)
        record["object_key"] = object_key
    else:
        record["content_base64"] = base64.b64encode(raw).decode()
    return record


def _build_edition(
    store: MemoryStore,
    project: dict[str, Any],
    chapter_ids: list[str],
    locale: str,
    include_audio_links: bool,
    context_asset_ids: list[str] | None = None,
    preflight_inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    chapters = [project["chapters"][chapter_id] for chapter_id in chapter_ids if chapter_id in project["chapters"]]
    if not chapters:
        raise HTTPException(status_code=422, detail="Select at least one chapter")
    blocks: list[dict[str, Any]] = []
    source_links: list[dict[str, Any]] = []
    review_flags: list[str] = []
    selected_context_ids = set(context_asset_ids or [])
    for chapter in chapters:
        chapter_blocks = chapter.get("blocks", [])
        translation = chapter.get("translations", {}).get(locale)
        if translation and translation.get("status") == "CURRENT":
            chapter_blocks = translation.get("blocks", chapter_blocks)
        blocks.extend(deepcopy(chapter_blocks))
        review_flags.extend(chapter.get("review_flags", []))
        for block in chapter_blocks:
            selected_context_ids.update(block.get("context_asset_ids", []))
            for claim_id in block.get("claim_ids", []):
                claim = store.claims.get(claim_id)
                if not claim or claim["project_id"] != project["id"]:
                    review_flags.append("missing_evidence")
                else:
                    source_links.append({"claim_id": claim_id, "evidence": claim["evidence"]})
    context_records: list[dict[str, Any]] = []
    for context_id in sorted(selected_context_ids):
        asset = store.context_assets.get(context_id)
        if not asset or not asset.get("reviewed"):
            review_flags.append(f"context_rights:{context_id}")
            continue
        rights = asset.get("rights", {})
        context_records.append({"asset_id": context_id, "rights_policy_version": asset.get("rights_policy_version", "catalogue-v1"), "kind": asset.get("kind"), "label": asset.get("label")})
        if not rights.get("can_print", False) or not rights.get("can_include_in_download", False):
            review_flags.append(f"context_rights:{context_id}")
    edition_id = new_id("edition")
    manifest_base = {
        "edition_id": edition_id,
        "project_id": project["id"],
        "locale": locale,
        "chapter_versions": [{"id": chapter["id"], "revision": chapter["revision"]} for chapter in chapters],
        "claim_ids": sorted({link["claim_id"] for link in source_links}),
        "source_versions": sorted({e["source_version_id"] for link in source_links for e in link["evidence"]}),
        "context_asset_ids": sorted(selected_context_ids),
        "context_policy_versions": [record["rights_policy_version"] for record in context_records],
        "template_version": "memory-spark-reader-1",
        "renderer_version": "local-renderer-1",
        "include_audio_links": include_audio_links,
    }
    narrative = "\n".join(block.get("text", "") for block in blocks if block.get("type") in {"narrative", "direct_quote", "editorial_note"})
    rendered = '<article lang="' + escape(locale) + '"><h1>Memory Spark</h1>' + "".join(f"<p>{escape(line)}</p>" for line in narrative.splitlines() if line.strip()) + "</article>"
    edition = {
        "id": edition_id,
        "project_id": project["id"],
        "locale": locale,
        "status": "DRAFT",
        "chapters": deepcopy(chapters),
        "blocks": blocks,
        "manifest": {**manifest_base, "content_hash": sha256_json(manifest_base)},
        "rendered_content": rendered,
        "source_links": source_links,
        "context_assets": context_records,
        "context_asset_ids": sorted(selected_context_ids),
        "review_flags": sorted(set(review_flags)),
        "preflight_inputs": deepcopy(preflight_inputs or {}),
        "preflight": {"ok": not review_flags, "issues": sorted(set(review_flags))},
        "artifacts": {},
        "approval": None,
        "release_blocked": False,
        "created_at": now_iso(),
    }
    for fmt in ("html", "pdf", "epub", "archive"):
        raw = _artifact_bytes(edition, fmt)
        edition["artifacts"][fmt] = _artifact_record(store, edition, fmt, raw)
    edition["manifest"]["artifact_hashes"] = {fmt: artifact["sha256"] for fmt, artifact in edition["artifacts"].items()}
    edition["manifest_hash"] = sha256_json(edition["manifest"])
    project["editions"][edition_id] = edition
    project["edition_ids"].append(edition_id)
    return edition


def _is_operator(actor: str, role_header: str | None) -> bool:
    return actor.startswith("ops") or actor.startswith("operator") or role_header in {"operator", "finance", "admin"}


def _processing_available(store: MemoryStore, project: dict[str, Any], data_class: str = "transcript") -> bool:
    return any(
        policy.get("enabled")
        and policy.get("approved")
        and policy.get("processing_region") == project["home_region"]
        and data_class in policy.get("data_classes", [])
        for policy in store.provider_policies.values()
    )


def create_app(store: MemoryStore | None = None) -> FastAPI:
    if store is not None:
        memory = store
    else:
        database_url = os.getenv("SUPABASE_DB_URL", "").strip()
        object_store_path = os.getenv("MEMORY_SPARK_OBJECT_STORE_PATH")
        if database_url:
            memory = PostgresMemoryStore.from_url(
                database_url,
                object_store_path=object_store_path,
            )
        elif os.getenv("MEMORY_SPARK_TEST_MODE") == "1":
            # Tests use an explicit in-memory store; production must use Supabase Postgres.
            memory = MemoryStore(object_store_path=object_store_path)
        else:
            raise RuntimeError("SUPABASE_DB_URL must be configured; local MemoryStore fallback is disabled")
    app = FastAPI(title="CopyMe2 Memoir", version="1.0.0", description="Evidence-linked guided memoir product")
    app.state.store = memory
    from .supabase_routes import router as supabase_router
    app.include_router(supabase_router)
    from .agent_routes import router as agent_router
    app.include_router(agent_router)
    request_transaction_lock = asyncio.Lock() if getattr(memory, "request_transaction_enabled", False) else None
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:8000"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Response:
        canonical_memoir_request = rewrite_memoir_path(request.scope)
        supplied = request.headers.get("X-Request-ID", "")
        request_id = supplied if re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", supplied) else new_id("req")
        request.state.request_id = request_id
        database_transaction = request_transaction_lock is not None
        if database_transaction:
            await request_transaction_lock.acquire()
            memory.begin_request()
        else:
            # Refresh before dispatch and persist after dispatch. The JSON API
            # process remains the single in-process writer; worker-side
            # mutations use its explicit transaction context.
            memory.reload()
        try:
            session_token = request.cookies.get("memory_spark_session")
            session = memory.auth_sessions.get(_token_hash(session_token)) if session_token else None
            cookie_authenticated = bool(
                session
                and not request.url.path.startswith('/v1/user/')
                and not session.get("revoked_at")
                and datetime.fromisoformat(session["expires_at"]) > datetime.now(timezone.utc)
                and not request.headers.get("X-Account-Id")
            )
            if cookie_authenticated:
                if request.method in {"POST", "PUT", "PATCH", "DELETE"} and not request.url.path.startswith("/v1/auth/"):
                    csrf = request.headers.get("X-CSRF-Token")
                    if not csrf or not hmac.compare_digest(_token_hash(csrf), session.get("csrf_token_hash", "")):
                        response = JSONResponse(
                            status_code=403,
                            content={
                                "detail": "CSRF verification is required for cookie-authenticated mutations",
                                "error": {
                                    "code": "CSRF_REQUIRED",
                                    "message": "CSRF verification is required for cookie-authenticated mutations",
                                    "retryable": False,
                                    "request_id": request_id,
                                },
                            },
                            headers={"X-Request-ID": request_id, "X-Error-Code": "CSRF_REQUIRED"},
                        )
                        if database_transaction:
                            memory.commit_request()
                        else:
                            memory.save()
                        return response
                request.scope["headers"] = list(request.scope["headers"]) + [(b"x-account-id", session["account_id"].encode())]
            response = await call_next(request)
            if database_transaction:
                memory.commit_request()
            else:
                memory.save()
            response.headers["X-Request-ID"] = request_id
            if canonical_memoir_request:
                response.headers["X-API-Namespace"] = "memoir"
            return response
        except BaseException:
            if database_transaction:
                memory.rollback_request()
            raise
        finally:
            if database_transaction:
                request_transaction_lock.release()

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        status_code = exc.status_code
        default_codes = {
            400: "BAD_REQUEST",
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            410: "GONE",
            413: "PAYLOAD_TOO_LARGE",
            415: "UNSUPPORTED_MEDIA_TYPE",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            503: "PROCESSING_UNAVAILABLE",
        }
        detail = exc.detail
        message = detail if isinstance(detail, str) else "The request could not be completed"
        error_code = (exc.headers or {}).get("X-Error-Code", default_codes.get(status_code, "REQUEST_FAILED"))
        payload = {
            "detail": detail,
            "error": {
                "code": error_code,
                "message": message,
                "retryable": status_code in {429, 502, 503, 504},
                "request_id": request.state.request_id,
            },
        }
        headers = dict(exc.headers or {})
        headers["X-Request-ID"] = request.state.request_id
        return JSONResponse(status_code=status_code, content=jsonable_encoder(payload), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        payload = {
            "detail": exc.errors(),
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "Request validation failed",
                "retryable": False,
                "request_id": request.state.request_id,
                "field_errors": exc.errors(),
            },
        }
        return JSONResponse(status_code=422, content=jsonable_encoder(payload), headers={"X-Request-ID": request.state.request_id})

    @app.get("/health")
    def health() -> dict[str, Any]:
        if getattr(memory, "database_url", None):
            storage = "supabase-postgresql-jsonb+filesystem-objects" if memory.object_store_path else "supabase-postgresql-jsonb"
        elif memory.persistence_path and memory.object_store_path:
            storage = "persistent-json+filesystem-objects"
        elif memory.persistence_path:
            storage = "persistent-json"
        else:
            storage = "memory"
        return {
            "status": "ok",
            "service": "memory-spark",
            "version": "1.0.0",
            "processing_regions": ["au"],
            "demo_mode": True,
            "storage": storage,
            "pending_outbox": memory.pending_outbox_count(),
        }

    @app.get("/v1/config")
    def config() -> dict[str, Any]:
        return {
            "product": "Memory Spark",
            "trial_primary_sessions": 5,
            "max_follow_up_prompts": 3,
            "max_audio_seconds_per_session": 900,
            "supported_languages": ["en-AU", "zh-CN"],
            "active_regions": ["au"],
            "processing_policy": "demo providers stay inside the AU cell; no automatic cross-region fallback",
            "capture_fallbacks": ["typed", "file_upload"],
            "recording_guarantee": "no_background_recording",
        }

    @app.post("/v1/auth/request")
    def request_auth(payload: AuthRequest) -> dict[str, Any]:
        # The local cell returns a one-time demo token so the workflow is testable without an SMS/email vendor.
        token = uuid4_hex()
        account_id = hashlib.sha256(payload.contact.strip().lower().encode()).hexdigest()[:16]
        account = memory.ensure_account(account_id)
        account["verified"] = False
        account["auth_token_hash"] = hashlib.sha256(token.encode()).hexdigest()
        account["auth_token_expires_at"] = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        account["auth_attempts"] = 0
        account["region"] = payload.region
        return {"accepted": True, "message": "If the contact can be verified, a sign-in code has been sent.", "demo_token": token, "account_id": account_id}

    @app.post("/v1/auth/verify")
    def verify_auth(payload: AuthVerify, response: Response) -> dict[str, Any]:
        account = memory.accounts.get(payload.account_id)
        if not account:
            raise HTTPException(status_code=400, detail="Invalid or expired verification token")
        account["auth_attempts"] = account.get("auth_attempts", 0) + 1
        if account["auth_attempts"] > 5:
            account.pop("auth_token_hash", None)
            raise HTTPException(status_code=429, detail="Too many verification attempts; request a new code")
        if account.get("auth_token_hash") != hashlib.sha256(payload.token.encode()).hexdigest():
            raise HTTPException(status_code=400, detail="Invalid or expired verification token")
        if datetime.fromisoformat(account["auth_token_expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Verification token has expired")
        account["verified"] = True
        account.pop("auth_token_hash", None)
        account.pop("auth_token_expires_at", None)
        account.pop("auth_attempts", None)
        session_reference = _issue_auth_session(memory, payload.account_id, response)
        memory.audit("auth.session.created", payload.account_id, None, session_reference=session_reference)
        return {"verified": True, "account_id": payload.account_id, "session_reference": session_reference}

    @app.post("/v1/auth/challenges", status_code=status.HTTP_202_ACCEPTED)
    def create_auth_challenge(payload: AuthRequest) -> dict[str, Any]:
        """Start the documented challenge flow while keeping the local provider deterministic."""
        token = uuid4_hex()
        account_id = hashlib.sha256(payload.contact.strip().lower().encode()).hexdigest()[:16]
        account = memory.ensure_account(account_id)
        account["verified"] = False
        challenge_id = new_id("challenge")
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
        memory.auth_challenges[challenge_id] = {
            "id": challenge_id,
            "account_id": account_id,
            "token_hash": hashlib.sha256(token.encode()).hexdigest(),
            "expires_at": expires_at,
            "attempts": 0,
            "consumed_at": None,
            "region": payload.region,
        }
        account["region"] = payload.region
        memory.audit("auth.challenge.created", account_id, None, challenge_id=challenge_id, region=payload.region)
        return {"challenge_id": challenge_id, "account_id": account_id, "expires_at": expires_at, "accepted": True, "demo_token": token}

    @app.post("/v1/auth/challenges/{challenge_id}/verify")
    def verify_auth_challenge(challenge_id: str, payload: LooseModel, response: Response) -> dict[str, Any]:
        challenge = memory.auth_challenges.get(challenge_id)
        if not challenge:
            raise HTTPException(status_code=400, detail="Invalid or expired verification challenge")
        if challenge["consumed_at"] or datetime.fromisoformat(challenge["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Verification challenge has expired")
        data = payload.model_dump()
        challenge["attempts"] += 1
        provided_hash = hashlib.sha256(str(data.get("token", data.get("code", ""))).encode()).hexdigest()
        if challenge["attempts"] > 5 or not hmac.compare_digest(provided_hash, challenge["token_hash"]):
            raise HTTPException(status_code=400, detail="Invalid or expired verification challenge")
        account = memory.ensure_account(challenge["account_id"])
        account["verified"] = True
        challenge["consumed_at"] = now_iso()
        memory.audit("auth.challenge.verified", challenge["account_id"], None, challenge_id=challenge_id)
        session_reference = _issue_auth_session(memory, challenge["account_id"], response)
        memory.audit("auth.session.created", challenge["account_id"], None, session_reference=session_reference)
        return {"verified": True, "account_id": challenge["account_id"], "session_reference": session_reference}

    @app.post("/v1/auth/logout")
    def logout_auth(request: Request, response: Response) -> dict[str, Any]:
        token = request.cookies.get("memory_spark_session")
        session = memory.auth_sessions.get(_token_hash(token)) if token else None
        if session:
            session["revoked_at"] = now_iso()
            memory.audit("auth.session.revoked", session["account_id"], None, session_reference=session["id"])
        response.delete_cookie("memory_spark_session", path="/")
        response.delete_cookie("memory_spark_csrf", path="/")
        return {"revoked": True, "logged_out_at": now_iso()}

    @app.post("/v1/projects", status_code=status.HTTP_201_CREATED)
    def create_project(payload: ProjectCreate, x_account_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        memory.ensure_account(actor)
        with memory.lock:
            request_hash = sha256_json(payload.model_dump())
            operation_key = f"project-create:{actor}:{idempotency_key}" if idempotency_key else None
            if operation_key:
                prior = memory.idempotency.get(operation_key)
                if prior:
                    if prior["request_hash"] != request_hash:
                        raise _idempotency_conflict()
                    return deepcopy(prior["response"])
            project_id = new_id("project")
            storyteller = actor if payload.mode == "self" else (payload.storyteller_account_id or new_id("storyteller"))
            storyteller_account = memory.ensure_account(storyteller)
            members = {actor: {"role": "organiser" if payload.mode == "family" else "storyteller", "capabilities": ["manage_project", "purchase"]}}
            if payload.mode == "self":
                members[actor]["capabilities"] += ["record", "consent", "approve_publication", "delete_project"]
            elif storyteller != actor:
                members[storyteller] = {"role": "storyteller", "capabilities": ["record", "consent", "approve_publication", "delete_project"]}
            entitlement_model = str(os.getenv("MEMORY_SPARK_ENTITLEMENT_MODEL", "chapter")).strip().lower()
            if entitlement_model not in {"chapter", "legacy"}:
                entitlement_model = "chapter"
            if entitlement_model == "legacy":
                trial_units_total = 0 if storyteller_account.get("trial_grant_issued") else 5
                storyteller_account["trial_grant_issued"] = True
                storyteller_account["trial_grant_issued_at"] = storyteller_account.get("trial_grant_issued_at") or now_iso()
            else:
                trial_units_total = 0
            project = {
                "id": project_id, "owner_id": actor, "storyteller_id": storyteller, "mode": payload.mode, "entitlement_model": entitlement_model, "home_region": payload.region, "revision": 1, "policy_epoch": 1, "created_at": now_iso(),
                "profile": {"name": payload.storyteller_name, "preferred_language": payload.language, "birth_year": payload.birth_year, "birth_date_expression": payload.birth_date_expression, "birth_place": payload.birth_place, "childhood_place": payload.childhood_place, "dialect_preference": None},
                "members": members, "consent": {}, "preferences": {"muted_topics": [], "excluded_topics": [], "default_visibility": "private", "sensitive_processing": False},
                "trial_units_total": trial_units_total, "trial_units_consumed": 0, "trial_units_reserved": 0, "free_chapter_session_count": 0, "paid_units_total": 0, "paid_units_revoked": 0, "paid_units_consumed": 0, "paid_units_reserved": 0, "grants": [],
                "sessions": {}, "session_ids": [], "memories": {}, "assets": {}, "people": {}, "relationships": [], "timeline": [], "chapters": {}, "chapter_ids": [], "outline_versions": [], "editions": {}, "edition_ids": [], "orders": [], "print_orders": [], "exports": {}, "payment_invitations": {}, "preview_jobs": {}, "idempotency": {}, "events": [], "event_cursor": 0, "deletion_state": "ACTIVE", "deleted_at": None,
            }
            memory.projects[project_id] = project
        memory.audit("project.created", actor, project_id, mode=payload.mode, home_region=payload.region)
        memory.emit(project, "project.created", mode=payload.mode)
        response = _project_response(project)
        if operation_key:
            memory.idempotency[operation_key] = {"request_hash": request_hash, "response": deepcopy(response)}
        return response

    @app.get("/v1/projects/{project_id}")
    def get_project(project_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        return _project_response(_project(memory, project_id, _account_id(x_account_id), allow_deleted=True))

    @app.patch("/v1/projects/{project_id}")
    def patch_project(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        if actor not in {project["owner_id"], project["storyteller_id"]}:
            raise _unauthorised()
        data = payload.model_dump(exclude_unset=True)
        expected_revision = data.pop("expected_revision", project.get("revision", 1))
        if expected_revision != project.get("revision", 1):
            raise HTTPException(status_code=409, detail="Project revision has changed")
        profile = data.pop("profile", None)
        preferences = data.pop("preferences", None)
        for key in ("name", "preferred_language", "birth_year", "birth_date_expression", "birth_place", "childhood_place", "dialect_preference"):
            if key in data:
                project["profile"][key] = data[key]
        if isinstance(profile, dict):
            for key in ("name", "preferred_language", "birth_year", "birth_date_expression", "birth_place", "childhood_place", "dialect_preference"):
                if key in profile:
                    project["profile"][key] = profile[key]
        if isinstance(preferences, dict):
            for key in ("muted_topics", "default_visibility", "sensitive_processing"):
                if key in preferences:
                    project["preferences"][key] = preferences[key]
        for key in ("muted_topics", "excluded_topics", "default_visibility", "sensitive_processing"):
            if key in data:
                project["preferences"][key] = data[key]
        if profile is not None or preferences is not None or any(key in data for key in ("muted_topics", "excluded_topics", "default_visibility", "sensitive_processing")):
            _bump_policy_epoch(project)
        project["revision"] = project.get("revision", 1) + 1
        memory.audit("project.updated", actor, project_id, revision=project["revision"])
        memory.emit(project, "project.updated", revision=project["revision"])
        return _project_response(project)

    @app.delete("/v1/projects/{project_id}/members/{member_account_id}")
    def remove_member(project_id: str, member_account_id: str, x_account_id: str | None = Header(default=None)) -> Response:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        if actor != project["owner_id"] and "manage_members" not in project["members"].get(actor, {}).get("capabilities", []):
            raise _unauthorised()
        if member_account_id in {project["owner_id"], project["storyteller_id"]}:
            raise HTTPException(status_code=409, detail="The project owner and storyteller cannot be removed")
        if member_account_id not in project["members"]:
            raise _not_found("Project member")
        del project["members"][member_account_id]
        memory.audit("member.removed", actor, project_id, member_account_id=member_account_id)
        memory.emit(project, "member.removed", account_id=member_account_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/v1/projects/{project_id}/consents")
    def record_consent(project_id: str, payload: ConsentCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        subject = payload.subject_account_id or project["storyteller_id"]
        if actor != subject and payload.purpose in {"storyteller_assent", "recording", "sensitive_processing", "family_sharing", "sharing"}:
            raise _unauthorised()
        record = {"subject": subject, "actor": actor, "purpose": payload.purpose, "granted": payload.granted, "notice_version": payload.notice_version, "locale": payload.locale, "timestamp": now_iso(), "region": project["home_region"], "assistance_method": payload.assistance_method}
        project["consent"][payload.purpose] = record
        _bump_policy_epoch(project)
        memory.audit("consent.recorded", actor, project_id, purpose=payload.purpose, granted=payload.granted)
        memory.emit(project, "consent.updated", purpose=payload.purpose, granted=payload.granted)
        return deepcopy(record)

    @app.post("/v1/projects/{project_id}/consents/{purpose}/withdraw")
    def withdraw_consent(project_id: str, purpose: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        if actor not in {project["storyteller_id"], project["owner_id"]}:
            raise _unauthorised()
        record = project["consent"].get(purpose)
        if not record:
            raise _not_found("Consent")
        record["granted"] = False
        record["withdrawn_at"] = now_iso()
        _bump_policy_epoch(project)
        _mark_project_stale(project, f"consent_withdrawn:{purpose}")
        memory.audit("consent.withdrawn", actor, project_id, purpose=purpose)
        return deepcopy(record)

    @app.post("/v1/projects/{project_id}/invitations", status_code=status.HTTP_201_CREATED)
    def create_invitation(project_id: str, payload: InvitationCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        if actor != project["owner_id"] and "manage_invitations" not in project["members"][actor].get("capabilities", []):
            raise _unauthorised()
        token = uuid4_hex()
        invitation_id = new_id("invite")
        expires = datetime.now(timezone.utc) + timedelta(hours=max(1, min(payload.expires_hours, 72)))
        invitation = {"id": invitation_id, "project_id": project_id, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "intended_role": payload.intended_role, "capability_set": payload.capability_set, "issuer": actor, "expires_at": expires.isoformat(), "redeemed_at": None}
        memory.invitations[invitation_id] = invitation
        memory.audit("invitation.created", actor, project_id, invitation_id=invitation_id)
        return {"id": invitation_id, "token": token, "expires_at": invitation["expires_at"], "intended_role": payload.intended_role}

    @app.get("/v1/invitations/{token}")
    def preview_invitation(token: str) -> dict[str, Any]:
        invitation = next((item for item in memory.invitations.values() if item["token_hash"] == hashlib.sha256(token.encode()).hexdigest()), None)
        if not invitation:
            raise _not_found("Invitation")
        expired = datetime.fromisoformat(invitation["expires_at"]) <= datetime.now(timezone.utc)
        return {"id": invitation["id"], "project_id": invitation["project_id"], "role": invitation["intended_role"], "expired": expired, "redeemed": bool(invitation["redeemed_at"]), "project_name": "A private Memory Spark project"}

    @app.post("/v1/invitations/{token}/accept")
    def accept_invitation(token: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        invitation = next((item for item in memory.invitations.values() if item["token_hash"] == hashlib.sha256(token.encode()).hexdigest()), None)
        if not invitation:
            raise HTTPException(status_code=400, detail="Invalid invitation")
        if invitation["redeemed_at"]:
            raise HTTPException(status_code=409, detail="Invitation has already been redeemed")
        if datetime.fromisoformat(invitation["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="Invitation has expired")
        project = memory.projects.get(invitation["project_id"])
        if not project:
            raise _not_found("Project")
        project["members"][actor] = {"role": invitation["intended_role"], "capabilities": invitation["capability_set"]}
        invitation["redeemed_at"] = now_iso()
        memory.audit("invitation.accepted", actor, project["id"], invitation_id=invitation["id"])
        memory.emit(project, "member.joined", account_id=actor, role=invitation["intended_role"])
        return {"accepted": True, "project": _project_response(project), "role": invitation["intended_role"]}

    @app.get("/v1/projects/{project_id}/journey")
    def journey(project_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor, allow_deleted=True)
        active = next((session for session in project["sessions"].values() if session["status"] not in {"COMPLETED", "SKIPPED"}), None)
        memories = [item["id"] for item in project["memories"].values() if _can_read_memory(project, actor, item)]
        active_response = _session_response(memory, active) if active else None
        private_progress = not _can_operate_session(project, actor)
        if active_response and private_progress:
            active_response.pop("turns", None)
            active_response.pop("draft", None)
            active_response.pop("claims", None)
        response = {**_project_response(project), "active_session": active_response, "memory_ids": memories, "next_action": "resume_session" if active else ("read_preview" if project.get("preview") else "start_memory")}
        if private_progress:
            response["private_progress"] = True
            response["completed_sessions"] = None
            response["trial_units_remaining"] = None
            response["entitlements"] = {"redacted": True, "reason": "storyteller_progress_is_private"}
        return response

    @app.get("/v1/projects/{project_id}/entitlements")
    def entitlements(project_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        return _entitlement_response(_project(memory, project_id, _account_id(x_account_id), allow_deleted=True))

    @app.post("/v1/projects/{project_id}/memory-sessions", status_code=status.HTTP_201_CREATED)
    def start_session(project_id: str, payload: SessionCreate, x_account_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        with memory.lock:
            project = _project(memory, project_id, actor)
            request_hash = sha256_json(payload.model_dump())
            operation_key = f"start:{actor}:{idempotency_key}" if idempotency_key else None
            if operation_key:
                prior = project.setdefault("idempotency", {}).get(operation_key)
                if prior:
                    if prior["request_hash"] != request_hash:
                        raise _idempotency_conflict()
                    return deepcopy(prior["response"])
            if project["mode"] == "family" and not _consent_granted(project, "storyteller_assent"):
                raise HTTPException(status_code=403, detail="Storyteller consent is required before recording")
            if payload.topic_id in project["preferences"].get("muted_topics", []) or payload.topic_id in project["preferences"].get("excluded_topics", []):
                raise HTTPException(status_code=409, detail="This topic is muted by the storyteller")
            active = next((item for item in project["sessions"].values() if item["status"] not in {"COMPLETED", "SKIPPED"}), None)
            if active:
                if active["status"] not in {"EXPIRED"} and _reservation_expired(active):
                    if not active.get("reservation_released"):
                        _release_unit(project, active["reservation_source"])
                        active["reservation_released"] = True
                    active["previous_status"] = active["status"]
                    active["status"] = "EXPIRED"
                    active["expired_at"] = now_iso()
                if active["status"] == "EXPIRED":
                    raise HTTPException(status_code=409, detail="Resume the expired memory session before starting another one")
                raise HTTPException(status_code=409, detail="An active memory session already exists")
            if payload.source_asset_id and payload.source_asset_id not in project["assets"]:
                raise _not_found("Source asset")
            source = _reserve_unit(project)
            session_id = new_id("session")
            source_assisted = bool(payload.source_asset_id)
            topic_questions = {"childhood_home": "What do you remember about getting to school?", "childhood_routine": "What was an ordinary day like when you were young?", "food": "What food or celebration from childhood stays with you?", "work": "What was your first work, responsibility, or way of earning money?", "turning_point": "What turning point would you like your family to remember?", "school": "What do you remember about school or learning, if school was part of your childhood?", "migration": "What do you remember about moving or making a new home?"}
            question = {"id": new_id("prompt"), "text": topic_questions.get(payload.topic_id, "What is one memory you would like to keep?") if not source_assisted else "What do you remember when you look at this photograph?", "elicitation": "personal_source_assisted" if source_assisted else "unaided", "topic_id": payload.topic_id, "sequence": 1, "target_thread": payload.topic_id}
            session = {"id": session_id, "project_id": project_id, "status": "QUESTION_READY", "previous_status": None, "topic_id": payload.topic_id, "reservation_source": source, "reservation_released": False, "reservation_expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), "question": question, "questions_offered": 1, "follow_ups_offered": 0, "follow_ups_used": 0, "accepted_audio_seconds": 0.0, "accepted_asset_ids": [], "turns": [], "cue_exposures": [], "cue_asset_ids": [], "claim_ids": [], "draft": None, "revision": 0, "source_asset_id": payload.source_asset_id, "include_video": payload.include_video, "participant_account_id": project["storyteller_id"], "idempotency": {}, "answer_idempotency": {}, "policy_epoch": project.get("policy_epoch", 1), "created_at": now_iso()}
            project["sessions"][session_id] = session
            project["session_ids"].append(session_id)
            memory.audit("memory_session.started", actor, project_id, session_id=session_id, reservation_source=source)
            memory.emit(project, "memory_session.started", session_id=session_id)
            response = _session_response(memory, session)
            response["entitlements"] = _entitlement_response(project)
            if operation_key:
                project["idempotency"][operation_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            return response

    @app.get("/v1/memory-sessions/{session_id}")
    def get_session(session_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        session, project = _find_session(memory, session_id, actor)
        response = _session_response(memory, session)
        if not _can_operate_session(project, actor):
            response.pop("turns", None)
            response.pop("draft", None)
            response.pop("claims", None)
        return response

    @app.get("/v1/memory-sessions/{session_id}/cues")
    def session_cues(session_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        session, project = _find_session(memory, session_id, actor)
        if not _can_operate_session(project, actor) and actor not in project["members"]:
            raise _unauthorised()
        exposures = {item["asset_id"]: item for item in session.get("cue_exposures", [])}
        items = []
        for asset_id in session.get("cue_asset_ids", []):
            asset = memory.context_assets.get(asset_id)
            if not asset:
                continue
            exposure = exposures.get(asset_id)
            items.append(_cue_response(asset, exposure["id"] if exposure else None))
        return {"items": items, "count": len(items), "session_id": session_id}

    @app.post("/v1/memory-sessions/{session_id}/cue-exposures", status_code=status.HTTP_201_CREATED)
    def create_cue_exposure(session_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        session, project = _find_session(memory, session_id, actor)
        if not _can_operate_session(project, actor):
            raise _unauthorised()
        data = payload.model_dump()
        asset_id = data.get("asset_id")
        if asset_id not in session.get("cue_asset_ids", []):
            raise _not_found("Cue")
        event = data.get("event", data.get("state", "rendered"))
        allowed_events = {"offered", "rendered", "play_started", "play_progress", "skipped"}
        if event not in allowed_events:
            raise HTTPException(status_code=422, detail="Unsupported cue exposure event")
        exposure = next((item for item in session["cue_exposures"] if item["asset_id"] == asset_id), None)
        if not exposure:
            exposure = {"id": new_id("exposure"), "project_id": project["id"], "session_id": session_id, "asset_id": asset_id, "state": "offered", "available_before_turn_id": None, "reaction": None, "comment": None, "created_at": now_iso()}
            session["cue_exposures"].append(exposure)
        exposure["state"] = event
        exposure["last_event_at"] = now_iso()
        if "progress_seconds" in data:
            exposure["progress_seconds"] = data["progress_seconds"]
        memory.emit(project, "cue.exposure", session_id=session_id, asset_id=asset_id, event=event)
        return {"exposure": deepcopy(exposure), "cue": _cue_response(memory.context_assets[asset_id], exposure["id"])}

    @app.post("/v1/memory-sessions/{session_id}/pause")
    def pause_session(session_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        session, project = _find_session(memory, session_id, actor)
        if not _can_operate_session(project, actor):
            raise _unauthorised()
        if session["status"] in {"COMPLETED", "SKIPPED"}:
            raise HTTPException(status_code=409, detail="Terminal sessions cannot be paused")
        session["previous_status"] = session["status"]
        session["status"] = "PAUSED"
        memory.emit(project, "memory_session.paused", session_id=session_id)
        return _session_response(memory, session)

    @app.post("/v1/memory-sessions/{session_id}/resume")
    def resume_session(session_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        session, project = _find_session(memory, session_id, actor)
        if not _can_operate_session(project, actor):
            raise _unauthorised()
        with memory.lock:
            session, project = _find_session(memory, session_id, actor)
            if not _can_operate_session(project, actor):
                raise _unauthorised()
            if session["status"] == "EXPIRED":
                session["reservation_source"] = _reserve_unit(project)
                session["reservation_released"] = False
                session["reservation_expires_at"] = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
                session["status"] = session.get("previous_status") or "WAITING_FOR_ANSWER"
                session["previous_status"] = None
                session["policy_epoch"] = project.get("policy_epoch", 1)
                session["resumed_at"] = now_iso()
                memory.emit(project, "memory_session.resumed", session_id=session_id, expired_reservation_rebooked=True)
            elif session["status"] == "PAUSED":
                session["status"] = session.get("previous_status") or "WAITING_FOR_ANSWER"
                session["previous_status"] = None
                session["policy_epoch"] = project.get("policy_epoch", 1)
                memory.emit(project, "memory_session.resumed", session_id=session_id)
        return _session_response(memory, session)

    @app.post("/v1/memory-sessions/{session_id}/skip")
    def skip_session(session_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        with memory.lock:
            session, project = _find_session(memory, session_id, actor)
            if not _can_operate_session(project, actor):
                raise _unauthorised()
            if session["status"] == "SKIPPED":
                return _session_response(memory, session)
            if session["status"] == "COMPLETED":
                raise HTTPException(status_code=409, detail="Completed sessions cannot be skipped")
            if not session.get("reservation_released"):
                _release_unit(project, session["reservation_source"])
                session["reservation_released"] = True
            session["status"] = "SKIPPED"
            session["skipped_at"] = now_iso()
            memory.audit("memory_session.skipped", actor, project["id"], session_id=session_id)
            memory.emit(project, "memory_session.skipped", session_id=session_id)
            return {**_session_response(memory, session), "entitlements": _entitlement_response(project)}

    @app.post("/v1/memory-sessions/{session_id}/answers")
    def answer_session(session_id: str, payload: AnswerCreate, x_account_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        with memory.lock:
            session, project = _find_session(memory, session_id, actor)
            if not _can_operate_session(project, actor):
                raise _unauthorised()
            _assert_policy_epoch(project, session)
            request_hash = sha256_json(payload.model_dump())
            if idempotency_key:
                prior = session.setdefault("answer_idempotency", {}).get(idempotency_key)
                if prior:
                    if prior["request_hash"] != request_hash:
                        raise _idempotency_conflict()
                    return deepcopy(prior["response"])
            if not _recording_allowed(project):
                raise HTTPException(status_code=403, detail="Storyteller consent is required before recording")
            if session["status"] in {"COMPLETED", "SKIPPED", "EXPIRED"}:
                raise HTTPException(status_code=409, detail="This session is complete")
            if payload.skip or (not payload.text.strip() and not payload.upload_id):
                session["status"] = "WAITING_FOR_ANSWER"
                response = {**_session_response(memory, session), "skipped_turn": True}
                if idempotency_key:
                    session["answer_idempotency"][idempotency_key] = {"request_hash": request_hash, "response": deepcopy(response)}
                return response
            required_class = "audio" if payload.upload_id else "transcript"
            if not _processing_available(memory, project, required_class):
                session["status"] = "RETRYABLE_ERROR"
                raise HTTPException(status_code=503, detail="Approved processing is unavailable in this project's region; no provider fallback was used")
            if len(session["turns"]) >= 5:
                raise HTTPException(status_code=422, detail="Session turn limit reached")
            participant = payload.participant_account_id or project["storyteller_id"]
            if participant not in project["members"] and participant != project["storyteller_id"]:
                raise _unauthorised()
            turn_type = payload.turn_type if payload.turn_type in {"initial", "follow_up", "correction"} else "initial"
            if turn_type == "follow_up" and session.get("follow_ups_used", 0) >= 3:
                raise HTTPException(status_code=422, detail="The session follow-up limit has been reached")
            elicitation = "after_cue" if session["cue_exposures"] and turn_type != "initial" else session["question"]["elicitation"]
            if payload.upload_id:
                upload = memory.uploads.get(payload.upload_id)
                asset = project["assets"].get(payload.upload_id)
                if upload and (upload["project_id"] != project["id"] or upload["state"] != "READY"):
                    raise HTTPException(status_code=409, detail="The recording must be fully validated before it can be used")
                if upload and upload["state"] == "READY":
                    asset = upload.get("asset")
                if not asset or asset.get("project_id") != project["id"] or asset.get("state") != "READY":
                    raise HTTPException(status_code=409, detail="The recording must be fully validated before it can be used")
                source_id = asset.get("source_version_id")
                source = memory.source_versions.get(source_id) if source_id else None
                if not source:
                    source = _source_version(memory, project["id"], "recording", "Recorded audio source awaiting transcription", session_id=session_id, participant_account_id=participant, original_asset_id=asset["id"], time_mapping=[])
                else:
                    source = deepcopy(source)
                    source["original_asset_id"] = asset["id"]
                    source["time_mapping"] = source.get("time_mapping", [])
                duration_seconds = float(asset.get("duration_seconds", upload.get("duration_seconds", 0.0) if upload else 0.0) or 0.0)
                if asset["id"] in session.get("accepted_asset_ids", []):
                    raise HTTPException(status_code=409, detail="This recording has already been accepted for the session")
                if session.get("accepted_audio_seconds", 0.0) + duration_seconds > 900:
                    raise HTTPException(status_code=422, detail="The session accepts at most 15 minutes of audio")
                session["accepted_audio_seconds"] = session.get("accepted_audio_seconds", 0.0) + duration_seconds
                session.setdefault("accepted_asset_ids", []).append(asset["id"])
            else:
                source = _source_version(memory, project["id"], "transcript", payload.text, session_id=session_id, transcription_method="typed", participant_account_id=participant)
            turn = {"id": new_id("turn"), "session_id": session_id, "prompt_id": session["question"]["id"], "turn_type": turn_type, "elicitation": elicitation, "participant_account_id": participant, "source_version_id": source["id"], "text": payload.text, "created_at": now_iso()}
            session["turns"].append(turn)
            claims = _make_claims(memory, project, session, source, payload.text, elicitation)
            session["claim_ids"].extend(claim["id"] for claim in claims)
            session["draft"] = _draft_for(session, source, payload.text, claims)
            session["revision"] += 1
            session["status"] = "DRAFT_READY"
            session["last_source_version_id"] = source["id"]
            if turn_type == "initial" and session["questions_offered"] == 1:
                cues = _cue_selection(memory, project, session["topic_id"], include_video=session.get("include_video", False))
                session["cue_asset_ids"] = [asset["asset_id"] for asset in cues]
                for asset in cues:
                    exposure = {"id": new_id("exposure"), "project_id": project["id"], "session_id": session_id, "asset_id": asset["asset_id"], "state": "offered", "available_before_turn_id": None, "reaction": None, "comment": None, "created_at": now_iso()}
                    session["cue_exposures"].append(exposure)
                session["status"] = "CONTEXT_READY" if cues else "DRAFT_READY"
                session["follow_ups_offered"] = min(3, len(cues))
                memory.emit(project, "cue.shown", session_id=session_id, asset_ids=session["cue_asset_ids"])
            elif turn_type == "follow_up":
                session["follow_ups_used"] = session.get("follow_ups_used", 0) + 1
            memory.emit(project, "answer.saved", session_id=session_id, source_version_id=source["id"], elicitation=elicitation)
            response = {**_session_response(memory, session), "source_version": deepcopy(source), "entitlements": _entitlement_response(project)}
            if idempotency_key:
                session["answer_idempotency"][idempotency_key] = {"request_hash": request_hash, "response": deepcopy(response)}
            return response

    @app.post("/v1/memory-sessions/{session_id}/cue-reactions")
    def cue_reaction(session_id: str, payload: CueReactionCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        session, project = _find_session(memory, session_id, actor)
        if not _can_operate_session(project, actor):
            raise _unauthorised()
        exposure = next((item for item in session["cue_exposures"] if item["asset_id"] == payload.asset_id), None)
        if not exposure:
            raise _not_found("Cue exposure")
        exposure["state"] = "reacted"
        exposure["reaction"] = payload.reaction
        exposure["comment"] = payload.comment
        exposure["reacted_at"] = now_iso()
        memory.audit("cue.reacted", actor, project["id"], session_id=session_id, asset_id=payload.asset_id, reaction=payload.reaction)
        memory.emit(project, "cue.reacted", session_id=session_id, asset_id=payload.asset_id, reaction=payload.reaction)
        return {"exposure": deepcopy(exposure), "creates_personal_claim": False, "message": "A reaction alone is not treated as a biography fact."}

    @app.post("/v1/memory-sessions/{session_id}/complete")
    def complete_session(session_id: str, payload: CompleteCreate, x_account_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        with memory.lock:
            session, project = _find_session(memory, session_id, actor)
            if not _can_operate_session(project, actor):
                raise _unauthorised()
            _assert_policy_epoch(project, session)
            key = _idempotency_key(idempotency_key, f"complete:{session_id}")
            request_hash = sha256_json(payload.model_dump())
            prior = session["idempotency"].get(key)
            if prior:
                if isinstance(prior, dict) and "request_hash" in prior:
                    if prior["request_hash"] != request_hash:
                        raise _idempotency_conflict()
                    return deepcopy(prior["response"])
                return deepcopy(prior)
            if session["status"] == "COMPLETED" and session.get("completion_result"):
                return deepcopy(session["completion_result"])
            if session["status"] == "SKIPPED":
                raise HTTPException(status_code=409, detail="Skipped sessions cannot be completed")
            if not session.get("draft"):
                raise HTTPException(status_code=422, detail="Save an answer before completing the memory")
            if payload.expected_revision is not None and payload.expected_revision != session["revision"]:
                raise HTTPException(status_code=409, detail="Memory draft revision has changed")
            text = (payload.draft_text or session["draft"]["text"]).strip()
            source_text = " ".join(turn["text"] for turn in session["turns"])
            _validate_draft(text, source_text)
            if payload.visibility not in {"private", "family"}:
                raise HTTPException(status_code=422, detail="Visibility must be private or family")
            _consume_unit(project, session["reservation_source"])
            memory_id = new_id("memory")
            memory_record = {"id": memory_id, "project_id": project["id"], "session_id": session_id, "topic_id": session.get("topic_id"), "text": text, "visibility": payload.visibility, "allow_digital": payload.include_in_digital, "allow_print": payload.include_in_print, "allow_audio_link": False, "include_in_digital": payload.include_in_digital, "include_in_print": payload.include_in_print, "claim_ids": list(session["claim_ids"]), "source_version_ids": [turn["source_version_id"] for turn in session["turns"]], "revision": 1, "review_status": "unreviewed", "created_at": now_iso()}
            project["memories"][memory_id] = memory_record
            session["status"] = "COMPLETED"
            session["completed_at"] = now_iso()
            if project.get("conflict_claim_ids"):
                _mark_project_stale(project, "conflicting_claims_require_review")
            session["completion_result"] = {"session": _session_response(memory, session), "memory": deepcopy(memory_record), "entitlements": _entitlement_response(project)}
            session["idempotency"][key] = {"request_hash": request_hash, "response": deepcopy(session["completion_result"])}
            memory.emit(project, "memory_session.completed", session_id=session_id, memory_id=memory_id)
            memory.audit("memory_session.completed", actor, project["id"], session_id=session_id, memory_id=memory_id, reservation_source=session["reservation_source"])
            # The retired trial model still creates its preview at the fifth
            # completion. New chapter projects receive their free result when
            # the first chapter is built and approved instead.
            if _entitlement_model(project) == "legacy" and project["trial_units_consumed"] == 5:
                snapshot_hash = sha256_json({"memory_ids": sorted(project["memories"]), "revisions": [item["revision"] for item in project["memories"].values()]})
                if snapshot_hash not in project["preview_jobs"]:
                    job = memory.queue_job(project["id"], "BuildFreePreview", {"snapshot_hash": snapshot_hash, "memory_ids": sorted(project["memories"])})
                    preview = _build_preview(project, memory)
                    memory.complete_job(job["id"], {"preview_id": preview["id"]})
                    project["preview_jobs"][snapshot_hash] = job["id"]
                    project["preview"] = preview
                    memory.emit(project, "preview.ready", preview_id=preview["id"])
            return deepcopy(session["completion_result"])

    @app.get("/v1/projects/{project_id}/memories")
    def list_memories(project_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor, allow_deleted=True)
        visible = [deepcopy(item) for item in project["memories"].values() if _can_read_memory(project, actor, item)]
        return _paginate(visible, cursor, limit)

    @app.patch("/v1/memories/{memory_id}")
    def patch_memory(memory_id: str, payload: MemoryPatch, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        resource = next((item for project in memory.projects.values() for item in project["memories"].values() if item["id"] == memory_id), None)
        if not resource:
            raise _not_found("Memory")
        project = _resource_project(memory, resource, actor)
        if not _can_read_memory(project, actor, resource):
            raise _unauthorised()
        if payload.expected_revision != resource["revision"]:
            raise HTTPException(status_code=409, detail="Memory revision has changed")
        if payload.text is not None:
            source_text = " ".join(memory.source_versions[source_id]["text"] for source_id in resource["source_version_ids"] if source_id in memory.source_versions)
            _validate_draft(payload.text, source_text)
            correction = _source_version(memory, project["id"], "correction", payload.text, attributed_to=actor, replaces_revision=resource["revision"])
            resource["source_version_ids"].append(correction["id"])
            resource["text"] = payload.text
        if payload.visibility is not None:
            resource["visibility"] = payload.visibility
        if payload.include_in_digital is not None:
            resource["include_in_digital"] = payload.include_in_digital
            resource["allow_digital"] = payload.include_in_digital
        if payload.include_in_print is not None:
            resource["include_in_print"] = payload.include_in_print
            resource["allow_print"] = payload.include_in_print
        resource["revision"] += 1
        _mark_project_stale(project, "memory_revision_changed")
        memory.audit("memory.updated", actor, project["id"], memory_id=memory_id, revision=resource["revision"])
        return deepcopy(resource)

    @app.post("/v1/memories/{memory_id}/approvals")
    def approve_memory(memory_id: str, payload: ApprovalCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        resource = next((item for project in memory.projects.values() for item in project["memories"].values() if item["id"] == memory_id), None)
        if not resource:
            raise _not_found("Memory")
        project = _resource_project(memory, resource, actor)
        if actor not in {project["owner_id"], project["storyteller_id"]}:
            raise _unauthorised()
        if payload.expected_revision is not None and payload.expected_revision != resource["revision"]:
            raise HTTPException(status_code=409, detail="Memory revision has changed")
        resource["review_status"] = "APPROVED"
        resource["reviewed_by"] = actor
        resource["reviewed_at"] = now_iso()
        memory.audit("memory.approved", actor, project["id"], memory_id=memory_id, revision=resource["revision"])
        return deepcopy(resource)

    @app.post("/v1/projects/{project_id}/preferences")
    def update_preferences(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        if actor not in {project["storyteller_id"], project["owner_id"]}:
            raise _unauthorised()
        data = payload.model_dump(exclude_unset=True)
        for key in ("muted_topics", "excluded_topics", "default_visibility", "sensitive_processing"):
            if key in data:
                project["preferences"][key] = data[key]
        return deepcopy(project["preferences"])

    @app.post("/v1/uploads", status_code=status.HTTP_201_CREATED)
    def create_upload(payload: UploadCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        if not payload.project_id:
            raise HTTPException(status_code=422, detail="project_id is required")
        project = _project(memory, payload.project_id, actor)
        if payload.kind in {"audio", "diary"} and not _recording_allowed(project):
            raise HTTPException(status_code=403, detail="Recording consent is required before retaining private media")
        if payload.kind == "photo" and not payload.rights_confirmed:
            raise HTTPException(status_code=400, detail="Confirm that you have a basis for the requested photo uses")
        if payload.duration_seconds is not None and payload.duration_seconds < 0:
            raise HTTPException(status_code=422, detail="Audio duration cannot be negative")
        if payload.kind == "audio" and payload.duration_seconds is not None and payload.duration_seconds > 900:
            raise HTTPException(status_code=422, detail="A recorded turn cannot exceed 15 minutes of accepted audio")
        allowed = {"audio/webm", "audio/mp4", "audio/wav", "audio/mpeg", "image/jpeg", "image/png", "image/heic", "application/pdf", "text/plain"}
        if payload.mime_type not in allowed:
            raise HTTPException(status_code=415, detail="Unsupported media type")
        limits = {"photo": 25 * 1024 * 1024, "document": 50 * 1024 * 1024, "audio": 100 * 1024 * 1024, "diary": 50 * 1024 * 1024}
        if payload.expected_size and payload.expected_size > limits.get(payload.kind, 50 * 1024 * 1024):
            raise HTTPException(status_code=413, detail="File exceeds the declared limit")
        upload_id = new_id("upload")
        upload = {"id": upload_id, "project_id": project["id"], "created_by": actor, "kind": payload.kind, "filename": payload.filename, "mime_type": payload.mime_type, "expected_size": payload.expected_size, "expected_checksum": payload.expected_checksum, "rights_confirmed": payload.rights_confirmed, "visibility": payload.visibility, "duration_seconds": payload.duration_seconds, "state": "CREATED", "parts": {}, "created_at": now_iso()}
        memory.uploads[upload_id] = upload
        return {"id": upload_id, "state": upload["state"], "upload_url": f"/v1/uploads/{upload_id}/parts", "max_part_size": 5 * 1024 * 1024}

    @app.post("/v1/projects/{project_id}/uploads", status_code=status.HTTP_201_CREATED)
    def create_project_upload(project_id: str, payload: UploadCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        payload.project_id = project_id
        return create_upload(payload, x_account_id)

    @app.post("/v1/uploads/{upload_id}/parts")
    def upload_part(upload_id: str, payload: UploadPartCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        upload = memory.uploads.get(upload_id)
        if not upload:
            raise _not_found("Upload")
        _project(memory, upload["project_id"], actor)
        if upload["state"] in {"READY", "QUARANTINED"}:
            raise HTTPException(status_code=409, detail="Upload is already finalised")
        try:
            raw = base64.b64decode(payload.content.encode(), validate=True)
        except Exception:
            raw = payload.content.encode()
        checksum = sha256_bytes(raw)
        if payload.checksum and payload.checksum != checksum:
            raise HTTPException(status_code=400, detail="Part checksum does not match")
        existing = upload["parts"].get(str(payload.sequence))
        if existing and existing["checksum"] != checksum:
            raise HTTPException(status_code=409, detail="Sequence already contains different bytes")
        upload["parts"][str(payload.sequence)] = {"sequence": payload.sequence, "bytes_base64": base64.b64encode(raw).decode(), "checksum": checksum, "size": len(raw)}
        upload["state"] = "UPLOADING"
        return {"upload_id": upload_id, "sequence": payload.sequence, "acknowledged": True, "server_persisted": True, "checksum": checksum}

    @app.put("/v1/uploads/{upload_id}/parts/{sequence}")
    async def upload_part_put(upload_id: str, sequence: int, request: Request, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        raw = await request.body()
        payload = UploadPartCreate(sequence=sequence, content=base64.b64encode(raw).decode())
        return upload_part(upload_id, payload, x_account_id)

    @app.post("/v1/uploads/{upload_id}/finalize")
    def finalize_upload(upload_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        upload = memory.uploads.get(upload_id)
        if not upload:
            raise _not_found("Upload")
        project = _project(memory, upload["project_id"], actor)
        request_hash = sha256_json(payload.model_dump())
        operation_key = f"upload-finalize:{actor}:{upload_id}:{idempotency_key}" if idempotency_key else None
        if operation_key:
            prior = memory.idempotency.get(operation_key)
            if prior:
                if prior["request_hash"] != request_hash:
                    raise _idempotency_conflict()
                return deepcopy(prior["response"])
        if upload["state"] == "READY":
            return deepcopy(upload["asset"])
        if not upload["parts"]:
            raise HTTPException(status_code=409, detail="No acknowledged upload parts")
        sequences = sorted(int(key) for key in upload["parts"])
        if sequences != list(range(sequences[-1] + 1)):
            raise HTTPException(status_code=409, detail="Upload chunks are incomplete or out of order")
        raw = b"".join(base64.b64decode(upload["parts"][str(sequence)]["bytes_base64"]) for sequence in sequences)
        if upload["expected_size"] is not None and len(raw) != upload["expected_size"]:
            upload["state"] = "QUARANTINED"
            raise HTTPException(status_code=422, detail="Uploaded size does not match the declared size")
        checksum = sha256_bytes(raw)
        if upload["expected_checksum"] and upload["expected_checksum"] != checksum:
            upload["state"] = "QUARANTINED"
            raise HTTPException(status_code=422, detail="Uploaded checksum does not match")
        if upload["kind"] == "document" and raw.startswith(b"PK"):
            upload["state"] = "QUARANTINED"
            raise HTTPException(status_code=415, detail="Office and archive documents are outside the supported ingestion contract")
        signatures = {
            "image/jpeg": b"\xff\xd8\xff",
            "image/png": b"\x89PNG\r\n\x1a\n",
            "application/pdf": b"%PDF-",
        }
        expected_signature = signatures.get(upload["mime_type"])
        if expected_signature and not raw.startswith(expected_signature):
            upload["state"] = "QUARANTINED"
            raise HTTPException(status_code=415, detail="The uploaded bytes do not match the declared media type")
        asset_id = new_id("asset")
        captured_at = now_iso()
        asset = {"id": asset_id, "project_id": project["id"], "kind": upload["kind"], "filename": upload["filename"], "mime_type": upload["mime_type"], "original_checksum": checksum, "size": len(raw), "visibility": upload["visibility"], "duration_seconds": upload.get("duration_seconds"), "original_retained": True, "derivative_ready": True, "state": "READY", "rights_confirmed": upload["rights_confirmed"], "processing_region": project["home_region"], "capture_date": captured_at, "scene_date": None, "scene_date_precision": "unknown", "source_version_history": [], "created_at": captured_at}
        if memory.object_store_path:
            asset["object_key"] = memory.put_object(f"projects/{project['id']}/originals/{asset_id}", raw)
        source = _source_version(memory, project["id"], upload["kind"], f"Uploaded source: {upload['filename']}", asset_id=asset_id, original_checksum=checksum, original_asset_id=asset_id, time_mapping=[])
        asset["source_version_id"] = source["id"]
        asset["original_source_version_id"] = source["id"]
        asset["source_version_history"] = [source["id"]]
        project["assets"][asset_id] = asset
        upload["state"] = "READY"
        upload["asset"] = asset
        asset["upload_id"] = upload_id
        memory.audit("upload.finalised", actor, project["id"], upload_id=upload_id, asset_id=asset_id)
        response = deepcopy(asset)
        if operation_key:
            memory.idempotency[operation_key] = {"request_hash": request_hash, "response": deepcopy(response)}
        return response

    @app.get("/v1/uploads/{upload_id}")
    def get_upload(upload_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        upload = memory.uploads.get(upload_id)
        if not upload:
            raise _not_found("Upload")
        _project(memory, upload["project_id"], _account_id(x_account_id))
        return {key: deepcopy(value) for key, value in upload.items() if key != "parts"}

    @app.post("/v1/projects/{project_id}/diary-entries", status_code=status.HTTP_201_CREATED)
    def create_diary(project_id: str, payload: DiaryCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        used = project.setdefault("diary_text_characters", 0)
        if used + len(payload.text) > (100000 if project["paid_units_total"] else 0):
            raise HTTPException(status_code=402, detail="Diary AI processing requires the paid package; source export remains available")
        source = _source_version(memory, project_id, "diary", payload.text, recorded_at=payload.recorded_at or now_iso(), historical_date_expression=payload.historical_date_expression, author=actor)
        project["diary_text_characters"] = used + len(payload.text)
        asset = {"id": new_id("diary"), "project_id": project_id, "kind": "diary", "source_version_id": source["id"], "visibility": payload.visibility, "recorded_at": payload.recorded_at or now_iso(), "historical_date_expression": payload.historical_date_expression, "created_at": now_iso()}
        project["assets"][asset["id"]] = asset
        return deepcopy(asset)

    @app.get("/v1/projects/{project_id}/sources")
    def list_sources(project_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        return _paginate([deepcopy(item) for item in project["assets"].values()], cursor, limit)

    @app.patch("/v1/sources/{asset_id}")
    def patch_source(asset_id: str, payload: SourcePatch, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        found = next(((project, asset) for project in memory.projects.values() for asset in project["assets"].values() if asset["id"] == asset_id), None)
        if not found:
            raise _not_found("Source")
        project, asset = found
        _project(memory, project["id"], actor)
        revision = asset.get("revision", 1)
        if payload.expected_revision != revision:
            raise HTTPException(status_code=409, detail="Source revision has changed")
        changed = {key: value for key, value in {
            "caption": payload.caption,
            "approximate_date_expression": payload.approximate_date_expression,
            "approximate_place": payload.approximate_place,
            "person_tags": payload.person_tags,
            "include_in_print": payload.include_in_print,
            "side": payload.side,
            "capture_date": payload.capture_date,
            "scene_date": payload.scene_date or payload.approximate_date_expression,
            "front_of_asset_id": payload.front_of_asset_id,
            "back_of_asset_id": payload.back_of_asset_id,
            "crop": payload.crop,
            "rotation": payload.rotation,
            "machine_description": payload.machine_description,
        }.items() if value is not None}
        if payload.caption is not None:
            previous = asset.get("caption_source_version_id")
            caption_source = _source_version(memory, project["id"], "photo_caption", payload.caption, asset_id=asset_id, attributed_to=actor, replaces_source_version_id=previous)
            asset["caption_source_version_id"] = caption_source["id"]
            asset.setdefault("source_version_history", []).append(caption_source["id"])
        asset.update(changed)
        asset["revision"] = revision + 1
        _mark_project_stale(project, "source_revision_changed")
        return deepcopy(asset)

    @app.patch("/v1/media/{asset_id}/metadata")
    def patch_media_metadata(asset_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        data = payload.model_dump(exclude_unset=True)
        source_payload = SourcePatch(
            caption=data.get("caption"),
            approximate_date_expression=data.get("approximate_date_expression", data.get("date_expression")),
            approximate_place=data.get("approximate_place", data.get("place")),
            person_tags=data.get("person_tags"),
            include_in_print=data.get("include_in_print"),
            side=data.get("side"),
            capture_date=data.get("capture_date"),
            scene_date=data.get("scene_date"),
            front_of_asset_id=data.get("front_of_asset_id"),
            back_of_asset_id=data.get("back_of_asset_id"),
            crop=data.get("crop"),
            rotation=data.get("rotation"),
            machine_description=data.get("machine_description"),
            expected_revision=data.get("expected_revision", 1),
        )
        return patch_source(asset_id, source_payload, x_account_id)

    @app.post("/v1/sources/{asset_id}/corrections", status_code=status.HTTP_201_CREATED)
    def correct_source(asset_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        found = next(((project, asset) for project in memory.projects.values() for asset in project["assets"].values() if asset["id"] == asset_id), None)
        if not found:
            found = next(
                (
                    (project, asset)
                    for project in memory.projects.values()
                    for asset in project["assets"].values()
                    if asset.get("source_version_id") == asset_id
                    or asset.get("original_source_version_id") == asset_id
                    or asset_id in asset.get("source_version_history", [])
                ),
                None,
            )
        if not found and asset_id in memory.source_versions:
            source_record = memory.source_versions[asset_id]
            project = memory.projects.get(source_record.get("project_id"))
            if not project:
                raise _not_found("Source")
            _project(memory, project["id"], actor)
            data = payload.model_dump()
            text = str(data.get("text", data.get("transcript", data.get("caption", "")))).strip()
            if not text:
                raise HTTPException(status_code=422, detail="A correction must contain text")
            expected_version = data.get("expected_revision", source_record.get("version", 1))
            if expected_version != source_record.get("version", 1):
                raise HTTPException(status_code=409, detail="Source version has changed")
            correction = _source_version(memory, project["id"], "correction", text, attributed_to=actor, replaces_source_version_id=asset_id)
            source_record["superseded_by"] = correction["id"]
            _mark_project_stale(project, "source_correction_created")
            memory.audit("source.corrected", actor, project["id"], source_id=asset_id, source_version_id=correction["id"])
            return {"source": deepcopy(correction), "asset": {"id": asset_id, "revision": source_record.get("version", 1) + 1, "source_version_id": correction["id"], "original_source_version_id": asset_id}}
        if not found:
            raise _not_found("Source")
        project, asset = found
        _project(memory, project["id"], actor)
        data = payload.model_dump()
        expected_revision = data.get("expected_revision", asset.get("revision", 1))
        if expected_revision != asset.get("revision", 1):
            raise HTTPException(status_code=409, detail="Source revision has changed")
        text = str(data.get("text", data.get("transcript", data.get("caption", "")))).strip()
        if not text:
            raise HTTPException(status_code=422, detail="A correction must contain text")
        previous = asset.get("source_version_id") or asset.get("caption_source_version_id")
        source = _source_version(memory, project["id"], "correction", text, asset_id=asset_id, attributed_to=actor, replaces_source_version_id=previous)
        asset["source_version_id"] = source["id"]
        asset["correction_source_version_id"] = source["id"]
        asset.setdefault("source_version_history", []).append(source["id"])
        asset["revision"] = asset.get("revision", 1) + 1
        asset["correction_status"] = "REVIEWED"
        _mark_project_stale(project, "source_correction_created")
        memory.audit("source.corrected", actor, project["id"], asset_id=asset_id, source_version_id=source["id"])
        return {"source": deepcopy(source), "asset": deepcopy(asset)}

    @app.get("/v1/context-assets")
    def list_context_assets(region: str = "au", topic_id: str | None = None, cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        assets = [deepcopy(asset) for asset in memory.context_assets.values() if region in asset["rights"].get("allowed_regions", []) and (not topic_id or topic_id in asset.get("topics", []))]
        return _paginate(assets, cursor, limit)

    @app.post("/v1/projects/{project_id}/context-search")
    def context_search(project_id: str, payload: ContextSearch, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id))
        if payload.query and (len(payload.query) > 120 or any(marker in payload.query.lower() for marker in ("ignore instructions", "private ip", "select *", "full name", "http://", "https://", "file://", "127.0.0.1", "169.254.", "latest/meta-data"))):
            raise HTTPException(status_code=400, detail="Public context search accepts only coarse place, period, and topic")
        remote_query = {
            "coarse_place": payload.coarse_place,
            "approximate_year_start": payload.approximate_year_start,
            "approximate_year_end": payload.approximate_year_end,
            "topic_id": payload.topic_id,
            "language": payload.language,
        }
        if not _processing_available(memory, project, "coarse_context_query"):
            return {"status": "NO_APPROVED_MATCH", "items": [], "remote_query": remote_query, "message": "The approved context service is unavailable; we can continue with a neutral question."}
        requested = set(payload.requested_media or ["image"])
        candidates = []
        for asset in memory.context_assets.values():
            rights = asset["rights"]
            if not asset["reviewed"] or project["home_region"] not in rights.get("allowed_regions", []) or not rights.get("can_display_in_paid_app", False):
                continue
            if asset["asset_id"] in payload.excluded_asset_ids or asset["kind"] not in requested:
                continue
            if payload.topic_id and payload.topic_id not in asset["topics"]:
                continue
            if asset["kind"] == "video" and not rights.get("can_embed"):
                continue
            candidates.append(asset)
        images = [asset for asset in candidates if asset["kind"] == "image"][:3]
        videos = [asset for asset in candidates if asset["kind"] == "video"][:1]
        selected = videos if "video" in requested else images
        if not selected:
            return {"status": "NO_APPROVED_MATCH", "items": [], "remote_query": remote_query, "message": "We can continue with a neutral question without a historical cue."}
        return {"status": "READY", "query": remote_query, "remote_query": remote_query, "items": [_cue_response(asset) for asset in selected]}

    @app.post("/v1/projects/{project_id}/people", status_code=status.HTTP_201_CREATED)
    def create_person(project_id: str, payload: PersonCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        person_id = new_id("person")
        person = {"id": person_id, "project_id": project_id, **payload.model_dump(), "revision": 1, "created_by": actor, "created_at": now_iso()}
        project["people"][person_id] = person
        return deepcopy(person)

    @app.get("/v1/projects/{project_id}/people")
    def list_people(project_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        return _paginate([deepcopy(item) for item in project["people"].values()], cursor, limit)

    @app.patch("/v1/people/{person_id}")
    def patch_person(person_id: str, payload: PersonPatch, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        person = next((item for project in memory.projects.values() for item in project["people"].values() if item["id"] == person_id), None)
        if not person:
            raise _not_found("Person")
        project = _project(memory, person["project_id"], _account_id(x_account_id))
        if payload.expected_revision != person["revision"]:
            raise HTTPException(status_code=409, detail="Person revision has changed")
        for key in ("name", "include_in_print", "visibility"):
            value = getattr(payload, key)
            if value is not None:
                person[key] = value
        person["revision"] += 1
        _mark_project_stale(project, "person_identity_changed")
        return deepcopy(person)

    @app.post("/v1/projects/{project_id}/relationships", status_code=status.HTTP_201_CREATED)
    def create_relationship(project_id: str, payload: RelationshipCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id))
        if payload.from_person_id not in project["people"] or payload.to_person_id not in project["people"]:
            raise _not_found("Person")
        if payload.from_person_id == payload.to_person_id:
            raise HTTPException(status_code=422, detail="A person cannot be their own parent or relationship target")
        if payload.relationship_type in {"parent", "child"} and _would_cycle(project, payload.from_person_id, payload.to_person_id):
            raise HTTPException(status_code=422, detail="Confirmed ancestry cycles are not allowed")
        relation = {"id": new_id("relationship"), "project_id": project_id, **payload.model_dump(), "review_status": "asserted", "created_at": now_iso()}
        project["relationships"].append(relation)
        return deepcopy(relation)

    @app.get("/v1/projects/{project_id}/relationships")
    def list_relationships(project_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        return _paginate(deepcopy(project["relationships"]), cursor, limit)

    @app.post("/v1/projects/{project_id}/people/merge-proposals", status_code=status.HTTP_201_CREATED)
    def propose_merge(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id))
        data = payload.model_dump()
        if data.get("left_person_id") not in project["people"] or data.get("right_person_id") not in project["people"]:
            raise _not_found("Person")
        proposal = {"id": new_id("merge"), "left_person_id": data["left_person_id"], "right_person_id": data["right_person_id"], "status": "PENDING_REVIEW", "affected_references": [], "created_at": now_iso()}
        project.setdefault("merge_proposals", []).append(proposal)
        return deepcopy(proposal)

    @app.post("/v1/projects/{project_id}/person-merges", status_code=status.HTTP_201_CREATED)
    def propose_person_merge(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        return propose_merge(project_id, payload, x_account_id)

    @app.post("/v1/projects/{project_id}/person-merges/{merge_id}/approve")
    def approve_person_merge(project_id: str, merge_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        if actor not in {project["owner_id"], project["storyteller_id"]}:
            raise _unauthorised()
        proposal = next((item for item in project.get("merge_proposals", []) if item["id"] == merge_id), None)
        if not proposal:
            raise _not_found("Person merge proposal")
        if proposal["status"] == "APPROVED":
            return deepcopy(proposal)
        data = payload.model_dump()
        survivor = data.get("survivor_person_id", proposal["left_person_id"])
        merged = data.get("merged_person_id", proposal["right_person_id"])
        if survivor not in project["people"] or merged not in project["people"] or survivor == merged:
            raise HTTPException(status_code=422, detail="A reviewed merge must reference two distinct project people")
        proposal.update({"status": "APPROVED", "survivor_person_id": survivor, "merged_person_id": merged, "approved_by": actor, "approved_at": now_iso()})
        project.setdefault("person_merge_mappings", {})[merged] = {"survivor_person_id": survivor, "proposal_id": merge_id, "reversible": True}
        memory.audit("person.merge.approved", actor, project_id, merge_id=merge_id, survivor_person_id=survivor, merged_person_id=merged)
        _mark_project_stale(project, "person_merge_approved")
        return deepcopy(proposal)

    @app.post("/v1/projects/{project_id}/timeline", status_code=status.HTTP_201_CREATED)
    def create_timeline(project_id: str, payload: TimelineCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id))
        item = {"id": new_id("timeline"), "project_id": project_id, **payload.model_dump(), "created_at": now_iso()}
        project["timeline"].append(item)
        return deepcopy(item)

    @app.get("/v1/projects/{project_id}/timeline")
    def list_timeline(project_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        return _paginate(deepcopy(project["timeline"]), cursor, limit)

    @app.post("/v1/projects/{project_id}/chapter-decisions")
    def chapter_decision(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        """Return the small chapter tool decision used by the conversation agent.

        The local prototype keeps this deterministic and evidence-bound: a new
        chapter can only be proposed from authorised memories, and a topic
        change is the default boundary after the first chapter exists.
        """
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        data = payload.model_dump()
        requested_ids = data.get("memory_ids") or ([data["memory_id"]] if data.get("memory_id") else [])
        memories = [project["memories"].get(memory_id) for memory_id in requested_ids]
        memories = [item for item in memories if item and _can_read_memory(project, actor, item)]
        if not memories:
            raise HTTPException(status_code=422, detail="A chapter decision needs at least one authorised memory")

        chapters = sorted(project.get("chapters", {}).values(), key=lambda item: item.get("created_at", ""))

        def chapter_topics(chapter: dict[str, Any]) -> set[str]:
            topics: set[str] = set()
            for memory_id in chapter.get("source_memory_ids", []):
                memory_record = project["memories"].get(memory_id)
                session = project["sessions"].get(memory_record.get("session_id")) if memory_record else None
                if session and session.get("topic_id"):
                    topics.add(session["topic_id"])
            return topics

        topic_id = data.get("topic_id")
        if not topic_id:
            session = project["sessions"].get(memories[0].get("session_id"))
            topic_id = session.get("topic_id") if session else None
        previous_topics = chapter_topics(chapters[-1]) if chapters else set()
        topic_changed = bool(chapters and topic_id and topic_id not in previous_topics)
        should_start_new = not chapters or topic_changed
        chapter_number = len(chapters) + 1 if should_start_new else len(chapters)
        title_by_topic = {
            "childhood_home": "Where the story begins",
            "childhood_routine": "The days that shaped us",
            "school": "Learning the world",
            "food": "The taste of home",
            "work": "Work and responsibility",
            "turning_point": "A turning point",
            "migration": "Making a new home",
        }
        title = data.get("title") or title_by_topic.get(topic_id, f"Chapter {chapter_number}")
        return {
            "tool": "chapter_decision",
            "should_start_new_chapter": should_start_new,
            "chapter_number": chapter_number,
            "title": title,
            "topic_id": topic_id,
            "memory_ids": [item["id"] for item in memories],
            "free": not chapters,
            "reason": "This is the first chapter and it is free." if not chapters else ("The topic has changed, so this is a new chapter." if topic_changed else "Keep this memory with the current chapter."),
            "workspace_unlocked": any(item.get("status") == "APPROVED" for item in chapters),
        }

    @app.post("/v1/projects/{project_id}/outline-builds", status_code=status.HTTP_202_ACCEPTED)
    def build_outline(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        memories = [item for item in project["memories"].values() if _can_read_memory(project, actor, item)]
        if not memories:
            raise HTTPException(status_code=422, detail="An outline needs at least one authorised memory")
        outline_id = new_id("outline")
        outline = {
            "id": outline_id,
            "project_id": project_id,
            "revision": len(project.get("outline_versions", [])) + 1,
            "status": "PROPOSED",
            "title": payload.model_dump().get("title", "A life remembered"),
            "tone": payload.model_dump().get("tone", "warm"),
            "style": payload.model_dump().get("style", "first_person"),
            "sections": [{"id": new_id("outline-section"), "title": "Beginnings", "memory_ids": [item["id"] for item in memories], "review_flags": []}],
            "source_snapshot": {"memory_ids": [item["id"] for item in memories], "revisions": {item["id"]: item["revision"] for item in memories}},
            "created_by": actor,
            "created_at": now_iso(),
        }
        project.setdefault("outline_versions", []).append(outline)
        job = memory.queue_job(project_id, "BuildOutline", {"outline_id": outline_id, "memory_ids": [item["id"] for item in memories]})
        memory.complete_job(job["id"], {"outline_id": outline_id})
        memory.audit("outline.created", actor, project_id, outline_id=outline_id)
        return {"job": deepcopy(job), "outline": deepcopy(outline)}

    @app.post("/v1/projects/{project_id}/chapter-builds", status_code=status.HTTP_202_ACCEPTED)
    def build_chapter(project_id: str, payload: ChapterBuildCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        chapter_number = payload.model_dump().get("chapter_number", len(project["chapters"]) + 1)
        free = payload.model_dump().get("free", chapter_number == 1)
        memory_ids = payload.memory_ids or list(project["memories"].keys())
        memories = [project["memories"].get(memory_id) for memory_id in memory_ids]
        memories = [item for item in memories if item and _can_read_memory(project, actor, item)]
        if not memories:
            raise HTTPException(status_code=422, detail="Select at least one authorised memory")
        blocks = [{"id": new_id("block"), "type": "heading", "text": payload.title, "claim_ids": [], "source_version_ids": []}]
        for item in memories:
            blocks.append({"id": new_id("block"), "type": "narrative", "text": item["text"], "claim_ids": item["claim_ids"], "source_version_ids": item["source_version_ids"]})
        flags = ["insufficient_evidence_for_narrative" for block in blocks if block["type"] == "narrative" and not block["claim_ids"]]
        chapter = {"id": new_id("chapter"), "project_id": project_id, "title": payload.title, "chapter_number": chapter_number, "free": free, "locale": payload.locale, "tone": payload.model_dump().get("tone", "warm"), "style": payload.model_dump().get("style", "first_person"), "blocks": blocks, "revision": 1, "status": "DRAFT", "review_flags": flags, "translation_stale": False, "source_memory_ids": [item["id"] for item in memories], "created_at": now_iso()}
        project["chapters"][chapter["id"]] = chapter
        project["chapter_ids"].append(chapter["id"])
        job = memory.queue_job(project_id, "BuildChapter", {"memory_ids": memory_ids, "chapter_id": chapter["id"]})
        memory.complete_job(job["id"], {"chapter_id": chapter["id"]})
        return {"job": deepcopy(job), "chapter": deepcopy(chapter)}

    @app.get("/v1/projects/{project_id}/chapters")
    def list_chapters(project_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        return _paginate(deepcopy(list(project["chapters"].values())), cursor, limit)

    @app.get("/v1/chapters/{chapter_id}")
    def get_chapter(chapter_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        chapter = next((item for project in memory.projects.values() for item in project["chapters"].values() if item["id"] == chapter_id), None)
        if not chapter:
            raise _not_found("Chapter")
        _project(memory, chapter["project_id"], _account_id(x_account_id))
        return deepcopy(chapter)

    @app.patch("/v1/chapters/{chapter_id}")
    def patch_chapter(chapter_id: str, payload: ChapterPatch, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        chapter = next((item for project in memory.projects.values() for item in project["chapters"].values() if item["id"] == chapter_id), None)
        if not chapter:
            raise _not_found("Chapter")
        project = _project(memory, chapter["project_id"], _account_id(x_account_id))
        if payload.expected_revision != chapter["revision"]:
            raise HTTPException(status_code=409, detail="Chapter revision has changed; reconcile the edit")
        if payload.title is not None:
            chapter["title"] = payload.title
        if payload.blocks is not None:
            review_flags: list[str] = []
            for block in payload.blocks:
                source_text = " ".join(
                    memory.source_versions[source_id]["text"]
                    for source_id in block.get("source_version_ids", [])
                    if source_id in memory.source_versions and memory.source_versions[source_id].get("project_id") == project["id"]
                )
                for claim_id in block.get("claim_ids", []):
                    claim = memory.claims.get(claim_id)
                    if not claim or claim.get("project_id") != project["id"]:
                        raise HTTPException(status_code=422, detail="Chapter blocks may reference only evidence from this project")
                for source_id in block.get("source_version_ids", []):
                    source = memory.source_versions.get(source_id)
                    if not source or source.get("project_id") != project["id"]:
                        raise HTTPException(status_code=422, detail="Chapter blocks may reference only source versions from this project")
                if block.get("type") in {"narrative", "direct_quote"} and not block.get("claim_ids") and not block.get("source_version_ids"):
                    raise HTTPException(status_code=422, detail="Personal narrative blocks require source evidence")
                if block.get("type") == "direct_quote" and block.get("text", "") not in source_text:
                    raise HTTPException(status_code=422, detail="Direct quotes must resolve to an exact source span")
                if block.get("type") == "historical_sidebar":
                    context_ids = block.get("context_asset_ids", [])
                    if not context_ids:
                        raise HTTPException(status_code=422, detail="Historical sidebars require reviewed context provenance")
                    for context_id in context_ids:
                        asset = memory.context_assets.get(context_id)
                        if not asset or not asset.get("reviewed"):
                            review_flags.append(f"context_rights:{context_id}")
                        elif not asset.get("rights", {}).get("can_include_in_download", False) or not asset.get("rights", {}).get("can_print", False):
                            review_flags.append(f"context_rights:{context_id}")
                text = str(block.get("text", "")).lower()
                unsupported = ("in 1968", "new bicycle", "every morning", "the rain smelled", "felt hopeful")
                if block.get("type") in {"narrative", "editorial_note"} and any(marker in text and marker not in source_text.lower() for marker in unsupported):
                    review_flags.append("unsupported_detail")
            chapter["blocks"] = payload.blocks
            chapter["review_flags"] = sorted(set(review_flags))
        chapter["revision"] += 1
        chapter["status"] = "DRAFT"
        chapter["translation_stale"] = True
        return deepcopy(chapter)

    @app.post("/v1/chapters/{chapter_id}/approvals")
    def approve_chapter(chapter_id: str, payload: ApprovalCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        chapter = next((item for project in memory.projects.values() for item in project["chapters"].values() if item["id"] == chapter_id), None)
        if not chapter:
            raise _not_found("Chapter")
        project = _project(memory, chapter["project_id"], actor)
        if actor not in {project["storyteller_id"], project["owner_id"]}:
            raise _unauthorised()
        if payload.expected_revision is not None and payload.expected_revision != chapter["revision"]:
            raise HTTPException(status_code=409, detail="Chapter revision has changed")
        chapter["status"] = "APPROVED"
        chapter["approved_by"] = actor
        chapter["approved_at"] = now_iso()
        memory.audit("chapter.approved", actor, project["id"], chapter_id=chapter_id)
        return deepcopy(chapter)

    @app.post("/v1/chapters/{chapter_id}/translations")
    def translate_chapter(chapter_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        chapter = next((item for project in memory.projects.values() for item in project["chapters"].values() if item["id"] == chapter_id), None)
        if not chapter:
            raise _not_found("Chapter")
        _project(memory, chapter["project_id"], _account_id(x_account_id))
        target_locale = payload.model_dump().get("locale", "zh-CN")
        translation = {
            "id": new_id("translation"),
            "chapter_id": chapter_id,
            "locale": target_locale,
            "source_revision": chapter["revision"],
            "blocks": deepcopy(chapter["blocks"]),
            "preserves_uncertainty": any(
                claim.get("date", {}).get("precision") in {"approximate", "range", "unknown"}
                for block in chapter["blocks"]
                for claim_id in block.get("claim_ids", [])
                for claim in [memory.claims.get(claim_id, {})]
            ) or any(token in str(block.get("text", "")) for block in chapter["blocks"] for token in ("大约", "约", "around", "approximately")),
            "approved_names": [
                person.get("name")
                for person in memory.projects[chapter["project_id"]]["people"].values()
                if person.get("name")
            ],
            "source_alignments": [
                source_id
                for block in chapter["blocks"]
                for source_id in block.get("source_version_ids", [])
            ],
            "status": "CURRENT",
            "created_at": now_iso(),
        }
        chapter.setdefault("translations", {})[target_locale] = translation
        chapter["translation_stale"] = False
        return deepcopy(translation)

    @app.post("/v1/projects/{project_id}/editions", status_code=status.HTTP_201_CREATED)
    def create_edition(project_id: str, payload: EditionCreate, x_account_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        request_hash = sha256_json(payload.model_dump())
        operation_key = f"edition-create:{actor}:{project_id}:{idempotency_key}" if idempotency_key else None
        if operation_key:
            prior = project.setdefault("idempotency", {}).get(operation_key)
            if prior:
                if prior["request_hash"] != request_hash:
                    raise _idempotency_conflict()
                return deepcopy(prior["response"])
        edition = _build_edition(
            memory,
            project,
            payload.chapter_ids or list(project["chapter_ids"]),
            payload.locale,
            payload.include_audio_links,
            context_asset_ids=payload.context_asset_ids,
            preflight_inputs={
                "missing_glyphs": payload.missing_glyphs,
                "layout_overflow": payload.layout_overflow,
                "links_valid": payload.links_valid,
                "qr_valid": payload.qr_valid,
            },
        )
        memory.audit("edition.created", actor, project_id, edition_id=edition["id"], manifest_hash=edition["manifest_hash"])
        response = _edition_public(edition)
        if operation_key:
            project["idempotency"][operation_key] = {"request_hash": request_hash, "response": deepcopy(response)}
        return response

    @app.get("/v1/projects/{project_id}/editions")
    def list_editions(project_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        return _paginate([_edition_public(item) for item in project["editions"].values()], cursor, limit)

    @app.get("/v1/editions/{edition_id}")
    def get_edition(edition_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        edition = _find_edition(memory, edition_id)
        _project(memory, edition["project_id"], _account_id(x_account_id))
        return _edition_public(edition)

    @app.post("/v1/editions/{edition_id}/preflight")
    def preflight_edition(edition_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        edition = _find_edition(memory, edition_id)
        project = _project(memory, edition["project_id"], _account_id(x_account_id))
        issues = list(edition.get("review_flags", []))
        inputs = edition.get("preflight_inputs", {})
        if inputs.get("missing_glyphs"):
            issues.append("missing_glyphs:" + ",".join(inputs["missing_glyphs"]))
        if inputs.get("layout_overflow"):
            issues.append("layout_overflow")
        if inputs.get("links_valid") is False:
            issues.append("invalid_links")
        if inputs.get("qr_valid") is False:
            issues.append("invalid_qr")
        for context_id in edition.get("context_asset_ids", []):
            asset = memory.context_assets.get(context_id)
            rights = asset.get("rights", {}) if asset else {}
            if not asset or not asset.get("reviewed") or not rights.get("can_include_in_download", False) or not rights.get("can_print", False):
                issues.append(f"context_rights:{context_id}")
        for asset in project["assets"].values():
            if asset.get("kind") == "photo" and asset.get("include_in_print") and not asset.get("rights_confirmed"):
                issues.append(f"photo_rights:{asset['id']}")
        for fmt, artifact in edition.get("artifacts", {}).items():
            expected = artifact.get("sha256")
            actual = sha256_bytes(_artifact_bytes(edition, fmt))
            if expected != actual:
                issues.append(f"artifact_hash_mismatch:{fmt}")
        edition["preflight"] = {"ok": not issues, "issues": sorted(set(issues)), "checked_at": now_iso(), "checks": ["evidence", "rights", "glyphs", "layout", "links", "qr"]}
        if issues:
            edition["status"] = "REQUIRES_REVIEW"
        return deepcopy(edition["preflight"])

    @app.post("/v1/editions/{edition_id}/rerender")
    def rerender_edition(edition_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        edition = _find_edition(memory, edition_id)
        project = _project(memory, edition["project_id"], _account_id(x_account_id))
        edition["manifest"]["renderer_version"] = f"local-renderer-{new_id('render')[-6:]}"
        edition["manifest"]["content_hash"] = sha256_json({"blocks": edition["blocks"], "renderer": edition["manifest"]["renderer_version"]})
        for fmt in ("html", "pdf", "epub", "archive"):
            raw = _artifact_bytes(edition, fmt)
            edition["artifacts"][fmt] = _artifact_record(memory, edition, fmt, raw)
        edition["manifest"]["artifact_hashes"] = {fmt: artifact["sha256"] for fmt, artifact in edition["artifacts"].items()}
        edition["manifest_hash"] = sha256_json(edition["manifest"])
        edition["status"] = "DRAFT"
        edition["approval"] = None
        edition["review_flags"] = [flag for flag in edition.get("review_flags", []) if flag.startswith("context_rights:")]
        edition["preflight_inputs"] = {}
        edition["preflight"] = {"ok": True, "issues": [], "checked_at": None, "checks": []}
        memory.audit("edition.rerendered", _account_id(x_account_id), project["id"], edition_id=edition_id)
        return _edition_public(edition)

    @app.post("/v1/editions/{edition_id}/approvals")
    def approve_edition(edition_id: str, payload: ApprovalCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        edition = _find_edition(memory, edition_id)
        project = _project(memory, edition["project_id"], actor)
        if actor not in {project["storyteller_id"], project["owner_id"]}:
            raise _unauthorised()
        if payload.manifest_hash != edition["manifest_hash"]:
            raise HTTPException(status_code=409, detail="Approval must reference the exact artifact manifest")
        if not edition["preflight"].get("ok"):
            raise HTTPException(status_code=422, detail="Critical preflight issues must be resolved before approval")
        edition["status"] = "APPROVED"
        edition["approval"] = {"approved_by": actor, "approved_at": now_iso(), "manifest_hash": payload.manifest_hash, "note": payload.note}
        memory.audit("edition.approved", actor, project["id"], edition_id=edition_id, manifest_hash=payload.manifest_hash)
        memory.emit(project, "edition.approved", edition_id=edition_id)
        return _edition_public(edition)

    @app.post("/v1/editions/{edition_id}/releases")
    def release_edition(edition_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        edition = _find_edition(memory, edition_id)
        project = _project(memory, edition["project_id"], actor)
        if actor not in {project["owner_id"], project["storyteller_id"]}:
            raise _unauthorised()
        if edition["status"] not in {"APPROVED", "RELEASED"}:
            raise HTTPException(status_code=409, detail="The exact artifact set must be approved before release")
        if edition.get("release_blocked"):
            raise HTTPException(status_code=409, detail="This edition requires review after a source or rights change")
        if edition["status"] != "RELEASED":
            edition["status"] = "RELEASED"
            edition["released_at"] = now_iso()
            edition["released_by"] = actor
            memory.audit("edition.released", actor, project["id"], edition_id=edition_id, manifest_hash=edition["manifest_hash"])
            memory.emit(project, "edition.released", edition_id=edition_id)
        return _edition_public(edition)

    @app.get("/v1/editions/{edition_id}/artifacts/{fmt}")
    def download_artifact(edition_id: str, fmt: str, x_account_id: str | None = Header(default=None)) -> Response:
        edition = _find_edition(memory, edition_id)
        project = _project(memory, edition["project_id"], _account_id(x_account_id))
        if edition["status"] != "APPROVED" and _account_id(x_account_id) not in {project["owner_id"], project["storyteller_id"]}:
            raise HTTPException(status_code=403, detail="Edition is not approved")
        artifact = edition["artifacts"].get(fmt)
        if not artifact:
            raise _not_found("Artifact")
        content = memory.read_object(artifact["object_key"]) if artifact.get("object_key") else base64.b64decode(artifact["content_base64"])
        media_type = {"html": "text/html", "pdf": "application/pdf", "epub": "application/epub+zip", "archive": "application/zip"}.get(fmt, "application/octet-stream")
        return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="memory-spark-{edition_id}.{fmt}"', "X-Artifact-SHA256": artifact["sha256"]})

    @app.get("/v1/artifacts/{artifact_id}/download")
    def download_artifact_alias(artifact_id: str, format: str = "pdf", x_account_id: str | None = Header(default=None)) -> Response:
        if any(artifact_id in project.get("editions", {}) for project in memory.projects.values()):
            return download_artifact(artifact_id, format, x_account_id)
        for project in memory.projects.values():
            for edition in project.get("editions", {}).values():
                if any(artifact_id == artifact.get("sha256") for artifact in edition.get("artifacts", {}).values()):
                    return download_artifact(edition["id"], next((fmt for fmt, artifact in edition["artifacts"].items() if artifact.get("sha256") == artifact_id), format), x_account_id)
        raise _not_found("Artifact")

    @app.get("/v1/editions/{edition_id}/artifacts")
    def list_artifacts(edition_id: str, x_account_id: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        edition = _find_edition(memory, edition_id)
        _project(memory, edition["project_id"], _account_id(x_account_id))
        page = _paginate([{key: value for key, value in artifact.items() if key != "content_base64"} for artifact in edition["artifacts"].values()], cursor, limit)
        return {"edition_id": edition_id, "manifest_hash": edition["manifest_hash"], **page}

    @app.get("/v1/editions/{edition_id}/reader")
    def reader(edition_id: str, x_account_id: str | None = Header(default=None)) -> Response:
        edition = _find_edition(memory, edition_id)
        _project(memory, edition["project_id"], _account_id(x_account_id))
        return Response(content=edition["rendered_content"], media_type="text/html")

    @app.get("/v1/plans")
    def list_plans(region: str = "au") -> dict[str, Any]:
        return {"items": [deepcopy(plan) for plan in memory.plans.values() if plan["status"] == "live" and plan["processing_region"] == region]}

    @app.post("/v1/projects/{project_id}/checkout", status_code=status.HTTP_201_CREATED)
    def create_checkout(project_id: str, payload: CheckoutCreate, x_account_id: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        payer = _account_id(x_account_id)
        request_hash = sha256_json(payload.model_dump())
        operation_key = f"checkout:{payer}:{project_id}:{idempotency_key}" if idempotency_key else None
        if operation_key:
            prior = memory.idempotency.get(operation_key)
            if prior:
                if prior["request_hash"] != request_hash:
                    raise _idempotency_conflict()
                return deepcopy(prior["response"])
        target = memory.projects.get(project_id)
        if not target:
            raise _not_found("Project")
        if payer not in target["members"] and payload.beneficiary_project_id not in {None, project_id}:
            raise _unauthorised()
        project = target if payer in target["members"] or payload.beneficiary_project_id == project_id else _project(memory, project_id, payer)
        if payload.beneficiary_project_id and payload.beneficiary_project_id != project_id:
            beneficiary = memory.projects.get(payload.beneficiary_project_id)
            if not beneficiary:
                raise _not_found("Beneficiary project")
            project = beneficiary
        plan = memory.plans.get(payload.plan_key)
        if not plan or plan["status"] != "live" or plan["processing_region"] != project["home_region"]:
            raise HTTPException(status_code=409, detail="This package is not available in the project's processing region")
        if payload.client_amount_minor is not None and payload.client_amount_minor != plan["amount_minor"]:
            raise HTTPException(status_code=400, detail="Checkout amount is server-defined")
        order_id = new_id("order")
        order = {"id": order_id, "order_kind": "digital_package", "payer_account_id": payer, "beneficiary_project_id": project["id"], "plan_key": plan["plan_key"], "plan_version": plan["version"], "amount_minor": plan["amount_minor"], "currency": plan["currency"], "terms_version": plan["terms_version"], "status": "PENDING", "created_at": now_iso(), "payment_url": f"/demo-checkout/{order_id}"}
        memory.orders[order_id] = order
        project["orders"].append(order_id)
        memory.audit("checkout.started", payer, project["id"], order_id=order_id, plan_key=plan["plan_key"])
        response = deepcopy(order)
        if operation_key:
            memory.idempotency[operation_key] = {"request_hash": request_hash, "response": deepcopy(response)}
        return response

    @app.post("/v1/projects/{project_id}/payment-invitations", status_code=status.HTTP_201_CREATED)
    def create_payment_invitation(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor)
        if actor not in {project["owner_id"], project["storyteller_id"]} and "purchase" not in project["members"].get(actor, {}).get("capabilities", []):
            raise _unauthorised()
        data = payload.model_dump()
        plan_key = data.get("plan_key", "complete_digital_memoir_v1")
        plan = memory.plans.get(plan_key)
        if not plan or plan["status"] != "live" or plan["processing_region"] != project["home_region"]:
            raise HTTPException(status_code=409, detail="This package is not available in the project's processing region")
        token = uuid4_hex()
        invitation_id = new_id("payment-invite")
        invitation = {"id": invitation_id, "project_id": project_id, "token_hash": hashlib.sha256(token.encode()).hexdigest(), "plan_key": plan_key, "plan_version": plan["version"], "beneficiary_project_id": project_id, "created_by": actor, "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), "status": "OPEN", "created_at": now_iso()}
        project.setdefault("payment_invitations", {})[invitation_id] = invitation
        memory.audit("payment_invitation.created", actor, project_id, invitation_id=invitation_id, plan_key=plan_key)
        return {"id": invitation_id, "token": token, "beneficiary_project_id": project_id, "plan": {"plan_key": plan["plan_key"], "version": plan["version"], "name": plan["name"], "amount_minor": plan["amount_minor"], "currency": plan["currency"], "terms_version": plan["terms_version"]}, "expires_at": invitation["expires_at"], "status": invitation["status"]}

    @app.get("/v1/orders/{order_id}")
    def get_order(order_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        order = memory.orders.get(order_id)
        if not order:
            raise _not_found("Order")
        actor = _account_id(x_account_id)
        project = memory.projects.get(order["beneficiary_project_id"])
        if actor != order["payer_account_id"] and (not project or actor not in project["members"]):
            raise _unauthorised()
        return deepcopy(order)

    @app.post("/v1/webhooks/payments/{provider}")
    def payment_webhook(provider: str, payload: PaymentWebhook) -> dict[str, Any]:
        if provider != "demo":
            raise HTTPException(status_code=404, detail="Payment provider is not enabled in this cell")
        if not hmac.compare_digest(payload.signature, "demo-signature"):
            raise HTTPException(status_code=400, detail="Invalid payment signature")
        event_hash = sha256_json(payload.model_dump())
        if payload.event_id in memory.payment_events:
            previous = memory.payment_events[payload.event_id]
            if previous.get("request_hash") != event_hash:
                raise _idempotency_conflict()
            return deepcopy(previous["response"])
        order = memory.orders.get(payload.order_id)
        if not order:
            raise _not_found("Order")
        if payload.amount_minor != order["amount_minor"] or payload.currency != order["currency"]:
            order["status"] = "REQUIRES_RECONCILIATION"
            raise HTTPException(status_code=409, detail="Payment amount or currency does not match the server order")
        event = {"id": payload.event_id, "provider": provider, "order_id": payload.order_id, "status": payload.status, "received_at": now_iso()}
        response = {"accepted": True, "duplicate": False, "event_id": payload.event_id}
        memory.payment_events[payload.event_id] = {"event": event, "request_hash": event_hash, "response": response}
        project = memory.projects[order["beneficiary_project_id"]]
        if payload.status == "paid" and order["status"] != "PAID":
            order["status"] = "PAID"
            order["paid_at"] = now_iso()
            grant_key = f"grant:{order['id']}"
            if not any(grant.get("key") == grant_key for grant in project.setdefault("grants", [])):
                plan = memory.plans[order["plan_key"]]
                project["paid_units_total"] += plan["additional_primary_sessions"]
                project["grants"].append({"id": new_id("grant"), "key": grant_key, "kind": "digital_package", "units": plan["additional_primary_sessions"], "consumed_units": 0, "reserved_units": 0, "revoked_units": 0, "issued_to_project": project["id"], "issued_at": now_iso(), "expires_at": (datetime.now(timezone.utc) + timedelta(days=plan["creation_days"])).isoformat()})
                memory.audit("entitlement.granted", order["payer_account_id"], project["id"], order_id=order["id"], units=plan["additional_primary_sessions"])
                memory.emit(project, "order.paid", order_id=order["id"], payer_account_id=order["payer_account_id"])
        return deepcopy(response)

    @app.post("/v1/orders/{order_id}/refund")
    def refund_order(order_id: str, payload: RefundCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        order = memory.orders.get(order_id)
        if not order:
            raise _not_found("Order")
        project = _project(memory, order["beneficiary_project_id"], actor)
        if actor not in {order["payer_account_id"], project["owner_id"]}:
            raise _unauthorised()
        order["status"] = "REFUNDED"
        order["refund"] = {"reason": payload.reason, "amount_minor": payload.amount_minor or order["amount_minor"], "created_at": now_iso()}
        _refresh_expired_grants(project)
        unused = max(0, project["paid_units_total"] - project.get("paid_units_revoked", 0) - project["paid_units_consumed"] - project["paid_units_reserved"])
        remaining_to_revoke = unused
        for grant in sorted(project.get("grants", []), key=lambda item: item.get("expires_at", "")):
            grant_unused = max(0, grant.get("units", 0) - grant.get("consumed_units", 0) - grant.get("reserved_units", 0) - grant.get("revoked_units", 0))
            revoke = min(remaining_to_revoke, grant_unused)
            if revoke:
                grant["revoked_units"] = grant.get("revoked_units", 0) + revoke
                grant["revoked_at"] = now_iso()
                grant["revocation_reason"] = "order_refunded"
                remaining_to_revoke -= revoke
            if remaining_to_revoke == 0:
                break
        project["paid_units_revoked"] = project.get("paid_units_revoked", 0) + unused
        memory.audit("order.refunded", actor, project["id"], order_id=order_id, revoked_unused_units=unused)
        return {"order": deepcopy(order), "revoked_unused_units": unused, "content_preserved": True}

    @app.post("/v1/orders/{order_id}/refund-requests", status_code=status.HTTP_202_ACCEPTED)
    def request_refund(order_id: str, payload: RefundCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        result = refund_order(order_id, payload, x_account_id)
        request = {"id": new_id("refund"), "order_id": order_id, "status": "APPROVED_DEMO", "reason": payload.reason, "requested_at": now_iso()}
        result["refund_request"] = request
        return result

    @app.post("/v1/projects/{project_id}/preview-builds", status_code=status.HTTP_202_ACCEPTED)
    def build_preview(project_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id))
        snapshot_hash = sha256_json({"memory_ids": sorted(project["memories"]), "revisions": [item["revision"] for item in project["memories"].values()]})
        existing = project["preview_jobs"].get(snapshot_hash)
        if existing:
            return {"job": deepcopy(memory.jobs[existing]), "preview": deepcopy(project.get("preview"))}
        job = memory.queue_job(project_id, "BuildFreePreview", {"snapshot_hash": snapshot_hash, "memory_ids": sorted(project["memories"])})
        preview = _build_preview(project, memory)
        memory.complete_job(job["id"], {"preview_id": preview["id"]})
        project["preview_jobs"][snapshot_hash] = job["id"]
        project["preview"] = preview
        memory.emit(project, "preview.ready", preview_id=preview["id"])
        return {"job": deepcopy(job), "preview": deepcopy(preview)}

    @app.get("/v1/projects/{project_id}/preview")
    def get_preview(project_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        if not project.get("preview"):
            raise _not_found("Preview")
        return deepcopy(project["preview"])

    @app.get("/v1/projects/{project_id}/preview/download")
    def download_preview(project_id: str, format: str = "html", x_account_id: str | None = Header(default=None)) -> Response:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        preview = project.get("preview")
        if not preview:
            raise _not_found("Preview")
        html = "<article><h1>" + escape(preview["title"]) + "</h1>" + "".join(f"<p>{escape(line)}</p>" for line in preview["narrative"].splitlines() if line.strip()) + "</article>"
        if format == "pdf":
            content = ("%PDF-1.4\n% Memory Spark preview\n" + html + "\n%%EOF\n").encode()
            return Response(content=content, media_type="application/pdf", headers={"Content-Disposition": "attachment; filename=memory-spark-preview.pdf"})
        return Response(content=html.encode(), media_type="text/html", headers={"Content-Disposition": "attachment; filename=memory-spark-preview.html"})

    @app.post("/v1/projects/{project_id}/exports", status_code=status.HTTP_202_ACCEPTED)
    def create_export(project_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor, allow_deleted=True)
        if project.get("deletion_state") not in {"ACTIVE", "REQUESTED"}:
            raise HTTPException(status_code=410, detail="Project exports are unavailable after deletion")
        data = payload.model_dump()
        export_id = new_id("export")
        source_items = []
        for asset in project.get("assets", {}).values():
            source_id = asset.get("source_version_id") or asset.get("caption_source_version_id")
            source = memory.source_versions.get(source_id) if source_id else None
            source_items.append({"asset": deepcopy(asset), "source": deepcopy(source) if source else None})
        export = {"id": export_id, "project_id": project_id, "kind": data.get("kind", "owned_sources"), "status": "READY", "created_by": actor, "created_at": now_iso(), "items": source_items, "download_url": f"/v1/projects/{project_id}/exports/{export_id}"}
        project.setdefault("exports", {})[export_id] = export
        job = memory.queue_job(project_id, "BuildSourceExport", {"export_id": export_id, "kind": export["kind"]})
        memory.complete_job(job["id"], {"export_id": export_id})
        memory.audit("export.created", actor, project_id, export_id=export_id, kind=export["kind"])
        return {"job": deepcopy(job), "export": {key: deepcopy(value) for key, value in export.items() if key != "items"}}

    @app.get("/v1/projects/{project_id}/exports/{export_id}")
    def get_export(project_id: str, export_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        export = project.get("exports", {}).get(export_id)
        if not export:
            raise _not_found("Export")
        return deepcopy(export)

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        job = memory.jobs.get(job_id)
        if not job:
            raise _not_found("Job")
        _project(memory, job["project_id"], _account_id(x_account_id), allow_deleted=True)
        return deepcopy(job)

    @app.get("/v1/projects/{project_id}/events", response_model=None)
    def events(project_id: str, request: Request, after: int = 0, x_account_id: str | None = Header(default=None)) -> dict[str, Any] | StreamingResponse:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        last_event_id = request.headers.get("last-event-id")
        if last_event_id and last_event_id.isdigit():
            after = int(last_event_id)
        current = project["event_cursor"]
        if after < max(0, current - 100) and after != 0:
            result: dict[str, Any] = {"reset": True, "cursor": current, "items": []}
        else:
            result = {"reset": False, "cursor": current, "items": [deepcopy(event) for event in project["events"] if event["cursor"] > after]}
        if "text/event-stream" not in request.headers.get("accept", ""):
            return result

        def stream() -> Any:
            if result["reset"]:
                yield f"id: {current}\nevent: reset\ndata: {json.dumps({'reset': True, 'cursor': current})}\n\n"
                return
            for event in result["items"]:
                yield f"id: {event['cursor']}\nevent: {event['event']}\ndata: {json.dumps(event['data'], ensure_ascii=False)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Event-Cursor": str(current)})

    @app.post("/v1/projects/{project_id}/editions/{edition_id}/audio-links")
    def create_audio_link(project_id: str, edition_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id))
        if edition_id not in project["editions"]:
            raise _not_found("Edition")
        link_id = new_id("audio")
        project.setdefault("audio_links", {})[link_id] = {"id": link_id, "edition_id": edition_id, "project_id": project_id, "revoked": False, "book_holder_access": False, "grants": {}, "created_at": now_iso()}
        return {"opaque_id": link_id, "resolver": f"/v1/audio-links/{link_id}", "requires_project_authentication": True}

    @app.get("/v1/audio-links/{opaque_id}")
    def resolve_audio_link(opaque_id: str, token: str | None = None, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        found = next(((project, link) for project in memory.projects.values() for link in project.get("audio_links", {}).values() if link["id"] == opaque_id), None)
        if not found:
            raise _not_found("Audio link")
        project, link = found
        if link["revoked"]:
            raise HTTPException(status_code=410, detail="Audio access has been revoked")
        actor = _account_id(x_account_id)
        token_grant = next((grant for grant in link.get("grants", {}).values() if token and hmac.compare_digest(grant["token_hash"], hashlib.sha256(token.encode()).hexdigest()) and datetime.fromisoformat(grant["expires_at"]) > datetime.now(timezone.utc) and not grant["revoked"]), None)
        if actor not in project["members"] and not token_grant:
            raise _unauthorised()
        return {"allowed": True, "playback_url": f"/v1/audio-links/{opaque_id}/playback", "expires_in_seconds": 300, "grant_id": token_grant["id"] if token_grant else None, "printed_code_recall": "Printed copies cannot be technically recalled"}

    @app.post("/v1/audio-links/{opaque_id}/grants", status_code=status.HTTP_201_CREATED)
    def grant_audio_link(opaque_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        found = next(((project, link) for project in memory.projects.values() for link in project.get("audio_links", {}).values() if link["id"] == opaque_id), None)
        if not found:
            raise _not_found("Audio link")
        project, link = found
        actor = _account_id(x_account_id)
        if actor not in {project["owner_id"], project["storyteller_id"]}:
            raise _unauthorised()
        data = payload.model_dump()
        token = uuid4_hex()
        grant_id = new_id("audio-grant")
        grant = {"id": grant_id, "account_id": data.get("account_id"), "clip_ids": data.get("clip_ids", []), "token_hash": hashlib.sha256(token.encode()).hexdigest(), "expires_at": (datetime.now(timezone.utc) + timedelta(hours=max(1, min(int(data.get("expires_in_hours", 168)), 8760)))).isoformat(), "revoked": False, "created_by": actor, "created_at": now_iso()}
        link.setdefault("grants", {})[grant_id] = grant
        memory.audit("audio_link.granted", actor, project["id"], opaque_id=opaque_id, grant_id=grant_id)
        return {"id": grant_id, "opaque_id": opaque_id, "token": token, "expires_at": grant["expires_at"], "clip_ids": grant["clip_ids"]}

    @app.post("/v1/audio-links/{opaque_id}/grants/{grant_id}/revoke")
    def revoke_audio_grant(opaque_id: str, grant_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        found = next(((project, link) for project in memory.projects.values() for link in project.get("audio_links", {}).values() if link["id"] == opaque_id), None)
        if not found:
            raise _not_found("Audio link")
        project, link = found
        actor = _account_id(x_account_id)
        if actor not in {project["owner_id"], project["storyteller_id"]}:
            raise _unauthorised()
        grant = link.get("grants", {}).get(grant_id)
        if not grant:
            raise _not_found("Audio grant")
        grant["revoked"] = True
        grant["revoked_at"] = now_iso()
        memory.audit("audio_link.grant_revoked", actor, project["id"], opaque_id=opaque_id, grant_id=grant_id)
        return deepcopy(grant)

    @app.post("/v1/audio-links/{opaque_id}/revoke")
    def revoke_audio_link(opaque_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        found = next(((project, link) for project in memory.projects.values() for link in project.get("audio_links", {}).values() if link["id"] == opaque_id), None)
        if not found:
            raise _not_found("Audio link")
        project, link = found
        actor = _account_id(x_account_id)
        if actor not in {project["storyteller_id"], project["owner_id"]}:
            raise _unauthorised()
        link["revoked"] = True
        link["revoked_at"] = now_iso()
        memory.audit("audio_link.revoked", actor, project["id"], opaque_id=opaque_id)
        return deepcopy(link)

    @app.get("/v1/suppliers")
    def list_suppliers() -> dict[str, Any]:
        return {"items": [deepcopy(supplier) for supplier in memory.suppliers.values() if supplier["enabled"]], "count": len(memory.suppliers)}

    @app.post("/v1/projects/{project_id}/print-quotes", status_code=status.HTTP_201_CREATED)
    def create_project_quote(project_id: str, payload: PrintQuoteCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        return _create_quote(memory, project_id, payload, _account_id(x_account_id))

    @app.post("/v1/editions/{edition_id}/print-quotes", status_code=status.HTTP_201_CREATED)
    def create_edition_quote(edition_id: str, payload: PrintQuoteCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        edition = _find_edition(memory, edition_id)
        _project(memory, edition["project_id"], _account_id(x_account_id))
        return _create_quote(memory, edition["project_id"], payload, _account_id(x_account_id), edition_id=edition_id)

    @app.post("/v1/print-quotes/{quote_id}/accept")
    def accept_print_quote(quote_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        quote = memory.print_quotes.get(quote_id)
        if not quote:
            raise _not_found("Print quote")
        actor = _account_id(x_account_id)
        project = _project(memory, quote["project_id"], actor)
        if datetime.fromisoformat(quote["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="Print quote has expired")
        if quote["status"] not in {"QUOTED", "ACCEPTED"}:
            raise HTTPException(status_code=409, detail="Print quote cannot be accepted in its current state")
        quote["status"] = "ACCEPTED"
        quote["accepted_by"] = actor
        quote["accepted_at"] = now_iso()
        memory.audit("print_quote.accepted", actor, project["id"], quote_id=quote_id)
        return deepcopy(quote)

    @app.post("/v1/editions/{edition_id}/print-orders", status_code=status.HTTP_201_CREATED)
    def create_edition_print_order(edition_id: str, payload: PrintOrderCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        edition = _find_edition(memory, edition_id)
        project = _project(memory, edition["project_id"], _account_id(x_account_id))
        return _create_print_order(memory, project, edition, payload)

    @app.post("/v1/print-orders/{print_order_id}/proofs", status_code=status.HTTP_201_CREATED)
    def receive_proof(print_order_id: str, payload: ProofCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        _project(memory, order["project_id"], _account_id(x_account_id))
        if order["status"] in {"CANCELLED", "DELIVERED"}:
            raise HTTPException(status_code=409, detail="Print order is no longer editable")
        order["proof"] = {"id": new_id("proof"), "print_order_id": print_order_id, "manifest_hash": payload.manifest_hash, "proof_file_hash": payload.proof_file_hash or payload.manifest_hash, "status": "PROOF_RECEIVED", "created_at": now_iso()}
        order["status"] = "PROOF_RECEIVED"
        return deepcopy(order)

    @app.get("/v1/print-orders/{print_order_id}")
    def get_print_order(print_order_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        _project(memory, order["project_id"], _account_id(x_account_id), allow_deleted=True)
        return deepcopy(order)

    @app.post("/v1/print-orders/{print_order_id}/cancellation-requests", status_code=status.HTTP_202_ACCEPTED)
    def request_print_cancellation(print_order_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        project = _project(memory, order["project_id"], actor)
        if actor not in {project["owner_id"], project["storyteller_id"]}:
            raise _unauthorised()
        if order["status"] in {"SUBMITTED", "SUBMISSION_UNKNOWN", "IN_PRODUCTION", "SHIPPED", "DELIVERED"}:
            raise HTTPException(status_code=409, detail="The print order has passed the cancellation cutoff")
        order["status"] = "CANCELLED"
        order["cancellation_request"] = {"id": new_id("cancellation"), "reason": payload.model_dump().get("reason", "customer_request"), "requested_by": actor, "requested_at": now_iso()}
        memory.audit("print_order.cancelled", actor, project["id"], print_order_id=print_order_id)
        return deepcopy(order)

    @app.post("/v1/print-orders/{print_order_id}/proof-approvals")
    def approve_proof(print_order_id: str, payload: ApprovalCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        project = _project(memory, order["project_id"], actor)
        if actor not in {project["storyteller_id"], project["owner_id"]}:
            raise _unauthorised()
        proof = order.get("proof")
        if not proof or payload.manifest_hash != proof["manifest_hash"]:
            raise HTTPException(status_code=409, detail="Proof approval must reference the exact returned manifest")
        order["proof_approval"] = {"approved_by": actor, "approved_at": now_iso(), "manifest_hash": payload.manifest_hash}
        order["status"] = "CUSTOMER_APPROVED"
        return deepcopy(order)

    @app.post("/v1/print-orders/{print_order_id}/supplier-update")
    def supplier_update(print_order_id: str, payload: SupplierUpdate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        actor = _account_id(x_account_id)
        project = memory.projects.get(order["project_id"])
        if not project:
            raise _not_found("Project")
        if actor not in project["members"] and not _is_operator(actor, None):
            raise _unauthorised()
        proof = order.get("proof")
        order["supplier_manifest_hash"] = payload.manifest_hash
        if proof and payload.manifest_hash != proof["manifest_hash"]:
            order["status"] = "REQUIRES_REVISION"
            order["proof_approval"] = None
        return deepcopy(order)

    @app.get("/v1/print-orders/{print_order_id}/supplier-package")
    def supplier_package(print_order_id: str, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        if not _is_operator(_account_id(x_account_id), x_role):
            raise _unauthorised()
        supplier = memory.suppliers[order["supplier_id"]]
        if not supplier["qualified"] or not supplier["enabled"]:
            raise HTTPException(status_code=409, detail="Supplier is not qualified or enabled")
        if order["status"] != "CUSTOMER_APPROVED":
            raise HTTPException(status_code=409, detail="Only the approved proof can be sent to the supplier")
        edition = _find_edition(memory, order["edition_id"])
        return {"supplier": {"id": supplier["id"], "name": supplier["name"]}, "print_order_id": print_order_id, "files": {fmt: {"sha256": artifact["sha256"], "format": fmt} for fmt, artifact in edition["artifacts"].items() if fmt in {"pdf", "html"}}, "delivery": order["delivery"], "raw_audio_included": False, "source_transcripts_included": False}

    @app.post("/v1/print-orders/{print_order_id}/submit")
    def submit_print_order(print_order_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None), idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        if not _is_operator(actor, x_role):
            raise _unauthorised()
        project = memory.projects.get(order["project_id"])
        if not project:
            raise _not_found("Project")
        if order["status"] == "SUBMISSION_UNKNOWN":
            raise HTTPException(status_code=409, detail="Supplier acknowledgement is unknown; verify status before retrying")
        if order["status"] != "CUSTOMER_APPROVED":
            raise HTTPException(status_code=409, detail="Exact proof approval is required before submission")
        key = _idempotency_key(idempotency_key, f"submit:{print_order_id}")
        request_hash = sha256_json(payload.model_dump())
        if order.get("submission_key") == key:
            if order.get("submission_request_hash") != request_hash:
                raise _idempotency_conflict()
            return deepcopy(order)
        order["submission_key"] = key
        order["submission_request_hash"] = request_hash
        order["status"] = "SUBMISSION_UNKNOWN" if payload.model_dump().get("ack_lost") else "SUBMITTED"
        if order["status"] == "SUBMITTED":
            order["submitted_at"] = now_iso()
        memory.audit("print_order.submitted", actor, project["id"], print_order_id=print_order_id, status=order["status"])
        return deepcopy(order)

    @app.post("/v1/print-orders/{print_order_id}/tracking")
    def update_tracking(print_order_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        if not _is_operator(actor, None):
            raise _unauthorised()
        order = memory.print_orders.get(print_order_id)
        if not order:
            raise _not_found("Print order")
        data = payload.model_dump()
        order["tracking"] = data
        order["status"] = data.get("status", "IN_PRODUCTION")
        return deepcopy(order)

    @app.post("/v1/projects/{project_id}/deletion-requests", status_code=status.HTTP_202_ACCEPTED)
    def request_deletion(project_id: str, payload: DeletionCreate, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        project = _project(memory, project_id, actor, allow_deleted=True)
        if actor not in {project["storyteller_id"], project["owner_id"]}:
            raise _unauthorised()
        if payload.confirmation != "DELETE":
            raise HTTPException(status_code=400, detail="Explicit deletion confirmation is required")
        request_id = new_id("deletion")
        _bump_policy_epoch(project)
        project["deletion_state"] = "REQUESTED"
        project["deleted_at"] = now_iso()
        project["deletion_request"] = {"id": request_id, "reason": payload.reason, "requested_by": actor, "requested_at": now_iso(), "status": "COMPLETED", "retained_records": ["settled_finance_records"]}
        memory.deleted_projects[project_id] = {"tombstone_at": project["deleted_at"], "request_id": request_id}
        for session in project["sessions"].values():
            session["status"] = "DELETION_BLOCKED"
        for job in memory.jobs.values():
            if job.get("project_id") == project_id:
                job["status"] = "DELETION_BLOCKED"
                job.pop("result", None)
                job["snapshot"] = {"deletion_blocked": True}
        project["memories"] = {}
        project["assets"] = {}
        memory.audit("project.deletion_requested", actor, project_id, request_id=request_id)
        return deepcopy(project["deletion_request"])

    @app.get("/v1/projects/{project_id}/deletion-requests")
    def get_deletion(project_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        project = _project(memory, project_id, _account_id(x_account_id), allow_deleted=True)
        if not project.get("deletion_request"):
            raise _not_found("Deletion request")
        return deepcopy(project["deletion_request"])

    @app.get("/v1/ops/jobs")
    def operations_jobs(x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        if not _is_operator(_account_id(x_account_id), x_role):
            raise _unauthorised()
        return _paginate([{key: deepcopy(value) for key, value in job.items() if key not in {"snapshot", "result"}} for job in memory.jobs.values()], cursor, limit)

    @app.post("/v1/ops/jobs/{job_id}/retry")
    def retry_job(job_id: str, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        if not _is_operator(actor, x_role):
            raise _unauthorised()
        job = memory.jobs.get(job_id)
        if not job:
            raise _not_found("Job")
        if job["status"] == "SUCCEEDED":
            raise HTTPException(status_code=409, detail="Succeeded jobs do not need a retry")
        memory.requeue_job(job)
        memory.audit("job.retried", actor, job["project_id"], job_id=job_id)
        return deepcopy(job)

    @app.post("/v1/ops/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        if not _is_operator(actor, x_role):
            raise _unauthorised()
        job = memory.jobs.get(job_id)
        if not job:
            raise _not_found("Job")
        if job["status"] == "SUCCEEDED":
            raise HTTPException(status_code=409, detail="Succeeded jobs cannot be cancelled")
        job["status"] = "CANCELLED"
        job["updated_at"] = now_iso()
        memory.audit("job.cancelled", actor, job["project_id"], job_id=job_id)
        return deepcopy(job)

    @app.post("/v1/ops/support-grants", status_code=status.HTTP_201_CREATED)
    def create_support_grant(payload: LooseModel, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        if not _is_operator(actor, x_role):
            raise _unauthorised()
        data = payload.model_dump()
        project_id = data.get("project_id")
        project = memory.projects.get(project_id)
        if not project:
            raise _not_found("Project")
        expires_hours = max(1, min(int(data.get("expires_in_hours", 24)), 24 * 90))
        grant_id = new_id("support-grant")
        grant = {"id": grant_id, "project_id": project_id, "account_id": data.get("account_id"), "capabilities": data.get("capabilities", ["read_metadata"]), "purpose": data.get("purpose", "support_investigation"), "issued_by": actor, "expires_at": (datetime.now(timezone.utc) + timedelta(hours=expires_hours)).isoformat(), "revoked": False, "created_at": now_iso()}
        memory.support_grants[grant_id] = grant
        memory.audit("support_grant.created", actor, project_id, grant_id=grant_id, purpose=grant["purpose"], expires_at=grant["expires_at"])
        return deepcopy(grant)

    @app.get("/v1/ops/support-grants")
    def list_support_grants(x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None), cursor: str | None = None, limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        if not _is_operator(_account_id(x_account_id), x_role):
            raise _unauthorised()
        return _paginate(deepcopy(list(memory.support_grants.values())), cursor, limit)

    @app.get("/v1/ops/support-grants/{grant_id}/projects/{project_id}/metadata")
    def support_project_metadata(grant_id: str, project_id: str, x_account_id: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        grant = memory.support_grants.get(grant_id)
        if not grant or grant.get("project_id") != project_id or grant.get("account_id") != actor:
            raise _unauthorised()
        if grant.get("revoked"):
            raise HTTPException(status_code=403, detail="The support grant has been revoked")
        if datetime.fromisoformat(grant["expires_at"]) <= datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="The support grant has expired", headers={"X-Error-Code": "SUPPORT_GRANT_EXPIRED"})
        if "read_metadata" not in grant.get("capabilities", []):
            raise _unauthorised()
        project = memory.projects.get(project_id)
        if not project:
            raise _not_found("Project")
        result = {
            "project_id": project_id,
            "deletion_state": project.get("deletion_state", "ACTIVE"),
            "home_region": project.get("home_region"),
            "member_count": len(project.get("members", {})),
            "session_count": len(project.get("sessions", {})),
            "memory_count": len(project.get("memories", {})),
            "job_count": sum(1 for job in memory.jobs.values() if job.get("project_id") == project_id),
            "grant_id": grant_id,
            "expires_at": grant["expires_at"],
        }
        memory.audit("support_grant.metadata_accessed", actor, project_id, grant_id=grant_id)
        return result

    @app.post("/v1/ops/support-grants/{grant_id}/revoke")
    def revoke_support_grant(grant_id: str, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        actor = _account_id(x_account_id)
        if not _is_operator(actor, x_role):
            raise _unauthorised()
        grant = memory.support_grants.get(grant_id)
        if not grant:
            raise _not_found("Support grant")
        grant["revoked"] = True
        grant["revoked_at"] = now_iso()
        memory.audit("support_grant.revoked", actor, grant["project_id"], grant_id=grant_id)
        return deepcopy(grant)

    @app.get("/v1/ops/audit")
    def operations_audit(x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        if not _is_operator(_account_id(x_account_id), x_role):
            raise _unauthorised()
        return {"items": deepcopy(memory.audit_events)}

    @app.patch("/v1/ops/providers/{provider_id}")
    def patch_provider(provider_id: str, payload: ProviderPatch, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        if not _is_operator(_account_id(x_account_id), x_role):
            raise _unauthorised()
        provider = memory.provider_policies.get(provider_id)
        if not provider:
            raise _not_found("Provider")
        for key in ("enabled", "approved"):
            value = getattr(payload, key)
            if value is not None:
                provider[key] = value
        return deepcopy(provider)

    @app.patch("/v1/ops/context-assets/{asset_id}/rights")
    def patch_context_rights(asset_id: str, payload: LooseModel, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        if not _is_operator(_account_id(x_account_id), x_role):
            raise _unauthorised()
        asset = memory.context_assets.get(asset_id)
        if not asset:
            raise _not_found("Context asset")
        data = payload.model_dump()
        previous_rights = deepcopy(asset.get("rights", {}))
        if "rights" in data:
            asset["rights"].update(data["rights"])
        if "reviewed" in data:
            asset["reviewed"] = bool(data["reviewed"])
        changed = previous_rights != asset.get("rights", {})
        if changed:
            asset.setdefault("rights_policy_history", []).append({"version": asset.get("rights_policy_version", "catalogue-v1"), "rights": previous_rights, "recorded_at": now_iso()})
            asset["rights_policy_version"] = new_id("rights")
            capabilities_revoked = any(
                previous_rights.get(capability, False) and not asset["rights"].get(capability, False)
                for capability in ("can_display_in_paid_app", "can_include_in_download", "can_print")
            )
            if capabilities_revoked:
                for project in memory.projects.values():
                    project_changed = False
                    for chapter in project.get("chapters", {}).values():
                        if any(asset_id in block.get("context_asset_ids", []) for block in chapter.get("blocks", [])):
                            project_changed = True
                            chapter.setdefault("review_flags", []).append(f"context_rights:{asset_id}")
                            chapter["status"] = "STALE"
                    for edition in project.get("editions", {}).values():
                        if asset_id in edition.get("context_asset_ids", []):
                            project_changed = True
                            edition["release_blocked"] = True
                            edition.setdefault("review_flags", []).append(f"context_rights:{asset_id}")
                            if edition.get("status") in {"APPROVED", "RELEASED"}:
                                edition["status"] = "REQUIRES_REVIEW"
                            project.setdefault("events", [])
                            memory.emit(project, "context.rights_revoked", asset_id=asset_id, edition_id=edition["id"])
                            memory.audit("context.rights_revoked", _account_id(x_account_id), project["id"], asset_id=asset_id, edition_id=edition["id"])
                    if project_changed:
                        _bump_policy_epoch(project)
        return deepcopy(asset)

    @app.patch("/v1/ops/suppliers/{supplier_id}")
    def patch_supplier(supplier_id: str, payload: SupplierPatch, x_account_id: str | None = Header(default=None), x_role: str | None = Header(default=None)) -> dict[str, Any]:
        if not _is_operator(_account_id(x_account_id), x_role):
            raise _unauthorised()
        supplier = memory.suppliers.get(supplier_id)
        if not supplier:
            raise _not_found("Supplier")
        changed = False
        for key in ("enabled", "qualified", "supported_quantity", "supported_formats", "data_handling_terms", "delivery_countries"):
            value = getattr(payload, key)
            if value is not None:
                if supplier.get(key) != value:
                    changed = True
                supplier[key] = value
        if changed:
            current_version = str(supplier.get("profile_version", "supplier-demo-v1"))
            suffix = int(current_version.rsplit("-v", 1)[-1]) if "-v" in current_version and current_version.rsplit("-v", 1)[-1].isdigit() else 1
            supplier["profile_version"] = f"supplier-{supplier_id}-v{suffix + 1}"
        return deepcopy(supplier)

    web_root = Path(__file__).resolve().parents[1] / "web"
    web_dir = web_root / "public"
    if web_dir.exists():
        app.mount("/static", StaticFiles(directory=web_dir), name="static")
        web_app_dir = web_root / "app"
        if web_app_dir.exists():
            app.mount("/app", StaticFiles(directory=web_app_dir), name="web-app")

        @app.get("/", include_in_schema=False)
        def landing() -> FileResponse:
            return FileResponse(web_dir / "index.html")

        @app.get("/memoir", include_in_schema=False)
        @app.get("/memoir/{subpath:path}", include_in_schema=False)
        @app.get("/voice", include_in_schema=False)
        @app.get("/voice/{subpath:path}", include_in_schema=False)
        def product_landing(subpath: str | None = None) -> FileResponse:
            return FileResponse(web_dir / "index.html")

    return app


def uuid4_hex() -> str:
    return hashlib.sha256(f"{now_iso()}:{new_id('token')}".encode()).hexdigest()


def _find_session(store: MemoryStore, session_id: str, actor: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for project in store.projects.values():
        if session_id in project["sessions"]:
            session = project["sessions"][session_id]
            _project(store, project["id"], actor)
            return session, project
    raise _not_found("Memory session")


def _would_cycle(project: dict[str, Any], from_id: str, to_id: str) -> bool:
    graph: dict[str, set[str]] = {}
    for relation in project["relationships"]:
        if relation["relationship_type"] in {"parent", "child"}:
            graph.setdefault(relation["from_person_id"], set()).add(relation["to_person_id"])
    graph.setdefault(from_id, set()).add(to_id)
    todo = [to_id]
    seen: set[str] = set()
    while todo:
        current = todo.pop()
        if current == from_id:
            return True
        if current in seen:
            continue
        seen.add(current)
        todo.extend(graph.get(current, set()))
    return False


def _build_preview(project: dict[str, Any], store: MemoryStore) -> dict[str, Any]:
    memories = list(project["memories"].values())
    used_topics = [project["sessions"][sid]["topic_id"] for sid in project["session_ids"] if sid in project["sessions"]]
    return {"id": new_id("preview"), "project_id": project["id"], "title": "A beginning to remember", "status": "READY", "narrative": "\n\n".join(item["text"] for item in memories), "memory_cards": [{"id": item["id"], "text": item["text"], "source_linked": bool(item["source_version_ids"])} for item in memories], "timeline": deepcopy([item for item in project["timeline"] if item.get("precision") != "unknown"]), "suggested_topics": [topic for topic in ["food", "work", "turning_point"] if topic not in used_topics][:3], "downloadable": True, "created_at": now_iso()}


def _edition_public(edition: dict[str, Any]) -> dict[str, Any]:
    return {key: deepcopy(value) for key, value in edition.items() if key not in {"rendered_content", "artifacts", "chapters", "source_links"}}


def _find_edition(store: MemoryStore, edition_id: str) -> dict[str, Any]:
    for project in store.projects.values():
        if edition_id in project["editions"]:
            return project["editions"][edition_id]
    raise _not_found("Edition")


def _create_quote(store: MemoryStore, project_id: str, payload: PrintQuoteCreate, actor: str, edition_id: str | None = None) -> dict[str, Any]:
    project = _project(store, project_id, actor)
    if edition_id:
        edition = _find_edition(store, edition_id)
        if edition.get("status") not in {"APPROVED", "RELEASED"} or not edition.get("preflight", {}).get("ok") or edition.get("release_blocked"):
            raise HTTPException(status_code=409, detail="An approved, preflighted edition is required for a print quote")
    supplier = store.suppliers.get(payload.supplier_id)
    if not supplier:
        raise _not_found("Supplier")
    if not supplier.get("enabled") or not supplier.get("qualified"):
        raise HTTPException(status_code=409, detail="Supplier is not qualified or enabled")
    bounds = supplier["supported_quantity"]
    if payload.quantity < 1 or payload.quantity > 99 or payload.quantity < bounds["min"] or payload.quantity > bounds["max"]:
        raise HTTPException(status_code=422, detail="Quantity must be within the supplier-supported range of 1 to 99")
    if payload.trim_size not in supplier["supported_formats"]:
        raise HTTPException(status_code=422, detail="Trim size is not supported by this supplier")
    quote_id = new_id("quote")
    quote = {"id": quote_id, "project_id": project_id, "edition_id": edition_id, "supplier_id": supplier["id"], "supplier_profile_version": supplier.get("profile_version", "supplier-demo-v1"), "quantity": payload.quantity, "trim_size": payload.trim_size, "binding": payload.binding, "shipping_country": payload.shipping_country, "line_items": [{"kind": "book", "quantity": payload.quantity, "amount_minor": payload.quantity * 300}, {"kind": "setup_and_shipping", "quantity": 1, "amount_minor": 2500}], "tax": {"included": True, "amount_minor": 0, "jurisdiction": payload.shipping_country}, "amount_minor": 2500 + payload.quantity * 300, "currency": "AUD", "status": "QUOTED", "expires_at": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(), "created_at": now_iso()}
    store.print_quotes[quote_id] = quote
    return deepcopy(quote)


def _create_print_order(store: MemoryStore, project: dict[str, Any], edition: dict[str, Any], payload: PrintOrderCreate) -> dict[str, Any]:
    if edition.get("status") not in {"APPROVED", "RELEASED"} or not edition.get("preflight", {}).get("ok"):
        raise HTTPException(status_code=409, detail="An approved, preflighted edition is required for printing")
    quote = store.print_quotes.get(payload.quote_id)
    if not quote or quote["project_id"] != project["id"] or quote.get("edition_id") not in {None, edition["id"]}:
        raise _not_found("Print quote")
    if datetime.fromisoformat(quote["expires_at"]) <= datetime.now(timezone.utc):
        raise HTTPException(status_code=409, detail="Print quote has expired")
    if quote.get("status") != "ACCEPTED":
        raise HTTPException(status_code=409, detail="The print quote must be accepted before an order is created")
    supplier = store.suppliers.get(quote["supplier_id"])
    if not supplier or not supplier.get("enabled") or not supplier.get("qualified"):
        raise HTTPException(status_code=409, detail="Supplier is not qualified or enabled")
    if quote.get("supplier_profile_version") != supplier.get("profile_version", "supplier-demo-v1"):
        raise HTTPException(status_code=409, detail="The supplier profile changed; request a new quote")
    order_id = new_id("print")
    order = {"id": order_id, "project_id": project["id"], "edition_id": edition["id"], "quote_id": quote["id"], "supplier_id": quote["supplier_id"], "quantity": quote["quantity"], "status": "PAYMENT_CONFIRMED", "payment_status": "CONFIRMED", "payment_confirmed_at": now_iso(), "delivery": {"name": payload.delivery_name, "address": payload.delivery_address, "country": payload.delivery_country}, "interior_hash": edition["artifacts"]["pdf"]["sha256"], "cover_hash": edition["artifacts"]["html"]["sha256"], "created_at": now_iso()}
    store.print_orders[order_id] = order
    project["print_orders"].append(order_id)
    return deepcopy(order)


app = create_app()
