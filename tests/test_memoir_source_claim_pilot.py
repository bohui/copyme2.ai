"""Eight bilingual, synthetic source-claim protocol probes for issue #13.

These exercise validators with explicit proposals. They are not a live-model
pilot, extraction-quality evidence, or human calibration.
"""
import json

import pytest

from apps.api.codex_runtime import (
    _sanitize_author_timeline_markers,
    build_workspace_extraction_prompt,
)
from apps.api.memory_events import validate_extraction


INPUTS = {
    "en-AU": {
        "attributed": "Aunt June recalls my first day at school in 1980.",
        "attribution": "Aunt June",
        "purchase": "I bought a house in 1980.",
        "sale": "I sold the house in 1980.",
        "veto": "Please do not add this event to my timeline.",
    },
    "zh-CN": {
        "attributed": "阿姨记得我在1980年第一天上学的情景。",
        "attribution": "阿姨",
        "purchase": "我在1980年买了一套房子。",
        "sale": "我在1980年卖掉了这套房子。",
        "veto": "不要把这件事加入我的时间线。",
    },
}
SCENARIOS = ("attributed_timing", "unsupported_source", "item_veto", "null_claim")


def _ref(quote, **values):
    return {"source_id": "pilot-original", "version": 1, "quote": quote, **values}


def _event(title, quote, **values):
    return {"kind": "event", "title": title, "source_refs": [_ref(quote)], **values}


def _validate(text, events):
    return validate_extraction(
        {"events": events},
        [{"id": "pilot-original", "version": 1, "text": text, "status": "active"}],
        [],
    )


def _marker(items):
    return "[[MEMORY_SPARK_AUTHOR_TIMELINE]]" + json.dumps({"timeline": items}, ensure_ascii=False) + "[[/MEMORY_SPARK_AUTHOR_TIMELINE]]"


def _legacy_item(identifier, claim):
    return {"id": identifier, "kind": "event", "title": identifier, "date_expression": "1980", "precision": "year", "source_claim_id": claim}


@pytest.mark.parametrize("locale", INPUTS)
@pytest.mark.parametrize("scenario", SCENARIOS)
def test_bilingual_source_claim_protocol_pilot(locale, scenario):
    words = INPUTS[locale]
    if scenario == "attributed_timing":
        quote = words["attributed"]
        ref = _ref(quote, attribution=words["attribution"])
        proposal = _event("First day at school", quote, attribution=words["attribution"], temporal={
            "expression": "1980", "precision": "year", "year_start": 1980, "basis": [ref],
        })
        result = _validate(quote, [proposal])
        assert len(result) == 1
        assert result[0]["source_refs"][0]["quote"] == quote
        assert result[0]["temporal"]["basis"] == [ref]
        assert result[0]["attribution"] == words["attribution"]
    elif scenario == "unsupported_source":
        # Plausible prose and an exact quote do not repair a wrong source/version.
        proposal = _event("Purchase", words["purchase"])
        for invalid in ({"source_id": "not-authorized"}, {"version": 2}, {"quote": words["sale"]}):
            proposal["source_refs"] = [{**_ref(words["purchase"]), **invalid}]
            with pytest.raises(ValueError, match="Evidence must match an authorised original source version"):
                _validate(words["purchase"], [proposal])
        result = []
    elif scenario == "item_veto":
        text = " ".join((words["purchase"], words["sale"], words["veto"]))
        result = _validate(text, [_event("Purchase", words["purchase"]), _event("Sale", words["sale"])])
        assert [item["title"] for item in result] == ["Purchase"]
        # A permitted event cannot borrow vetoed timing evidence from the sale.
        assert _validate(text, [_event("Purchase", words["purchase"], temporal={
            "expression": "1980", "precision": "year", "year_start": 1980, "basis": [_ref(words["sale"])],
        })]) == []
        prompt = build_workspace_extraction_prompt("(none)", family_enabled=True, source_text=text)
        assert "- c0:" in prompt and "- c1:" in prompt
        sanitized = _sanitize_author_timeline_markers(_marker([_legacy_item("purchase", "c0"), _legacy_item("sale", "c1")]), text)
        assert '"id":"purchase"' in sanitized
        assert '"id":"sale"' not in sanitized
        assert "source_claim_id" not in sanitized
        assert "_resolved_source_span_indices" not in sanitized
    else:
        for field in ("source_claim_id", "_source_claim_id"):
            item = _legacy_item("purchase", None)
            item[field] = item.pop("source_claim_id")
            assert _sanitize_author_timeline_markers(_marker([item]), words["purchase"]) == ""
        result = []
    assert "source_claim_id" not in json.dumps(result)
    assert "_resolved_source_span_indices" not in json.dumps(result)
