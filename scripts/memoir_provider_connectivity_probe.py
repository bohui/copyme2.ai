#!/usr/bin/env python3
"""Bounded, synthetic connectivity receipt for the configured LLM gateway.

This is not a Memoir case runner and never sends memoir or customer content.
It records only endpoint/model reachability and the exact response to a
one-word synthetic probe so a live run cannot be mistaken for a fixture run.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import httpx


def read_env(path: Path) -> dict[str, str]:
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    file_env = read_env(Path(args.env_file))
    base_url = (os.getenv("MEMORY_SPARK_LLM_BASE_URL") or file_env.get("MEMORY_SPARK_LLM_BASE_URL") or "").rstrip("/")
    model = os.getenv("MEMORY_SPARK_LLM_MODEL") or file_env.get("MEMORY_SPARK_LLM_MODEL") or ""
    api_key = os.getenv("MEMORY_SPARK_LLM_API_KEY") or file_env.get("MEMORY_SPARK_LLM_API_KEY") or ""
    receipt: dict[str, object] = {
        "schema_version": "memoir-provider-connectivity-probe/1",
        "recorded_at": utc_now(),
        "base_url": base_url,
        "model": model,
        "request_kind": "synthetic connectivity probe; not a Memoir case round",
        "content_expected": "LIVE",
        "api_key_configured": bool(api_key),
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                base_url + "/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "Return exactly the word LIVE for this synthetic connectivity probe."}],
                    "temperature": 0,
                    "max_tokens": 4,
                },
            )
        body = response.json() if response.content else {}
        choice = (body.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        receipt.update({
            "http_status": response.status_code,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "response_id_present": bool(body.get("id")),
            "inference_model": body.get("model"),
            "finish_reason": choice.get("finish_reason"),
            "content": message.get("content"),
            "status": "pass" if response.status_code == 200 and message.get("content") == "LIVE" else "fail",
        })
    except Exception as error:
        receipt.update({
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "status": "unavailable",
            "error_type": type(error).__name__,
            "error": str(error)[:240],
        })
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in receipt.items() if k not in {"content"}}, ensure_ascii=False, indent=2))
    return 0 if receipt.get("status") == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
