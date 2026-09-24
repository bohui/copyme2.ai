#!/usr/bin/env python3
"""Run the named DOCX acceptance catalogue and write reviewable evidence."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


AT_NAME = re.compile(r"test_at_(\d{3})_(.*)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="docs/Memory_Spark_Acceptance_Evidence.md")
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(prefix="memory-spark-", suffix=".xml", delete=False) as handle:
        junit_path = Path(handle.name)
    command = [sys.executable, "-m", "pytest", "-q", "tests/test_full_acceptance.py", f"--junitxml={junit_path}"]
    result = subprocess.run(command, capture_output=True, text=True)
    cases: list[tuple[str, str, str]] = []
    try:
        root = ET.parse(junit_path).getroot()
        for testcase in root.findall(".//testcase"):
            match = AT_NAME.fullmatch(testcase.attrib.get("name", ""))
            if not match:
                continue
            status = "PASS"
            detail = ""
            if testcase.find("failure") is not None:
                status = "FAIL"
                detail = testcase.find("failure").attrib.get("message", "failure")
            elif testcase.find("error") is not None:
                status = "ERROR"
                detail = testcase.find("error").attrib.get("message", "error")
            elif testcase.find("skipped") is not None:
                status = "SKIP"
                detail = "skipped"
            cases.append((f"AT-{match.group(1)}", match.group(2).replace("_", " "), f"{status}{': ' + detail if detail else ''}"))
    finally:
        junit_path.unlink(missing_ok=True)

    cases.sort(key=lambda item: item[0])
    passed = sum(status == "PASS" for _, _, status in cases)
    generated = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Memory Spark acceptance evidence",
        "",
        f"Generated: `{generated}`",
        "",
        "This report runs the 55 functional and adversarial acceptance cases from section 26.2 of `Memory_Spark_Full_Specification_v1.0.docx` against the credential-free local deterministic cell.",
        "",
        f"Command: `{' '.join(command[:-2])} tests/test_full_acceptance.py`",
        "",
        f"Result: **{passed}/{len(cases)} acceptance cases passed**.",
        "",
        "| Case | Scenario | Result |",
        "|---|---|---|",
    ]
    lines.extend(f"| {case} | {scenario} | {status} |" for case, scenario, status in cases)
    lines.extend(
        [
            "",
            "The test evidence uses deterministic providers and an explicit in-memory store. It proves the documented functional behavior, permissions, idempotency and failure guards; Supabase PostgreSQL durability is verified separately by the configured database check and is not exercised by this credential-free suite.",
            "",
            "The full repository suite and the section 19.2 route audit are run separately by `make harness-check` through the Codex exec-server in Apple Container + Mocker.",
        ]
    )
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Acceptance evidence: {passed}/{len(cases)} passed")
    print(f"Report: {output}")
    if result.stdout:
        print(result.stdout.strip())
    if result.stderr:
        print(result.stderr.strip(), file=sys.stderr)
    return result.returncode if cases and passed != len(cases) else (result.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
