#!/usr/bin/env python3
"""Bounded synthetic smoke probe for the real private Codex worker path.

This is intentionally separate from the Memoir evaluator.  It sends one
non-memoir sentence through ``/internal/codex/turn`` and records only status,
latency, response shape, and error class; the model reply is never persisted.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from uuid import UUID

import httpx


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker-url", required=True)
    parser.add_argument("--worker-secret", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args()
    payload = {
        "user_id": str(UUID("00000000-0000-4000-8000-000000000043")),
        "project_id": "synthetic-worker-smoke",
        "family_enabled": False,
        "language": "en-AU",
        "text": "Return one short sentence acknowledging this synthetic worker smoke probe.",
        "model": args.model,
        "agent_role": "collector",
    }
    if payload["model"] is None:
        payload.pop("model")
    receipt: dict[str, object] = {
        "schema_version": "memoir-codex-worker-smoke-probe/1",
        "recorded_at": utc_now(),
        "worker_url": args.worker_url,
        "request_kind": "one synthetic non-memoir Codex worker turn",
        "timeout_seconds": args.timeout,
        "private_data": False,
    }
    started = time.monotonic()
    try:
        timeout = httpx.Timeout(args.timeout, connect=min(args.timeout, 5))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                args.worker_url.rstrip("/") + "/internal/codex/turn",
                headers={"X-Codex-Worker-Secret": args.worker_secret},
                json=payload,
            )
        receipt["http_status"] = response.status_code
        receipt["elapsed_ms"] = round((time.monotonic() - started) * 1000, 1)
        body = response.json() if response.content else {}
        reply = body.get("reply") if isinstance(body, dict) else None
        receipt["response_shape"] = {
            "thread_id_present": isinstance(body, dict) and bool(body.get("thread_id")),
            "reply_present": isinstance(reply, str) and bool(reply.strip()),
            "trajectory_present": isinstance(body, dict) and isinstance(body.get("trajectory"), dict),
        }
        if response.status_code == 200 and receipt["response_shape"]["reply_present"]:
            receipt["status"] = "pass"
        else:
            receipt["status"] = "unavailable"
            receipt["error_type"] = "worker_http_error"
            receipt["error_message"] = str((body.get("detail") if isinstance(body, dict) else ""))[:240]
    except Exception as error:
        receipt.update({
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "status": "unavailable",
            "error_type": type(error).__name__,
            "error_message": str(error)[:240],
        })
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt.get("status") == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
