#!/usr/bin/env python3
"""Pin a Langfuse text prompt version into a repository runtime artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.prompt_artifact import load_prompt_artifact
from scripts.langfuse_prompt_client import prompt_client


TARGETS = {
    "journalist": Path("Mira_Memoir_Journalist_System_Prompt_v1.0.md"),
    "collector-compact": Path("apps/api/prompts/collector-compact.md"),
}


def target_path(target: str, root: Path) -> Path:
    relative = TARGETS.get(target, Path(target))
    path = (root / relative).resolve()
    allowed = (root / "skills").resolve(), (root / "apps/api/prompts").resolve(), (root / "tests/evaluation").resolve()
    if (path != (root / TARGETS["journalist"]).resolve()
            and (path.suffix != ".md" or not any(path.is_relative_to(directory) for directory in allowed))):
        raise ValueError("Prompt target must be a known target or a repository prompt Markdown file")
    return path


def _replace(path: Path, content: str) -> None:
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def sync_prompt(client, *, target: str, name: str, version: int,
                root: Path = ROOT, check: bool = False) -> dict:
    if not name or version < 1:
        raise ValueError("A prompt name and positive exact version are required")
    root = root.resolve()
    path = target_path(target, root)
    if not path.is_file():
        raise ValueError(f"Missing repository prompt target: {path.relative_to(root)}")
    receipt_path = path.with_name(path.name + ".langfuse.json")
    if receipt_path.exists():
        load_prompt_artifact(path)  # Refuse to overwrite a locally edited, pinned prompt.
    prompt = client.get_prompt(name, version=version, type="text",
                               cache_ttl_seconds=0, max_retries=0)
    content = getattr(prompt, "prompt", None)
    if (getattr(prompt, "is_fallback", False)
            or getattr(prompt, "name", None) != name
            or getattr(prompt, "version", None) != version
            or not isinstance(content, str) or not content.strip()):
        raise ValueError("Langfuse returned a different, fallback or empty prompt version")
    receipt = {
        "schema_version": 1,
        "name": name,
        "version": version,
        "type": "text",
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }
    if check:
        if not receipt_path.exists() or path.read_text(encoding="utf-8") != content:
            raise ValueError("Repository prompt differs from the selected Langfuse version")
        if json.loads(receipt_path.read_text(encoding="utf-8")) != receipt:
            raise ValueError("Repository prompt receipt differs from the selected Langfuse version")
    else:
        _replace(path, content)
        _replace(receipt_path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return {"target": str(path.relative_to(root)), **receipt}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True,
                        help="journalist, collector-compact, or an existing prompt .md under skills/, apps/api/prompts/ or tests/evaluation/")
    parser.add_argument("--name", required=True, help="Langfuse prompt name")
    parser.add_argument("--version", required=True, type=int, help="Exact immutable Langfuse version")
    parser.add_argument("--check", action="store_true", help="Compare with the checked-in artifact without writing")
    parser.add_argument("--credential-file", type=Path, help="Provider .env containing Memoir project credentials")
    args = parser.parse_args()
    client = prompt_client(args.credential_file)
    receipt = sync_prompt(client, target=args.target, name=args.name,
                          version=args.version, check=args.check)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
