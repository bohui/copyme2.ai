#!/usr/bin/env python3
"""One bounded, synthetic probe for provider-native Responses web search.

This is deliberately separate from the Memoir runner. It sends one public,
non-memoir question through the configured provider and records only response
metadata, tool item types, citation hosts and a bounded error summary. A 200
without an observed web-search item is inconclusive, not a pass.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

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


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def response_evidence(body: dict) -> dict[str, object]:
    items = list(walk(body.get("output", [])))
    item_types = sorted({str(item.get("type")) for item in items if item.get("type")})
    search_items = [
        item for item in items
        if str(item.get("type", "")).lower() in {
            "web_search_call", "web_search", "web_search_preview",
        }
        or "web_search" in str(item.get("type", "")).lower()
    ]
    citations: list[str] = []
    for item in items:
        for key in ("url", "source_url"):
            value = item.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                host = urlsplit(value).netloc.lower()
                if host and host not in citations:
                    citations.append(host)
        annotation = item.get("annotations")
        if isinstance(annotation, list):
            for entry in annotation:
                if isinstance(entry, dict):
                    url = entry.get("url")
                    if isinstance(url, str) and url.startswith(("http://", "https://")):
                        host = urlsplit(url).netloc.lower()
                        if host and host not in citations:
                            citations.append(host)
    output_text = body.get("output_text")
    return {
        "response_id_present": bool(body.get("id")),
        "response_model": body.get("model"),
        "item_types": item_types,
        "web_search_item_count": len(search_items),
        "citation_host_count": len(citations),
        "citation_hosts": citations[:20],
        "output_text_present": isinstance(output_text, str) and bool(output_text.strip()),
    }


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    args = parser.parse_args()

    file_env = read_env(Path(args.env_file))
    base_url = (os.getenv("MEMORY_SPARK_LLM_BASE_URL") or file_env.get("MEMORY_SPARK_LLM_BASE_URL") or "").rstrip("/")
    model = os.getenv("MEMORY_SPARK_LLM_MODEL") or file_env.get("MEMORY_SPARK_LLM_MODEL") or ""
    api_key = os.getenv("MEMORY_SPARK_LLM_API_KEY") or file_env.get("MEMORY_SPARK_LLM_API_KEY") or ""
    request_body = {
        "model": model,
        "input": "For this synthetic capability check only: what is the capital of Australia? If web search is used, include source citations.",
        "tools": [{"type": "web_search"}],
        "max_output_tokens": 120,
    }
    receipt: dict[str, object] = {
        "schema_version": "memoir-provider-web-search-probe/1",
        "recorded_at": utc_now(),
        "base_url": base_url,
        "model": model,
        "request_kind": "one synthetic Responses web_search capability probe; not a Memoir round",
        "request_contract": {"tool_type": "web_search", "private_data": False, "max_output_tokens": 120},
        "timeout_seconds": args.timeout,
        "api_key_configured": bool(api_key),
    }
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=args.timeout) as client:
            response = await client.post(
                base_url + "/responses",
                headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                json=request_body,
            )
        receipt.update({
            "http_status": response.status_code,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
        })
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        if response.status_code == 200 and isinstance(body, dict):
            evidence = response_evidence(body)
            receipt["response_evidence"] = evidence
            if evidence["web_search_item_count"] > 0 and evidence["citation_host_count"] > 0:
                receipt["status"] = "pass"
            else:
                receipt["status"] = "inconclusive_no_search_evidence"
        else:
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict):
                receipt["error_type"] = error.get("type") or error.get("code")
                receipt["error_message"] = str(error.get("message", ""))[:240]
            else:
                receipt["error_type"] = "http_error"
                receipt["error_message"] = response.text[:240]
            receipt["status"] = "unsupported_or_unavailable"
    except Exception as error:
        receipt.update({
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "status": "unavailable",
            "error_type": type(error).__name__,
            "error_message": str(error)[:240],
        })

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in receipt.items() if key not in {"request_contract"}}, ensure_ascii=False, indent=2))
    return 0 if receipt.get("status") == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

