#!/usr/bin/env python3
"""Run the checked-in Memoir trajectory dataset through the app/worker seam."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import inspect
import json
from pathlib import Path
import sys
from typing import Any, Mapping

# ``python scripts/run_langfuse_evaluation.py`` puts ``scripts/`` first on
# sys.path; add the repository root so the callback can import ``apps`` and
# project-local evaluation modules without requiring PYTHONPATH.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from apps.api.trajectory_evaluation import (
    LangfusePublisher,
    MemoirEvaluationRunner,
    OpenAICompatibleJudge,
    comparison_matrix,
    load_judge_calibration,
)


def _load_callable(reference: str):
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("--task must use module:callable syntax")
    module = importlib.import_module(module_name)
    callback = getattr(module, attribute, None)
    if not callable(callback):
        raise TypeError(f"Evaluation task is not callable: {reference}")
    return callback


def _load_cases(path: Path) -> tuple[list[Mapping[str, Any]], Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, Mapping) else payload
    if not isinstance(cases, list) or not all(isinstance(case, Mapping) for case in cases):
        raise ValueError("Case file must contain a JSON array or {\"cases\": [...]}")
    defaults = {key: payload[key] for key in ("dataset", "dataset_version") if isinstance(payload, Mapping) and payload.get(key)}
    case_defaults = payload.get("case_defaults") if isinstance(payload, Mapping) else {}
    if not isinstance(case_defaults, Mapping):
        case_defaults = {}
    return [{**case_defaults, **defaults, **dict(case)} for case in cases], {**defaults, **dict(case_defaults)}


async def _invoke(callback, case, correlation):
    result = callback(case, correlation)
    if inspect.isawaitable(result):
        return await result
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=REPO_ROOT / "tests/evaluation/cases.json", help="JSON file containing evaluation cases")
    parser.add_argument("--task", default="apps.api.evaluation_cases:run_case", help="Python callback using module:callable syntax")
    parser.add_argument("--run-id", help="Stable run ID to reuse across retries")
    parser.add_argument("--output", type=Path, help="Write JSON results to this file instead of stdout")
    parser.add_argument("--failure-dir", type=Path, default=REPO_ROOT / "var/evaluation-failures", help="Directory for local per-case failure evidence")
    parser.add_argument("--variant", action="append", help="Model/provider variant name; repeat to build a comparison matrix")
    parser.add_argument("--baseline-variant", help="Variant used as the comparison baseline")
    parser.add_argument("--concurrency", type=int, default=1, help="Maximum concurrent isolated cases")
    parser.add_argument("--judge-base-url", help="Optional OpenAI-compatible judge base URL")
    parser.add_argument("--judge-model", help="Optional judge model; requires --judge-base-url")
    parser.add_argument("--judge-api-key", default="", help="Optional judge API key")
    parser.add_argument("--judge-calibration", type=Path, help="Optional JSON calibration examples for the semantic judge")
    parser.add_argument("--publish", action="store_true", help="Publish observations and scores to Langfuse")
    return parser


async def _main(args: argparse.Namespace) -> Any:
    callback = _load_callable(args.task)
    cases, _dataset_metadata = _load_cases(args.cases)
    publisher = LangfusePublisher() if args.publish else None
    judges = []
    if args.judge_base_url or args.judge_model:
        if not args.judge_base_url or not args.judge_model:
            raise ValueError("--judge-base-url and --judge-model must be supplied together")
        if not args.judge_calibration:
            raise ValueError("--judge-calibration is required when enabling the semantic judge")
        payload = json.loads(args.judge_calibration.read_text(encoding="utf-8"))
        calibration = load_judge_calibration(payload)
        judges.append(OpenAICompatibleJudge(
            base_url=args.judge_base_url,
            model=args.judge_model,
            api_key=args.judge_api_key,
            calibration_examples=calibration,
        ))
    runner = MemoirEvaluationRunner(
        lambda case, correlation: _invoke(callback, case, correlation),
        publisher=publisher,
        judges=judges,
    )
    variants = [{"variant": variant} for variant in args.variant] if args.variant else None
    results = await runner.run(cases, run_id=args.run_id, variants=variants, max_concurrency=args.concurrency)
    if publisher is not None:
        publisher.flush()
    args.failure_dir.mkdir(parents=True, exist_ok=True)
    for result in results:
        failures = result.get("failure_evidence") or []
        if not failures:
            continue
        variant = str((result.get("correlation") or {}).get("variant") or "default").replace("/", "_")
        path = args.failure_dir / f"{result['case_id']}-{variant}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.variant or args.baseline_variant:
        return {"results": results, "comparisons": comparison_matrix(results, baseline_variant=args.baseline_variant)}
    return results


def main() -> int:
    args = _parser().parse_args()
    results = asyncio.run(_main(args))
    encoded = json.dumps(results, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    else:
        print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
