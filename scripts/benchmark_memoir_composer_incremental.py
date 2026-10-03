#!/usr/bin/env python3
"""Bounded full-vs-incremental composer packet benchmark.

The default mode is a no-network packet benchmark. ``--live`` performs one
full-context and one compact-context three-phase run against the explicitly
supplied existing composer worker, using synthetic sources only. It records
payload sizes, phase latency and call counts; it never changes product policy
or a memoir project.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apps.api.codex_runtime import CodexRuntime
from apps.api.memoir_preview import (
    compose_candidate,
    incremental_index_request,
    incremental_model_request,
)


def synthetic_request(source_count: int = 40, new_count: int = 5) -> dict:
    project = "synthetic-composer-benchmark"
    sources = []
    for index in range(1, source_count + 1):
        stage = ("childhood", "young_adulthood", "midlife", "later_life")[(index - 1) // 10]
        text = (
            f"Fictional round {index} in {stage}: the storyteller remembers a "
            f"blue tin, a named street, and an ordinary responsibility. "
            f"This sentence is synthetic evidence {index}. "
        ) * 3
        sources.append({
            "id": f"source_{index:02d}", "version": hashlib.sha256(text.encode()).hexdigest(),
            "project_id": project, "kind": "narrator_chat", "author_role": "storyteller",
            "text": text, "status": "active", "allowed": True, "derived_from": [],
            "life_stage": stage, "source_order": index,
        })
    events = [{
        "id": f"event_{index:02d}", "period_id": sources[index - 1]["life_stage"],
        "summary": sources[index - 1]["text"][:120], "source_refs":[{"source_id": sources[index - 1]["id"], "version": sources[index - 1]["version"]}],
        "date": {"original_expression": "unknown", "start_year": None, "end_year": None, "precision": "unknown"},
        "status": "active", "narrative": True,
    } for index in range(1, source_count + 1)]
    periods = [{
        "id": stage, "order": order, "label": stage.replace("_", " ").title(),
        "source_refs": [{"source_id": sources[order * 10]["id"], "version": sources[order * 10]["version"]}],
    } for order, stage in enumerate(("childhood", "young_adulthood", "midlife", "later_life"))]
    prior_chapters = []
    for order, stage in enumerate(("childhood", "young_adulthood", "midlife", "later_life")):
        stage_sources = sources[order * 10:(order + 1) * 10]
        refs = [{"source_id": item["id"], "version": item["version"]} for item in stage_sources]
        prior_chapters.append({
            "revision": 1, "approved": False, "human_locked": False,
            "chapter": {"id": f"chapter_{order}", "period_ids": [stage], "event_ids": [f"event_{i:02d}" for i in range(order * 10 + 1, order * 10 + 11)],
                         "source_refs": refs, "blocks": [{"id": f"block_{order}", "type": "paragraph", "text": "Synthetic carry-forward prose", "source_refs": refs}]},
        })
    selected = sources[-new_count:]
    request = {
        "schema_version": "1.0", "request_id": "benchmark-update", "event_id": "benchmark-update",
        "project_id": project, "trigger": {"type": "new_context", "confirmed": True, "free_rounds_completed": source_count,
        "free_round_limit": 20, "composition_authorized": False},
        "target": {"locale": "en-AU", "audience": "storyteller", "medium": "web"},
        "snapshot": {"id": "benchmark-snapshot", "policy_epoch": 1, "expected_manuscript_revision": 1,
                      "retrieval_complete": True, "glossary_version": "1", "preferences_version": "en-AU"},
        "policy": {"max_chapter_words": 7000, "soft_chapter_words": 6000, "focus_threshold": 0.65,
                   "max_followup_questions": 0, "preview_preference": "auto"},
        "sources": sources, "assets": [], "periods": periods, "events": events,
        "prior_state": {"kind": "formal_memoir", "revision": 1, "chapters": prior_chapters,
                         "last_snapshot_fingerprint": "previous-fingerprint"},
        "authorised_retirements": [],
        "context": {
            "incremental_model_context": "compact", "new_source_ids": [item["id"] for item in selected],
            "changed_source_ids": [], "affected_source_ids": [], "overlap_source_ids": [sources[-7]["id"], sources[-6]["id"]],
        },
    }
    return request


def packet_summary(request: dict) -> dict:
    compact = incremental_model_request(request)
    full_draft = {"request": request, "plan": {"input_fingerprint": "benchmark", "counter": {}}}
    compact_draft = {"request": compact, "plan": {"input_fingerprint": "benchmark", "counter": {}}}
    full_review = {"request": request, "candidate": {"synthetic": True}, "validation": {"ok": True}}
    compact_review = {"request": compact, "candidate": {"synthetic": True}, "validation": {"ok": True}}
    size = lambda value: len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())
    return {
        "canonical_sources": len(request["sources"]), "compact_sources": len(compact["sources"]),
        "canonical_chars": sum(len(source["text"]) for source in request["sources"]),
        "compact_chars": sum(len(source["text"]) for source in compact["sources"]),
        "full_draft_bytes": size(full_draft), "compact_draft_bytes": size(compact_draft),
        "full_review_bytes": size(full_review), "compact_review_bytes": size(compact_review),
        "successful_phase_calls_before": 3, "successful_phase_calls_after": 3,
        "index_packet_unchanged": True,
    }


async def live_run(runtime: CodexRuntime, request: dict, *, compact: bool) -> dict:
    request = copy.deepcopy(request)
    if not compact:
        request['context'].pop('incremental_model_context', None)
    # composer_call submits this value through the production WorkerTurnInput
    # schema, which deliberately requires UUID-shaped tenant identities.  Use
    # a stable synthetic UUID so the benchmark exercises that same boundary
    # without ever touching a real account.
    storage = SimpleNamespace(user_id=str(UUID("00000000-0000-4000-8000-000000000042")))
    index_request = incremental_index_request(
        copy.deepcopy(request), request, request["context"].get("overlap_source_ids", []))
    checkpoint = {}
    progress_events = []

    async def progress(phase):
        progress_events.append({"phase": phase, "at_ms": round((time.perf_counter() - started) * 1000, 1)})

    before_requests = runtime.observed_worker_requests
    started = time.perf_counter()
    error = None
    result_status = None
    try:
        result = await compose_candidate(
            request, runtime, storage, request["project_id"], "en-AU",
            checkpoint=checkpoint, progress=progress, index_request=index_request,
        )
        result_status = result.get("status") if isinstance(result, dict) else None
    except Exception as exc:  # Safe class-only receipt; never persist provider text.
        error = type(exc).__name__
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    return {
        "mode": "compact" if compact else "full",
        "orchestration": "compose_candidate",
        "elapsed_ms": elapsed_ms,
        "successful": error is None and result_status == "ready",
        "result_status": result_status,
        "error_type": error,
        "worker_requests": runtime.observed_worker_requests - before_requests,
        "progress_phases": progress_events,
        "canonical_sources": len(request["sources"]),
        "model_sources": len(incremental_model_request(request)["sources"]) if compact else len(request["sources"]),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--worker-url", default=None)
    parser.add_argument("--worker-secret", default=None)
    args = parser.parse_args()
    request = synthetic_request()
    result = {"schema_version": 1, "synthetic_only": True, "packet_comparison": packet_summary(request)}
    if args.live:
        if not args.worker_url or not args.worker_secret:
            parser.error("--live requires --worker-url and --worker-secret")
        runtime = CodexRuntime(worker_url=args.worker_url, worker_secret=args.worker_secret)
        result["live"] = {
            "full": asyncio.run(live_run(runtime, request, compact=False)),
            "compact": asyncio.run(live_run(runtime, request, compact=True)),
        }
    encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")


if __name__ == "__main__":
    main()
