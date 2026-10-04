"""Validate the Family-tree and author-timeline runtime contracts."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from typing import Any


FAMILY_TREE_MARKER_START = "[[MEMORY_SPARK_FAMILY_TREE]]"
FAMILY_TREE_MARKER_END = "[[/MEMORY_SPARK_FAMILY_TREE]]"
AUTHOR_TIMELINE_MARKER_START = "[[MEMORY_SPARK_AUTHOR_TIMELINE]]"
AUTHOR_TIMELINE_MARKER_END = "[[/MEMORY_SPARK_AUTHOR_TIMELINE]]"
# Keep the old marker readable during rollout so a resumed model thread cannot
# leak its control payload into the visible reply. New prompts never emit it.
LEGACY_FAMILY_CONTEXT_MARKER_START = "[[MEMORY_SPARK_FAMILY_CONTEXT]]"
LEGACY_FAMILY_CONTEXT_MARKER_END = "[[/MEMORY_SPARK_FAMILY_CONTEXT]]"
FAMILY_CONTEXT_SCHEMA_VERSION = 2

_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
_PROJECT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_LIVING_STATUSES = {"unknown", "living", "deceased"}
_VISIBILITIES = {"private", "family"}
_RELATIONSHIP_TYPES = {
    "parent",
    "child",
    "spouse",
    "sibling",
    "adoptive_parent",
    "adopted_child",
    "step_parent",
    "step_child",
    "guardian",
    "other",
}
_DIRECTIONS = {"directed", "undirected"}
_PRECISIONS = {"unknown", "day", "month", "year", "range", "approximate", "age", "season"}
_MAX_PEOPLE = 100
_MAX_RELATIONSHIPS = 200
_MAX_TIMELINE_ITEMS = 300
_MAX_LIFE_PERIODS = 100
_MAX_MARKER_CHARS = 20_000
_CONTEXT_KEYS = {"people", "relationships", "timeline"}
_LEGACY_CONTEXT_KEYS = _CONTEXT_KEYS | {"life_periods"}
_TREE_KEYS = {"people", "relationships"}
_TIMELINE_KEYS = {"timeline", "life_periods"}
_MARKERS = (
    (FAMILY_TREE_MARKER_START, FAMILY_TREE_MARKER_END),
    (AUTHOR_TIMELINE_MARKER_START, AUTHOR_TIMELINE_MARKER_END),
    (LEGACY_FAMILY_CONTEXT_MARKER_START, LEGACY_FAMILY_CONTEXT_MARKER_END),
)


def _text(value: Any, limit: int, *, required: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip()
    if not cleaned or len(cleaned) > limit:
        return None
    return cleaned


def _person_name_key(value: Any) -> str | None:
    """Normalize a person label for a conservative exact-name match."""
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.split()).strip().casefold()
    return cleaned or None


def _identifier(value: Any) -> str | None:
    if not isinstance(value, str) or not _ID_PATTERN.fullmatch(value):
        return None
    return value


def _string_list(value: Any, *, limit: int, item_limit: int = 80) -> list[str] | None:
    if not isinstance(value, list) or len(value) > limit:
        return None
    result: list[str] = []
    for item in value:
        cleaned = _text(item, item_limit)
        if cleaned is None or cleaned in result:
            return None
        result.append(cleaned)
    return result


def _optional_enum(raw: dict[str, Any], key: str, allowed: set[str]) -> str | None:
    if key not in raw:
        return None
    value = raw[key]
    return value if isinstance(value, str) and value in allowed else None


def _copy_optional_text(target: dict[str, Any], raw: dict[str, Any], key: str, limit: int) -> bool:
    if key not in raw:
        return True
    value = _text(raw[key], limit)
    if value is None:
        return False
    target[key] = value
    return True


def _copy_optional_identifier(target: dict[str, Any], raw: dict[str, Any], key: str) -> bool:
    if key not in raw:
        return True
    value = _identifier(raw[key])
    if value is None:
        return False
    target[key] = value
    return True


def _normalise_person(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    person_id = _identifier(raw.get("id"))
    name = _text(raw.get("name"), 160)
    if person_id is None or name is None:
        return None
    person: dict[str, Any] = {"id": person_id, "name": name}
    for key, limit in (
        ("family_title", 120),
        ("introduction", 1200),
        ("birth_date_expression", 120),
        ("death_date_expression", 120),
    ):
        if not _copy_optional_text(person, raw, key, limit):
            return None
    if not _copy_optional_identifier(person, raw, "existing_id"):
        return None
    if "aliases" in raw:
        aliases = _string_list(raw["aliases"], limit=8, item_limit=120)
        if aliases is None:
            return None
        person["aliases"] = aliases
    for key, allowed in (("living_status", _LIVING_STATUSES), ("visibility", _VISIBILITIES)):
        if key in raw:
            value = _optional_enum(raw, key, allowed)
            if value is None:
                return None
            person[key] = value
    if "include_in_print" in raw:
        if not isinstance(raw["include_in_print"], bool):
            return None
        person["include_in_print"] = raw["include_in_print"]
    return person


def _normalise_relationship(raw: Any, person_ids: set[str]) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    from_id = _identifier(raw.get("from_person_id"))
    to_id = _identifier(raw.get("to_person_id"))
    relationship_type = raw.get("relationship_type")
    if (
        from_id is None
        or to_id is None
        or from_id == to_id
        or from_id not in person_ids
        or to_id not in person_ids
        or not isinstance(relationship_type, str)
        or relationship_type not in _RELATIONSHIP_TYPES
    ):
        return None
    relation: dict[str, Any] = {
        "from_person_id": from_id,
        "to_person_id": to_id,
        "relationship_type": relationship_type,
    }
    for key, allowed in (("direction", _DIRECTIONS), ("maternal_paternal", {"maternal", "paternal", "unknown"})):
        if key in raw:
            value = _optional_enum(raw, key, allowed)
            if value is None:
                return None
            relation[key] = value
    if not _copy_optional_identifier(relation, raw, "existing_id"):
        return None
    return relation


def _normalise_date_item(
    raw: Any,
    person_ids: set[str],
    *,
    period: bool = False,
    allow_external_person_refs: bool = False,
) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    item_id = _identifier(raw.get("id"))
    title = _text(raw.get("title"), 200)
    if item_id is None or title is None:
        return None
    kind = raw.get("kind", "period" if period else "event")
    if kind not in ("event", "period") or (period and kind != "period"):
        return None
    legacy_period = period
    period = kind == "period"
    if (period and "date_expression" in raw) or (not period and ({"start_expression", "end_expression"} & raw.keys())):
        return None
    item: dict[str, Any] = {"id": item_id, "title": title, "kind": kind}
    if not _copy_optional_identifier(item, raw, "existing_id"):
        return None
    text_keys = ("start_expression", "end_expression", "place") if period else ("date_expression", "place")
    if legacy_period:
        # v1 validation did not include period places in the normalized marker.
        # Retain that ingress behavior so old turn retries keep their IDs.
        text_keys = ("start_expression", "end_expression")
    for key in text_keys:
        if not _copy_optional_text(item, raw, key, 180 if key != "place" else 160):
            return None
    if period and "start_expression" not in item and "end_expression" not in item:
        return None
    if "precision" in raw:
        precision = _optional_enum(raw, "precision", _PRECISIONS)
        if precision is None:
            return None
        item["precision"] = precision
    if "person_ids" in raw:
        linked = _string_list(raw["person_ids"], limit=50, item_limit=80)
        if linked is None or (
            not allow_external_person_refs and any(person_id not in person_ids for person_id in linked)
        ):
            return None
        item["person_ids"] = linked
    for key, allowed in (("visibility", _VISIBILITIES),):
        if key in raw:
            value = _optional_enum(raw, key, allowed)
            if value is None:
                return None
            item[key] = value
    if "include_in_print" in raw:
        if not isinstance(raw["include_in_print"], bool):
            return None
        item["include_in_print"] = raw["include_in_print"]
    return item


def validate_family_context(
    raw: Any,
    *,
    allow_external_person_refs: bool = False,
) -> dict[str, Any] | None:
    """Return a bounded, graph-consistent shared workspace update."""
    if not isinstance(raw, dict) or set(raw) - _LEGACY_CONTEXT_KEYS:
        return None
    collections = {
        "people": (_MAX_PEOPLE, _normalise_person),
        "relationships": (_MAX_RELATIONSHIPS, None),
        "timeline": (_MAX_TIMELINE_ITEMS, None),
        "life_periods": (_MAX_LIFE_PERIODS, None),
    }
    for key, (limit, _normaliser) in collections.items():
        if key in raw and (not isinstance(raw[key], list) or len(raw[key]) > limit):
            return None

    people = [_normalise_person(item) for item in raw.get("people", [])]
    if any(item is None for item in people):
        return None
    person_records = [item for item in people if item is not None]
    person_ids = {item["id"] for item in person_records}
    if len(person_ids) != len(person_records):
        return None

    relationships: list[dict[str, Any]] = []
    for item in raw.get("relationships", []):
        normalised = _normalise_relationship(item, person_ids)
        if normalised is None:
            return None
        relationships.append(normalised)
    relationship_keys = {
        (
            item["from_person_id"],
            item["to_person_id"],
            item["relationship_type"],
            item.get("maternal_paternal"),
        )
        for item in relationships
    }
    if len(relationship_keys) != len(relationships):
        return None

    timeline: list[dict[str, Any]] = []
    for item in raw.get("timeline", []):
        normalised = _normalise_date_item(
            item,
            person_ids,
            allow_external_person_refs=allow_external_person_refs,
        )
        if normalised is None:
            return None
        timeline.append(normalised)
    # Resumed v1 model threads may still emit the former period collection.
    # Normalize it at ingress; all validated updates use one timeline.
    for item in raw.get("life_periods", []):
        normalised = _normalise_date_item(
            item,
            person_ids,
            period=True,
            allow_external_person_refs=allow_external_person_refs,
        )
        if normalised is None:
            return None
        timeline.append(normalised)
    timeline_ids = {item["id"] for item in timeline}
    if len(timeline) > _MAX_TIMELINE_ITEMS or len(timeline_ids) != len(timeline) or timeline_ids & person_ids:
        return None

    if not (person_records or relationships or timeline):
        return None
    return {
        "people": person_records,
        "relationships": relationships,
        "timeline": timeline,
    }


def validate_family_tree_context(raw: Any) -> dict[str, Any] | None:
    """Validate the family-tree skill's people and relationship payload."""
    if not isinstance(raw, dict) or set(raw) - _TREE_KEYS:
        return None
    return validate_family_context(
        {
            "people": raw.get("people", []),
            "relationships": raw.get("relationships", []),
        }
    )


