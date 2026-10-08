"""Code scores for Issue6 outputs; semantic acceptance requires human review.

These functions do not invoke a model, authorize live execution or prove that
valid source citations entail every generated claim.
"""
from __future__ import annotations

import re

from apps.api.memory_events import validate_extraction


def _matches_placement(event, gold):
    anchor = gold.get("evidence_anchor", "")
    # Event, stage and timing citations have separate roles in the public
    # proposal contract. A date identity anchor may live only in timing basis.
    refs = [*event.get("source_refs", []), *(event.get("stage_evidence") or []),
            *((event.get("temporal") or {}).get("basis") or [])]
    quotes = [ref.get("quote", "") for ref in refs]
    if anchor and not any(anchor in quote for quote in quotes):
        return False
    if event.get("kind") != gold["kind"]:
        return False
    stage = event.get("life_stage") or "unplaced"
    if stage != gold.get("life_stage", "unplaced"):
        return False
    temporal = event.get("temporal") or {}
    if gold.get("year_unknown") and any(temporal.get(k) is not None
                                       for k in ("year_start", "year_end")):
        return False
    for key, value in gold.get("temporal", {}).items():
        actual = temporal.get(key)
        if key == "expression":
            # Both "1958" and "in 1958" preserve the source date. The exact
            # year/precision checks and original-evidence validation still apply.
            expressions = [value, *gold.get("date_expression_alternatives", [])]
            if not isinstance(actual, str) or not any(re.search(
                    r"(?<!\d)" + re.escape(expression) + r"(?!\d)", actual)
                    for expression in expressions):
                return False
        elif actual != value:
            return False
    if gold.get("uncertainty_required") and not str(event.get("uncertainty") or "").strip():
        return False
    return True


def _placements_match(events, gold):
    if len(events) != len(gold):
        return False
    # One-to-one assignment; opaque IDs, title wording and output order are
    # deliberately not equality targets across projects or languages.
    owners = {}

    def assign(gold_index, visited):
        for index, event in enumerate(events):
            if index in visited or not _matches_placement(event, gold[gold_index]):
                continue
            visited.add(index)
            if index not in owners or assign(owners[index], visited):
                owners[index] = gold_index
                return True
        return False

    return all(assign(index, set()) for index in range(len(gold)))


def score_events(inputs, output, expected_output):
    if output is None:
        return {
            name: {"value": None, "status": "unavailable"}
            for name in ("schema_and_original_evidence", "event_count",
                         "expected_placement", "factual_entailment")
        }
    sources = [*inputs.get("context_sources", []), *inputs.get("sources", [])]
    try:
        # Score the same normalized, retained proposals the application can
        # persist. Syntactically valid recording-vetoed proposals are withheld.
        events = validate_extraction(output, sources, inputs.get("saved_events", []))
        valid = True
    except (ValueError, TypeError, KeyError):
        events = None
        valid = False
    gold = expected_output["events"]
    placement = bool(valid and isinstance(events, list) and _placements_match(events, gold))
    return {
        "schema_and_original_evidence": {
            "value": int(valid), "status": "pass" if valid else "fail",
        },
        "event_count": {
            "value": int(isinstance(events, list)
                         and len(events) == len(gold)),
            "status": "scored",
        },
        "expected_placement": {
            "value": int(placement) if gold else None,
            "status": ("pass" if placement else "fail") if gold else "not_applicable",
        },
        "factual_entailment": {
            "value": None, "status": "human_review_required",
            "comment": "Valid citations alone do not prove factual entailment.",
        },
    }
