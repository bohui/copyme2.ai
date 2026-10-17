#!/usr/bin/env python3
"""Bootstrap exact repo prompt text in Langfuse and pin returned versions."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.export_langfuse_prompt import sync_prompt
from scripts.langfuse_prompt_client import prompt_client
from scripts.prompt_registry import prompt_registry


def publish(client, *, root: Path = ROOT, bootstrap: bool = False) -> list[dict]:
    registry = prompt_registry(root)
    receipts = []
    for name, target in registry.items():
        text = (root / target).read_text(encoding="utf-8")
        matches = [item for item in client.api.prompts.list(name=name, limit=100).data
                   if item.name == name]
        if matches:
            if len(matches) != 1 or not matches[0].versions:
                raise ValueError(f"Ambiguous Langfuse prompt versions for {name}")
            prompt = client.get_prompt(name, version=max(matches[0].versions),
                                       type="text", cache_ttl_seconds=0,
                                       max_retries=0)
            if prompt.prompt != text:
                raise ValueError(f"Langfuse has a different version for {name}; export an exact version first")
        elif bootstrap:
            prompt = client.create_prompt(name=name, prompt=text, type="text",
                                          commit_message="Import checked-in Memoir prompt")
        else:
            raise ValueError(f"Langfuse prompt is missing: {name}; use --bootstrap to import it")
        receipts.append(sync_prompt(client, target=target, name=name,
                                    version=prompt.version, root=root))
    return receipts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--bootstrap", action="store_true", help="Create prompts that do not exist yet")
    args = parser.parse_args()
    client = prompt_client(args.credential_file)
    try:
        receipts = publish(client, bootstrap=args.bootstrap)
        print(json.dumps({"artifacts": len(receipts),
                          "versions": {r["name"]: r["version"] for r in receipts}}, sort_keys=True))
    finally:
        client.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
