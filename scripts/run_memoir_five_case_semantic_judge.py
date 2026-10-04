#!/usr/bin/env python3
"""Run a bounded, non-gating semantic judge over saved Memoir traces.

This adapter deliberately reuses ``OpenAICompatibleJudge`` from the existing
trajectory-evaluation facility.  It samples saved round traces instead of
making one paid call per application round, sends only the visible scenario
and observable trajectory, and writes a separate receipt.  Deterministic
contract grades remain authoritative; an unreviewed calibration manifest can
never turn this exploratory result into a pass.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.trajectory_evaluation import (  # noqa: E402
    JUDGE_RUBRIC,
    JUDGE_RUBRIC_VERSION,
    OpenAICompatibleJudge,
    build_application_revision,
    build_judge_input,
    load_judge_calibration,
    redact_payload,
)
from scripts.memoir_five_case_evaluator import SKILLS  # noqa: E402


INPUTS_PATH = ROOT / "tests/evaluation/memoir_five_case_inputs.json"
CALIBRATION_PATH = ROOT / "tests/evaluation/memoir_five_case_judge_calibration.json"
JUDGE_TEMPLATE_PATH = ROOT / "tests/evaluation/memoir_five_case_judge_prompt.md"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def sha256_json(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def env_value(name: str, env: Mapping[str, str]) -> str:
    return str(os.environ.get(name, env.get(name, ""))).strip()


def trace_files(run_dir: Path) -> list[Path]:
    return sorted(run_dir.glob("cases/*/rounds/round-*.json"), key=lambda path: (
        path.parent.parent.name,
        int(path.stem.split("-")[-1]),
    ))


def coverage_keys(trace: Mapping[str, Any]) -> set[str]:
    expected = trace.get("expected_outcome") if isinstance(trace.get("expected_outcome"), Mapping) else {}
    statuses = expected.get("skill_status") if isinstance(expected.get("skill_status"), Mapping) else {}
    keys = set()
    for skill, status in statuses.items():
        if status in {"required", "must_not_call"}:
            keys.add(f"{skill}:{status}")
    if expected.get("composer_action"):
        keys.add(f"memoir-composer:{expected['composer_action']}")
    if expected.get("photo_action") and expected.get("photo_action") != "none":
        keys.add(f"place-photo-research:{expected['photo_action']}")
    if str((trace.get("input") or "")).isascii() is False:
        keys.add("language:non-ascii")
    grade = trace.get("grade") if isinstance(trace.get("grade"), Mapping) else {}
    if grade.get("overall") not in {None, "pass"}:
        keys.add(f"deterministic:{grade.get('overall')}")
    return keys


def select_samples(paths: list[Path], maximum: int) -> list[Path]:
    """Greedily cover cases, skills, negative calls, composer and failures."""
    traces = [(path, load_json(path)) for path in paths]
    selected: list[Path] = []
    selected_ids: set[str] = set()
    covered: set[str] = set()
    case_ids = sorted({str(data.get("case_id") or path.parent.parent.name) for path, data in traces})

    while traces and len(selected) < maximum:
        def score(item: tuple[Path, Mapping[str, Any]]) -> tuple[int, int, str]:
            path, trace = item
            case_id = str(trace.get("case_id") or path.parent.parent.name)
            grade = trace.get("grade") if isinstance(trace.get("grade"), Mapping) else {}
            expected = trace.get("expected_outcome") if isinstance(trace.get("expected_outcome"), Mapping) else {}
            keys = coverage_keys(trace)
            value = len(keys - covered) * 20
            if case_id not in selected_ids:
                value += 100
            if grade.get("overall") not in {None, "pass"}:
                value += 35
            if expected.get("composer_action"):
                value += 25
            if expected.get("photo_action") and expected.get("photo_action") != "none":
                value += 15
            if str(trace.get("input") or "").isascii() is False:
                value += 8
            round_number = int(trace.get("round") or 0)
            return value, -round_number, f"{case_id}:{round_number:04d}"

        path, trace = max(traces, key=score)
        traces.remove((path, trace))
        selected.append(path)
        case_id = str(trace.get("case_id") or path.parent.parent.name)
        selected_ids.add(case_id)
        covered.update(coverage_keys(trace))

    # Keep the selection deterministic for the receipt and human inspection.
    return sorted(selected, key=lambda path: (path.parent.parent.name, int(path.stem.split("-")[-1])))


def observable_trajectory(trace: Mapping[str, Any]) -> dict[str, Any]:
    response = trace.get("response") if isinstance(trace.get("response"), Mapping) else {}
    trajectory = response.get("trajectory") if isinstance(response.get("trajectory"), Mapping) else None
    if trajectory is not None:
        return dict(trajectory)
    # An unavailable application round has no semantic trajectory to judge.
    # The placeholder is only used to construct a bounded, explicit receipt;
    # such a sample is marked not_judged before calling the provider.
    return {
        "schema_version": "memoir-trajectory/1",
        "context": {},
        "steps": [],
        "final": {
            "status": "error",
            "response": response.get("reply"),
            "state": response.get("state") if isinstance(response, Mapping) else {},
            "stop_reason": "unavailable",
        },
    }


def compact_trajectory(trajectory: Mapping[str, Any]) -> dict[str, Any]:
    """Keep observable evidence while removing repeated per-step context.

    Worker traces repeat the same enabled-skill/task context on every step.
    Sending that duplicate context to a reasoning model is expensive and does
    not improve a semantic score; the task and final state remain explicit.
    """
    compact_steps: list[dict[str, Any]] = []
    for raw in trajectory.get("steps", []) if isinstance(trajectory.get("steps"), list) else []:
        if not isinstance(raw, Mapping):
            continue
        step: dict[str, Any] = {}
        for key in ("step_id", "sequence", "action", "phase", "error"):
            if key in raw:
                step[key] = raw[key]
        if isinstance(raw.get("normalized_action"), Mapping):
            step["normalized_action"] = dict(raw["normalized_action"])
        output = raw.get("output")
        if isinstance(output, Mapping):
            # Action outputs are normally small; cap any accidental transcript
            # field without carrying the repeated pre-action context.
            step["output"] = {
                str(key): value for key, value in list(output.items())[:24]
                if key not in {"reasoning", "analysis", "prompt", "content"}
            }
        elif output is not None:
            step["output"] = str(output)[:800]
        compact_steps.append(step)
    final = trajectory.get("final") if isinstance(trajectory.get("final"), Mapping) else {}
    final_state = final.get("state") if isinstance(final.get("state"), Mapping) else {}
    compact_final = {
        key: final.get(key)
        for key in ("status", "response", "stop_reason")
        if key in final
    }
    compact_final["state"] = dict(final_state)
    return {
        "schema_version": trajectory.get("schema_version"),
        "context": {"project_id": (trajectory.get("context") or {}).get("project_id")},
        "steps": compact_steps,
        "final": compact_final,
    }


def validate_judge_result(result: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    status = str(result.get("status") or "scored")
    if status != "scored":
        return status, {"status": status, "comment": str(result.get("comment") or "")[:1000]}
    scores = result.get("scores") if isinstance(result.get("scores"), Mapping) else {}
    comments = result.get("comments") if isinstance(result.get("comments"), Mapping) else {}
    evidence = result.get("evidence")
    problems: list[str] = []
    normalized: dict[str, float] = {}
    for category in JUDGE_RUBRIC:
        value = scores.get(category)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            problems.append(f"invalid score: {category}")
        else:
            normalized[category] = float(value)
    if not isinstance(evidence, list) or not evidence:
        problems.append("missing evidence list")
    if problems:
        return "invalid", {
            "status": "invalid",
            "problems": problems,
            "scores": normalized,
            "comments": {str(key): str(value)[:1000] for key, value in comments.items()},
            "evidence": [str(item)[:200] for item in evidence] if isinstance(evidence, list) else [],
        }
    return "scored", {
        "status": "scored",
        "scores": normalized,
        "comments": {category: str(comments.get(category) or "")[:1000] for category in JUDGE_RUBRIC},
        "evidence": [str(item)[:200] for item in evidence[:20]],
    }


async def judge_one(
    judge: OpenAICompatibleJudge,
    trace: Mapping[str, Any],
    *,
    timeout: float,
    retries: int,
) -> dict[str, Any]:
    case_id = str(trace.get("case_id") or "unknown")
    round_number = int(trace.get("round") or 0)
    deterministic = trace.get("grade", {}).get("overall") if isinstance(trace.get("grade"), Mapping) else None
    response = trace.get("response") if isinstance(trace.get("response"), Mapping) else {}
    if trace.get("error") or not response.get("trajectory"):
        return {
            "case_id": case_id,
            "round": round_number,
            "deterministic_overall": deterministic,
            "status": "not_judged",
            "reason": "No completed observable trajectory was saved for this round.",
            "attempts": 0,
        }
    expected = trace.get("expected_outcome") if isinstance(trace.get("expected_outcome"), Mapping) else {}
    task = {
        "case_id": case_id,
        "round": round_number,
        "storyteller_text": trace.get("input"),
        "expected_outcome": expected,
        "ui_observations": trace.get("ui") if isinstance(trace.get("ui"), Mapping) else {},
        "composer_checkpoint": trace.get("composer") if isinstance(trace.get("composer"), Mapping) else None,
    }
    judge_input = build_judge_input(
        task=task,
        trajectory=compact_trajectory(observable_trajectory(trace)),
        available_tools=list(SKILLS),
    )
    receipt = {
        "case_id": case_id,
        "round": round_number,
        "deterministic_overall": deterministic,
        "input_sha256": sha256_json(judge_input),
        "attempts": 0,
    }
    last_error: dict[str, Any] | None = None
    for attempt in range(retries + 1):
        receipt["attempts"] = attempt + 1
        started = time.monotonic()
        try:
            raw = await asyncio.wait_for(judge(judge_input), timeout=timeout)
            status, normalized = validate_judge_result(raw)
            receipt.update({"status": status, "result": normalized, "elapsed_ms": round((time.monotonic() - started) * 1000, 1)})
            receipt["provider_call"] = dict(judge.last_call)
            return receipt
        except Exception as error:
            last_error = {"type": type(error).__name__, "message": str(error)[:500]}
            receipt["provider_call"] = dict(judge.last_call)
            if attempt >= retries:
                break
    receipt.update({"status": "unavailable", "error": last_error or {"type": "unknown"}})
    return receipt


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    run_dir = args.run_dir.resolve()
    manifest_path = run_dir / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}
    env = parse_env(args.env_file)
    provider = manifest.get("provider") if isinstance(manifest.get("provider"), Mapping) else {}
    base_url = args.provider_url or str(provider.get("base_url") or env_value("MEMORY_SPARK_LLM_BASE_URL", env)).rstrip("/")
    model = args.provider_model or str(provider.get("model") or env_value("MEMORY_SPARK_LLM_MODEL", env))
    api_key = env_value("MEMORY_SPARK_LLM_API_KEY", env)
    template = JUDGE_TEMPLATE_PATH.read_text(encoding="utf-8")
    calibration_payload = load_json(CALIBRATION_PATH)
    calibration_status: dict[str, Any]
    try:
        calibration_examples = load_judge_calibration(calibration_payload)
        calibration_status = {"status": "approved", "examples": len(calibration_examples)}
    except Exception as error:
        # Retain known failures as provisional prompt context so the run can
        # investigate judge behavior, but never call the result calibrated.
        calibration_examples = [
            item for item in calibration_payload.get("examples", [])
            if isinstance(item, Mapping)
        ]
        calibration_status = {
            "status": "unavailable",
            "reason": type(error).__name__,
            "message": str(error)[:500],
            "provisional_examples": len(calibration_examples),
        }
    instructions = template + "\n\nOperational guard: this invocation is exploratory. The calibration manifest is not human-reviewed; never treat any judge score as calibrated or as an acceptance pass, and say unavailable when observable evidence is insufficient."
    judge = OpenAICompatibleJudge(
        base_url=base_url,
        model=model,
        api_key=api_key,
        calibration_examples=calibration_examples,
        timeout=args.timeout,
        instructions=instructions,
        max_tokens=args.max_tokens,
        reasoning_effort=args.reasoning_effort,
    )
    paths = trace_files(run_dir)
    if args.case_id:
        paths = [path for path in paths if path.parent.parent.name == args.case_id]
    if args.round_number is not None:
        paths = [path for path in paths if int(path.stem.split("-")[-1]) == args.round_number]
    selected = select_samples(paths, args.max_rounds)
    results: list[dict[str, Any]] = []
    for path in selected:
        trace = load_json(path)
        results.append(await judge_one(judge, trace, timeout=args.timeout + 5, retries=args.max_retries))
    scored = [item for item in results if item.get("status") == "scored"]
    unavailable = [item for item in results if item.get("status") in {"unavailable", "not_judged"}]
    invalid = [item for item in results if item.get("status") == "invalid"]
    summary = {
        "schema_version": "memoir-five-case-semantic-judge/1",
        "status": "provisional_scored" if scored else ("unavailable" if unavailable else "invalid"),
        "run_id": manifest.get("run_id") or run_dir.name,
        "run_dir": str(run_dir),
        "created_at": utc_now(),
        "application_revision": build_application_revision(ROOT),
        "judge_rubric_version": JUDGE_RUBRIC_VERSION,
        "judge": {
            "class": "apps.api.trajectory_evaluation.OpenAICompatibleJudge",
            "base_url": base_url,
            "model": model,
            "reasoning_effort": args.reasoning_effort,
            "provider_changed": bool(args.provider_url or args.provider_model),
            "calls": judge.calls,
            "calibration": calibration_status,
            "acceptance_role": "non-gating; deterministic contract grades remain authoritative",
        },
        "sampling": {
            "available_round_traces": len(paths),
            "selected_round_traces": len(selected),
            "max_rounds": args.max_rounds,
            "selection": "greedy coverage of cases, required/must-not-call skills, composer/photo actions, language and deterministic failures",
        },
        "outcomes": {
            "scored": len(scored),
            "unavailable_or_not_judged": len(unavailable),
            "invalid": len(invalid),
        },
        "provider_usage": {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "cost": None,
            "note": "Token/cost fields are populated only when the configured endpoint returns usage; no provider or credential substitution was made.",
        },
        "deterministic_gate": {
            "authoritative": True,
            "judge_can_upgrade_failure": False,
            "judge_can_upgrade_unavailable": False,
        },
        "results": results,
        "replay": f"python scripts/run_memoir_five_case_semantic_judge.py --run-dir {run_dir} --env-file {args.env_file} --max-rounds {args.max_rounds}",
    }
    # Aggregate usage only from the safe numeric fields exposed by the
    # configured endpoint. The raw prompt and synthetic prose stay in the
    # already-saved round traces, not in a second judge transcript.
    usage = [
        item.get("provider_call", {}).get("usage")
        for item in results
        if isinstance(item.get("provider_call"), Mapping)
        and isinstance(item.get("provider_call", {}).get("usage"), Mapping)
    ]
    if usage:
        fields = {
            "input_tokens": ("prompt_tokens", "input_tokens"),
            "output_tokens": ("completion_tokens", "output_tokens"),
            "total_tokens": ("total_tokens",),
        }
        for target, names in fields.items():
            values = [
                int(entry[name]) for entry in usage for name in names
                if isinstance(entry.get(name), (int, float)) and not isinstance(entry.get(name), bool)
            ]
            if values:
                summary["provider_usage"][target] = sum(values)
    receipt_path = run_dir / "semantic-judge.json"
    receipt_path.write_text(json.dumps(redact_payload(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    parser.add_argument("--provider-url")
    parser.add_argument("--provider-model")
    parser.add_argument("--max-rounds", type=int, default=20)
    parser.add_argument("--case-id", help="Optionally judge one saved synthetic case")
    parser.add_argument("--round-number", type=int, help="Optionally judge one saved round")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--max-tokens", type=int, default=1200)
    parser.add_argument("--reasoning-effort", choices=("minimal", "low", "medium", "high", "max"), default="low")
    parser.add_argument("--max-retries", type=int, default=1)
    return parser


def main() -> int:
    args = parser().parse_args()
    if args.max_rounds < 1 or args.max_rounds > 30:
        raise SystemExit("--max-rounds must be between 1 and 30")
    if args.max_retries < 0 or args.max_retries > 1:
        raise SystemExit("--max-retries must be 0 or 1")
    summary = asyncio.run(main_async(args))
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["status"] in {"provisional_scored", "unavailable"} else 3


if __name__ == "__main__":
    raise SystemExit(main())
