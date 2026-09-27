#!/usr/bin/env python3
"""Validate that every supported UI locale has the same reviewed message shape."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MESSAGES = ROOT / "apps" / "web" / "messages"
LOCALES = ("en-AU", "zh-CN")
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z][A-Za-z0-9_]*)")


def leaves(value: Any, prefix: str = "") -> dict[str, str]:
    if isinstance(value, dict):
        result: dict[str, str] = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            result.update(leaves(child, path))
        return result
    if isinstance(value, str):
        return {prefix: value}
    raise TypeError(f"Message {prefix} must be a string or object, got {type(value).__name__}")


def load(locale: str) -> dict[str, str]:
    with (MESSAGES / f"{locale}.json").open(encoding="utf-8") as handle:
        return leaves(json.load(handle))


def main() -> int:
    catalogues = {locale: load(locale) for locale in LOCALES}
    reference = catalogues[LOCALES[0]]
    failures: list[str] = []
    for locale in LOCALES[1:]:
        current = catalogues[locale]
        missing = sorted(set(reference) - set(current))
        extra = sorted(set(current) - set(reference))
        if missing:
            failures.append(f"{locale}: missing keys: {', '.join(missing)}")
        if extra:
            failures.append(f"{locale}: unexpected keys: {', '.join(extra)}")
        for key in sorted(set(reference) & set(current)):
            expected = sorted(PLACEHOLDER_RE.findall(reference[key]))
            actual = sorted(PLACEHOLDER_RE.findall(current[key]))
            if expected != actual:
                failures.append(f"{locale}: placeholder mismatch at {key}: {expected!r} != {actual!r}")
    if failures:
        print("Localization catalogue validation failed:")
        print("\n".join(f"- {failure}" for failure in failures))
        return 1
    print(f"Localization catalogues valid: {len(reference)} messages across {', '.join(LOCALES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