def validate_author_timeline_context(raw: Any) -> dict[str, Any] | None:
    """Validate the author-timeline skill's events and life-period payload."""
    if not isinstance(raw, dict) or set(raw) - _TIMELINE_KEYS:
        return None
    return validate_family_context(
        {
            "people": [],
            "relationships": [],
            "timeline": raw.get("timeline", []),
            "life_periods": raw.get("life_periods", []),
        },
        allow_external_person_refs=True,
    )


def _strip_markers(text: str) -> str:
    visible: list[str] = []
    cursor = 0
    while True:
        candidates = [
            (text.find(start_marker, cursor), start_marker, end_marker)
            for start_marker, end_marker in _MARKERS
        ]
        candidates = [candidate for candidate in candidates if candidate[0] >= 0]
        if not candidates:
            visible.append(text[cursor:])
            break
        start, start_marker, end_marker = min(candidates, key=lambda candidate: candidate[0])
        visible.append(text[cursor:start])
        payload_start = start + len(start_marker)
        end = text.find(end_marker, payload_start)
        if end < 0:
            break
        cursor = end + len(end_marker)
    return "".join(visible).strip()


def _extract_marker_payload(
    text: str,
    start_marker: str,
    end_marker: str,
    validator,
) -> dict[str, Any] | None:
    if not isinstance(text, str):
        return None
    start = text.find(start_marker)
    if start < 0:
        return None
    payload_start = start + len(start_marker)
    end = text.find(end_marker, payload_start)
    if end < 0:
        return None
    if end - payload_start > _MAX_MARKER_CHARS:
        return None
    try:
        raw = json.loads(text[payload_start:end].strip())
    except json.JSONDecodeError:
        return None
    return validator(raw)


