#!/usr/bin/env python3
"""Run a pinned Langfuse text prompt against a pinned Langfuse dataset."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.langfuse_prompt_client import prompt_client
from scripts.prompt_registry import prompt_registry


def dataset_version(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("Dataset version must be a timezone-aware ISO timestamp")
    return parsed


def dataset_input_text(value) -> str:
    if isinstance(value, str) and value.strip():
        return value
    if isinstance(value, dict) and isinstance(value.get("text"), str):
        return value["text"]
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    raise ValueError("Each dataset item needs text or structured JSON input")


def experiment_task(prompt, model, client, *, target):
    system_text = prompt.prompt.rstrip() if target == "journalist" or target.endswith("Mira_Memoir_Journalist_System_Prompt_v1.0.md") else prompt.prompt
    def task(*, item, **_kwargs):
        input_text = dataset_input_text(item.input)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_text},
                      {"role": "user", "content": input_text}],
            langfuse_prompt=prompt,
        )
        return response.choices[0].message.content or ""
    return task


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="Stable Langfuse prompt name")
    parser.add_argument("--version", type=int, help="Exact prompt version; default: checked-in receipt")
    parser.add_argument("--dataset", required=True, help="Langfuse dataset name")
    parser.add_argument("--dataset-version", type=dataset_version,
                        help="Exact dataset snapshot timestamp; default: pin the current UTC time")
    parser.add_argument("--model", help="Provider model ID; required with --run")
    parser.add_argument("--base-url", help="Optional OpenAI-compatible provider URL")
    parser.add_argument("--provider-credential-file", type=Path,
                        help="Provider .env; defaults to the Langfuse credential file")
    parser.add_argument("--max-items", type=int, default=50,
                        help="Refuse datasets above this item count (default: 50)")
    parser.add_argument("--run", action="store_true", help="Dispatch model calls for the experiment")
    parser.add_argument("--credential-file", type=Path, help="Provider .env containing Memoir project credentials")
    args = parser.parse_args()
    if args.max_items < 1:
        parser.error("--max-items must be positive")
    registry = prompt_registry()
    if args.name not in registry:
        parser.error("--name must identify a managed Memoir prompt")
    if args.version is None:
        target = ROOT / registry[args.name]
        receipt = json.loads(target.with_name(target.name + ".langfuse.json").read_text())
        if receipt.get("name") != args.name:
            parser.error("Checked-in receipt belongs to a different prompt")
        args.version = receipt.get("version")
    if type(args.version) is not int or args.version < 1:
        parser.error("--version must be a positive exact version")
    if args.run and not args.model:
        parser.error("--model is required with --run")
    snapshot = args.dataset_version or datetime.now(timezone.utc)
    langfuse = prompt_client(args.credential_file)
    prompt = langfuse.get_prompt(args.name, version=args.version, type="text",
                                 cache_ttl_seconds=0, max_retries=0)
    if (getattr(prompt, "is_fallback", False) or prompt.name != args.name
            or prompt.version != args.version or not isinstance(prompt.prompt, str)):
        raise ValueError("Langfuse did not return the exact text prompt version")
    dataset = langfuse.get_dataset(args.dataset, version=snapshot)
    items = list(dataset.items)
    if not items:
        raise ValueError("Dataset has no items at the selected snapshot")
    for item in items:
        dataset_input_text(item.input)
    if len(items) > args.max_items:
        raise ValueError(f"Dataset has {len(items)} items, above --max-items={args.max_items}")
    summary = {"artifact": registry[args.name], "prompt": args.name, "prompt_version": args.version,
               "dataset": args.dataset, "dataset_version": snapshot.isoformat(),
               "items": len(items), "model": args.model or "not-selected"}
    print(json.dumps(summary, sort_keys=True), flush=True)
    if not args.run:
        return 0
    from dotenv import dotenv_values
    from langfuse.openai import OpenAI
    provider_file = args.provider_credential_file or args.credential_file
    provider_values = dotenv_values(provider_file, interpolate=False) if provider_file else {}
    api_key = provider_values.get("OPENAI_API_KEY") or provider_values.get("MEMORY_SPARK_LLM_API_KEY")
    if not api_key:
        raise ValueError("Provider credential file needs OPENAI_API_KEY or MEMORY_SPARK_LLM_API_KEY")
    base_url = (args.base_url or provider_values.get("OPENAI_BASE_URL")
                or provider_values.get("MEMORY_SPARK_LLM_BASE_URL"))
    client = OpenAI(api_key=api_key, **({"base_url": base_url} if base_url else {}))
    try:
        result = dataset.run_experiment(
            name=f"{args.name}-v{args.version}",
            run_name=f"{args.name}-v{args.version}-{snapshot.isoformat()}",
            description=json.dumps(summary, sort_keys=True),
            task=experiment_task(prompt, args.model, client, target=registry[args.name]),
            max_concurrency=1,
        )
        print(result.format())
    finally:
        langfuse.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
