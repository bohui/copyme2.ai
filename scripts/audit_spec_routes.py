#!/usr/bin/env python3
"""Check that every route listed in the specification has an application route."""

from __future__ import annotations

import argparse
import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path


METHODS = {"get", "post", "patch", "put", "delete"}
ROUTE_ROW = re.compile(r"\|\s*(GET|POST|PATCH|PUT|DELETE)\s+([^|]+?)\s*\|")


def normalise(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", path)


def spec_text(spec: Path) -> str:
    if spec.suffix.lower() != ".docx":
        return spec.read_text(encoding="utf-8")
    pandoc = shutil.which("pandoc")
    if not pandoc:
        raise RuntimeError("Pandoc is required to audit a .docx specification; pass the checked-in .md copy with --spec if unavailable")
    result = subprocess.run(
        [pandoc, "--track-changes=all", str(spec), "-t", "gfm"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def required_routes(spec: Path) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()
    for line in spec_text(spec).splitlines():
        match = ROUTE_ROW.match(line)
        if match:
            routes.add((match.group(1), normalise("/v1" + match.group(2).strip())))
    return routes


def implemented_routes(app_file: Path) -> set[tuple[str, str]]:
    tree = ast.parse(app_file.read_text(encoding="utf-8"), filename=str(app_file))
    routes: set[tuple[str, str]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in METHODS or not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        path = node.args[0].value
        if isinstance(path, str) and path.startswith("/v1"):
            routes.add((node.func.attr.upper(), normalise(path)))
    return routes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default="docs/Memory_Spark_Full_Specification_v1.0.docx")
    parser.add_argument("--app", default="apps/api/main.py")
    args = parser.parse_args()

    try:
        required = required_routes(Path(args.spec))
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f"Specification audit failed: {error}", file=sys.stderr)
        return 2
    implemented = implemented_routes(Path(args.app))
    missing = sorted(required - implemented)
    print(f"Specification routes: {len(required)}")
    print(f"Application routes: {len(implemented)}")
    if missing:
        print("Missing routes:")
        for method, path in missing:
            print(f"  {method:6} {path}")
        return 1
    print("All specification routes are represented in the application.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