def extract_family_skill_updates(text: str) -> tuple[str, list[dict[str, Any]]]:
    """Strip both active skill markers and return each validated domain update."""
    if not isinstance(text, str):
        return "", []
    updates: list[dict[str, Any]] = []
    tree = _extract_marker_payload(
        text,
        FAMILY_TREE_MARKER_START,
        FAMILY_TREE_MARKER_END,
        validate_family_tree_context,
    )
    if tree:
        updates.append({"skill": "family_tree", "context": tree})
    timeline = _extract_marker_payload(
        text,
        AUTHOR_TIMELINE_MARKER_START,
        AUTHOR_TIMELINE_MARKER_END,
        validate_author_timeline_context,
    )
    if timeline:
        updates.append({"skill": "author_timeline", "context": timeline})
    legacy = _extract_marker_payload(
        text,
        LEGACY_FAMILY_CONTEXT_MARKER_START,
        LEGACY_FAMILY_CONTEXT_MARKER_END,
        lambda raw: validate_family_context(raw, allow_external_person_refs=True),
    )
    if legacy:
        updates.append({"skill": "legacy_family_context", "context": legacy})
    return _strip_markers(text), updates


def combine_family_skill_updates(updates: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, list[str]]:
    """Combine independent skill payloads for one atomic document write."""
    combined = {key: [] for key in _CONTEXT_KEYS}
    skills: list[str] = []
    for update in updates:
        if not isinstance(update, dict) or not isinstance(update.get("context"), dict):
            continue
        skill = update.get("skill")
        if isinstance(skill, str) and skill not in skills:
            skills.append(skill)
        context = update["context"]
        for key in _CONTEXT_KEYS:
            combined[key].extend(context.get(key, []))
    if not skills:
        return None, []
    return validate_family_context(combined, allow_external_person_refs=True), skills


