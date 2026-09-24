#!/usr/bin/env python3
"""Credential-free smoke checks for the Apple Container stack."""

from __future__ import annotations

import argparse
import json
import socket
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def get(url: str) -> tuple[int, bytes, dict[str, str]]:
    try:
        with urlopen(url, timeout=10) as response:
            return response.status, response.read(), dict(response.headers)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"GET {url} failed: {exc}") from exc


def wait_for(url: str, attempts: int = 30) -> tuple[int, bytes, dict[str, str]]:
    last_error: RuntimeError | None = None
    for _ in range(attempts):
        try:
            return get(url)
        except RuntimeError as exc:
            last_error = exc
            time.sleep(1)
    assert last_error is not None
    raise last_error


def wait_for_tcp(host: str, port: int, attempts: int = 30) -> None:
    last_error: OSError | None = None
    for _ in range(attempts):
        try:
            with socket.create_connection((host, port), timeout=3):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(1)
    assert last_error is not None
    raise RuntimeError(f"TCP {host}:{port} failed: {last_error}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="http://127.0.0.1:8010")
    parser.add_argument("--web-base", default="http://127.0.0.1:3010")
    parser.add_argument("--harness-host", default="127.0.0.1")
    parser.add_argument("--harness-port", type=int, default=8765)
    parser.add_argument("--expected-storage")
    args = parser.parse_args()

    api_status, api_body, _ = wait_for(f"{args.api_base}/health")
    if api_status != 200:
        raise RuntimeError(f"API health returned {api_status}")
    health = json.loads(api_body)
    if health.get("status") != "ok":
        raise RuntimeError(f"unexpected API health payload: {health}")
    if args.expected_storage and health.get("storage") != args.expected_storage:
        raise RuntimeError(f"expected storage {args.expected_storage}, got {health.get('storage')}")

    config_status, config_body, config_headers = get(f"{args.api_base}/api/v1/memoir/config")
    if config_status != 200:
        raise RuntimeError(f"API config returned {config_status}")
    if config_headers.get("X-API-Namespace") != "memoir":
        raise RuntimeError("API config did not use the memoir product namespace")
    config = json.loads(config_body)
    if "trial_primary_sessions" not in config:
        raise RuntimeError("API config is missing trial_primary_sessions")

    web_status, web_body, _ = wait_for(f"{args.web_base}/")
    if web_status != 200 or b"CopyMe2" not in web_body:
        raise RuntimeError(f"web shell returned {web_status} without CopyMe2")

    proxied_status, proxied_body, _ = wait_for(f"{args.web_base}/api/v1/memoir/config")
    if proxied_status != 200 or b"trial_primary_sessions" not in proxied_body:
        raise RuntimeError("web-to-API proxy is not serving /api/v1/memoir/config")

    wait_for_tcp(args.harness_host, args.harness_port)

    print("Memory Spark container stack: healthy")
    print(f"  API: {args.api_base}/health")
    print(f"  Web: {args.web_base}/")
    print(f"  Codex harness: ws://{args.harness_host}:{args.harness_port}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RuntimeError as exc:
        print(f"container stack check failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
