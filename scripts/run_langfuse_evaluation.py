#!/usr/bin/env python3
"""Run Memoir trajectory cases through a local task callback.

The callback is intentionally supplied by the caller so a test can construct
an isolated UserStorage/worker fixture while production code keeps its normal
authentication and persistence boundaries. It must accept ``(case,
correlation)`` and return a mapping containing the normalized ``trajectory``
returned by ``CodexRuntime.turn(..., include_trajectory=True)``.
"""

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

from apps.api.trajectory_evaluation import LangfusePublisher, MemoirEvaluationRunner


def _load_callable(reference: str):
    module_name, separator, attribute = reference.partition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("--task must use module:callable syntax")
    module = importlib.import_module(module_name)
    callback = getattr(module, attribute, None)
    if not callable(callback):
        raise TypeError(f"Evaluation task is not callable: {reference}")
    return callback


def _load_cases(path: Path) -> list[Mapping[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, Mapping) else payload
    if not isinstance(cases, list) or not all(isinstance(case, Mapping) for case in cases):
        raise ValueError("Case file must contain a JSON array or {\"cases\": [...]}")
    return cases


async def _invoke(callback, case, correlation):
    result = callback(case, correlation)
    if inspect.isawaitable(result):
        return await result
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path, help="JSON file containing evaluation cases")
    parser.add_argument("--task", required=True, help="Python callback using module:callable syntax")
    parser.add_argument("--run-id", help="Stable run ID to reuse across retries")
    parser.add_argument("--output", type=Path, help="Write JSON results to this file instead of stdout")
    parser.add_argument("--publish", action="store_true", help="Publish observations and scores to Langfuse")
    return parser


async def _main(args: argparse.Namespace) -> list[dict[str, Any]]:
    callback = _load_callable(args.task)
    cases = _load_cases(args.cases)
    publisher = LangfusePublisher() if args.publish else None
    runner = MemoirEvaluationRunner(
        lambda case, correlation: _invoke(callback, case, correlation),
        publisher=publisher,
    )
    return await runner.run(cases, run_id=args.run_id)


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