def extract_family_tree_context(text: str) -> tuple[str, dict[str, Any] | None]:
    """Compatibility helper for the family-tree marker."""
    return _strip_markers(text) if isinstance(text, str) else "", _extract_marker_payload(
        text, FAMILY_TREE_MARKER_START, FAMILY_TREE_MARKER_END, validate_family_tree_context
    )


def extract_author_timeline_context(text: str) -> tuple[str, dict[str, Any] | None]:
    """Compatibility helper for the author-timeline marker."""
    return _strip_markers(text) if isinstance(text, str) else "", _extract_marker_payload(
        text, AUTHOR_TIMELINE_MARKER_START, AUTHOR_TIMELINE_MARKER_END, validate_author_timeline_context
    )


def extract_family_context(text: str) -> tuple[str, dict[str, Any] | None]:
    """Legacy helper returning the combined active/legacy payload."""
    visible, updates = extract_family_skill_updates(text)
    combined, _skills = combine_family_skill_updates(updates)
    return visible, combined


def family_features_enabled(entitlement: Any, configured_price_id: str | None = None) -> bool:
    """Check the server-controlled Family feature decision."""
    if not isinstance(entitlement, dict):
        return False
    if entitlement.get("status") != "paid" or entitlement.get("plan_key") != "family_memoir_v1":
        return False
    if entitlement.get("family_tree") is not True or entitlement.get("timeline") is not True:
        return False
    expected_price_id = configured_price_id
    if expected_price_id is None:
        expected_price_id = os.getenv("STRIPE_PRICE_FAMILY", "").strip()
    if expected_price_id and entitlement.get("stripe_price_id") != expected_price_id:
        return False
    return True


def valid_family_project_id(project_id: Any) -> str | None:
    """Return a safe project correlation key for the persisted document."""
    if not isinstance(project_id, str) or not _PROJECT_ID_PATTERN.fullmatch(project_id):
        return None
    return project_id


def empty_family_context_document(project_id: str) -> dict[str, Any]:
    """Create the stable, renderable shape stored for a project."""
    if valid_family_project_id(project_id) is None:
        raise ValueError("Invalid Family project id")
    return {
        "schema_version": FAMILY_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "revision": 0,
        "people": [],
        "relationships": [],
        "timeline": [],
    }


_TIMELINE_DATE_PATTERN = re.compile(r"(?<!\d)([12]\d{3})(?:[-/](\d{1,2})(?:[-/](\d{1,2}))?)?(?!\d)")


def _timeline_order(item: dict[str, Any]) -> tuple[int, int, int]:
    expression = item.get("start_expression") if item.get("kind") == "period" else item.get("date_expression")
    match = _TIMELINE_DATE_PATTERN.search(expression or "")
    # These values are ordering hints only. Original date expressions remain
    # untouched; undated entries retain their relative order at the end.
    return (int(match[1]), int(match[2] or 7), int(match[3] or 1)) if match else (9999, 12, 31)


def normalise_family_context_document(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Read v1 and v2 documents through the single canonical timeline contract."""
    if document is None:
        return None
    result = copy.deepcopy(document)
    timeline = result.get("timeline", [])
    for item in timeline:
        item.setdefault("kind", "event")
    timeline.extend({**item, "kind": "period"} for item in result.pop("life_periods", []))
    result["timeline"] = sorted(timeline, key=_timeline_order)
    result["schema_version"] = FAMILY_CONTEXT_SCHEMA_VERSION
    return result


def _stable_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _stable_id(kind: str, update_hash: str, source_id: str) -> str:
    # Keep the generated id within the marker's bounded identifier contract.
    return f"{kind}_{update_hash[:16]}_{_stable_hash(source_id)[:8]}"


def _records_equal(left: list[dict[str, Any]], right: list[dict[str, Any]]) -> bool:
    return left == right


def merge_family_context_document(
    existing: dict[str, Any] | None,
    update: dict[str, Any],
    project_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Merge one validated marker into the persisted, renderable document.

    The marker's ids are correlation keys for one turn. A marker can revise a
    previously persisted record only by supplying its canonical ``existing_id``.
    New ids are deterministic for the same marker, which makes a retried turn
    idempotent without guessing that two similarly named relatives are the
    same person.
    """
    if valid_family_project_id(project_id) is None:
        raise ValueError("Invalid Family project id")
    validated_update = validate_family_context(update, allow_external_person_refs=True)
    if validated_update is None:
        raise ValueError("Family context update is invalid")
    # Queued workspace jobs may contain an already validated v1 update.
    update = validated_update

    base = empty_family_context_document(project_id)
    if isinstance(existing, dict):
        existing = normalise_family_context_document(existing)
        base.update({key: copy.deepcopy(existing[key]) for key in base if key in existing})
        base["project_id"] = project_id
        base["schema_version"] = FAMILY_CONTEXT_SCHEMA_VERSION
        base["revision"] = int(existing.get("revision") or 0)
        if isinstance(existing.get("updated_at"), str):
            base["updated_at"] = existing["updated_at"]
        for key in _CONTEXT_KEYS:
            if not isinstance(base.get(key), list):
                base[key] = []

    # Retain v1 deterministic IDs so replaying a pre-upgrade marker cannot
    # create a second copy of an already persisted event or period.
    update_hash = _stable_hash({
        **update,
        "timeline": [{key: value for key, value in item.items() if key != "kind"}
                     for item in update["timeline"] if item["kind"] == "event"],
        "life_periods": [{key: value for key, value in item.items() if key != "kind"}
                        for item in update["timeline"] if item["kind"] == "period"],
    })
    people = base["people"]
    person_by_id = {item.get("id"): item for item in people if isinstance(item, dict) and item.get("id")}
    temporary_to_canonical: dict[str, str] = {}
    added = {key: 0 for key in ("people", "relationships", "timeline")}
    updated = {key: 0 for key in added}

    for raw in update["people"]:
        # A name is not an identity key. The same name can legitimately refer
        # to a parent and a child, or to two unrelated people across turns.
        # Revisions must carry explicit existing_id (or repeat the canonical
        # marker id); deterministic ids still make an exact marker retry
        # idempotent without guessing which person the storyteller meant.
        requested_id = raw["existing_id"] if raw.get("existing_id") in person_by_id else raw["id"]
        canonical_id = requested_id if requested_id in person_by_id else _stable_id("person", update_hash, raw["id"])
        temporary_to_canonical[raw["id"]] = canonical_id
        record = {key: copy.deepcopy(value) for key, value in raw.items() if key != "existing_id"}
        record["id"] = canonical_id
        if canonical_id in person_by_id:
            index = next(index for index, item in enumerate(people) if item.get("id") == canonical_id)
            merged = {**people[index], **record}
            if merged != people[index]:
                people[index] = merged
                updated["people"] += 1
        else:
            people.append(record)
            person_by_id[canonical_id] = record
            added["people"] += 1

    relationships = base["relationships"]
    for raw in update["relationships"]:
        from_id = temporary_to_canonical.get(raw["from_person_id"], raw["from_person_id"])
        to_id = temporary_to_canonical.get(raw["to_person_id"], raw["to_person_id"])
        record = {key: copy.deepcopy(value) for key, value in raw.items() if key != "existing_id"}
        record["from_person_id"] = from_id
        record["to_person_id"] = to_id
        key = (from_id, to_id, record["relationship_type"], record.get("maternal_paternal"))
        existing_relation = next((item for item in relationships if (
            item.get("from_person_id"), item.get("to_person_id"),
            item.get("relationship_type"), item.get("maternal_paternal")
        ) == key), None)
        requested_id = raw.get("existing_id")
        if existing_relation is not None:
            canonical_id = existing_relation.get("id") or requested_id or _stable_id("relationship", update_hash, json.dumps(key))
            record["id"] = canonical_id
            index = relationships.index(existing_relation)
            merged = {**existing_relation, **record}
            if merged != existing_relation:
                relationships[index] = merged
                updated["relationships"] += 1
        else:
            record["id"] = requested_id if requested_id and any(item.get("id") == requested_id for item in relationships) else _stable_id("relationship", update_hash, json.dumps(key))
            relationships.append(record)
            added["relationships"] += 1

    def merge_date_records(collection_key: str, raw_items: list[dict[str, Any]]) -> None:
        collection = base[collection_key]
        by_id = {item.get("id"): item for item in collection if isinstance(item, dict) and item.get("id")}
        for raw in raw_items:
            kind = "period" if raw["kind"] == "period" else "timeline"
            requested_id = raw["existing_id"] if raw.get("existing_id") in by_id else raw["id"]
            canonical_id = requested_id if requested_id in by_id else _stable_id(kind, update_hash, raw["id"])
            record = {key: copy.deepcopy(value) for key, value in raw.items() if key != "existing_id"}
            record["id"] = canonical_id
            if "person_ids" in record:
                record["person_ids"] = [temporary_to_canonical.get(item, item) for item in record["person_ids"]]
            if canonical_id in by_id:
                index = next(index for index, item in enumerate(collection) if item.get("id") == canonical_id)
                if collection[index]["kind"] != record["kind"]:
                    raise ValueError("An existing timeline item's kind cannot change")
                merged = {**collection[index], **record}
                if merged != collection[index]:
                    collection[index] = merged
                    updated[collection_key] += 1
            else:
                collection.append(record)
                by_id[canonical_id] = record
                added[collection_key] += 1

    for raw in update["timeline"]:
        for person_id in raw.get("person_ids", []):
            canonical_person_id = temporary_to_canonical.get(person_id, person_id)
            if canonical_person_id not in person_by_id:
                raise ValueError("Timeline record references an unknown person")

    merge_date_records("timeline", update["timeline"])

    changed = any(added[key] or updated[key] for key in added)
    old_revision = int(base.get("revision") or 0)
    document = {
        "schema_version": FAMILY_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "revision": old_revision + 1 if changed else old_revision,
        "people": people,
        "relationships": relationships,
        "timeline": sorted(base["timeline"], key=_timeline_order),
    }
    if not changed and isinstance(base.get("updated_at"), str):
        document["updated_at"] = base["updated_at"]
    summary = {
        "schema_version": FAMILY_CONTEXT_SCHEMA_VERSION,
        "project_id": project_id,
        "changed": changed,
        "revision": document["revision"],
        "added": added,
        "updated": updated,
    }
    return document, summary
