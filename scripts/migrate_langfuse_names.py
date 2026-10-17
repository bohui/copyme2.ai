#!/usr/bin/env python3
"""Move Issue 6 snapshots into stable Langfuse names without erasing history."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.api.prompt_artifact import load_prompt_artifact
from scripts.export_langfuse_prompt import sync_prompt
from scripts.langfuse_prompt_client import prompt_client
from scripts.prompt_registry import prompt_registry

ISSUE6 = "memoir/issue6/20261008-v1"
HISTORICAL_PROMPTS = {
    "memoir/memory/timeline": f"{ISSUE6}/prompts/timeline",
    **{f"memoir/composer/{phase}": f"{ISSUE6}/prompts/composer/{phase}"
       for phase in ("prepare", "index", "draft", "review")},
}
DATASETS = ("event-grounding", "temporal-placement", "chapter-continuity",
            "bilingual-consistency")


def _latest(client, name):
    matches = [item for item in client.api.prompts.list(name=name, limit=100).data
               if item.name == name]
    if not matches:
        return None
    if len(matches) != 1 or not matches[0].versions:
        raise ValueError(f"Ambiguous prompt versions for {name}")
    return client.get_prompt(name, version=max(matches[0].versions), type="text",
                             cache_ttl_seconds=0, max_retries=0)


def migrate_prompts(client):
    receipts = []
    for name, target in prompt_registry().items():
        path = ROOT / target
        current_text = load_prompt_artifact(path)
        latest = _latest(client, name)
        if latest is None and name in HISTORICAL_PROMPTS:
            old_name = HISTORICAL_PROMPTS[name]
            historical = client.get_prompt(old_name, version=1, type="text",
                                           cache_ttl_seconds=0, max_retries=0)
            if historical.name != old_name or historical.version != 1:
                raise ValueError(f"Historical prompt not verified: {old_name}")
            latest = client.create_prompt(name=name, prompt=historical.prompt,
                                          type="text", commit_message="Historical Issue 6 snapshot")
        if latest is None:
            latest = client.create_prompt(name=name, prompt=current_text, type="text",
                                          commit_message="Import checked-in Memoir prompt")
        elif latest.prompt != current_text:
            latest = client.create_prompt(name=name, prompt=current_text, type="text",
                                          commit_message="Current checked-in Memoir prompt")
        receipts.append(sync_prompt(client, target=target, name=name,
                                    version=latest.version))
    return receipts


def migrate_datasets(client):
    results = []
    for suffix in DATASETS:
        old_name = f"{ISSUE6}/{suffix}"
        new_name = f"memoir/evaluation/{suffix}"
        source = client.get_dataset(old_name)
        available = {item.name for item in client.api.datasets.list(limit=100).data}
        if new_name not in available:
            metadata = dict(source.metadata or {})
            metadata["migrated_from"] = old_name
            client.create_dataset(name=new_name, description=source.description,
                                  metadata=metadata, input_schema=source.input_schema,
                                  expected_output_schema=source.expected_output_schema)
        destination = client.get_dataset(new_name)
        if (destination.metadata or {}).get("migrated_from") != old_name:
            raise ValueError(f"Existing dataset has different provenance: {new_name}")
        existing = {(item.metadata or {}).get("migrated_from_item_id"): item
                    for item in destination.items}
        for item in source.items:
            old = existing.get(item.id)
            if old:
                if old.input != item.input or old.expected_output != item.expected_output:
                    raise ValueError(f"Migrated dataset item changed: {new_name}")
                continue
            metadata = dict(item.metadata or {})
            metadata["migrated_from_item_id"] = item.id
            client.create_dataset_item(dataset_name=new_name, input=item.input,
                                       expected_output=item.expected_output, metadata=metadata,
                                       status=item.status)
        destination = client.get_dataset(new_name)
        if len(destination.items) != len(source.items):
            raise ValueError(f"Dataset item count differs after migration: {new_name}")
        results.append({"name": new_name, "items": len(destination.items)})
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credential-file", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps({"prompt_names": list(prompt_registry()),
                          "dataset_names": [f"memoir/evaluation/{name}" for name in DATASETS]},
                         sort_keys=True))
        return 0
    client = prompt_client(args.credential_file)
    receipts = migrate_prompts(client)
    datasets = migrate_datasets(client)
    print(json.dumps({"prompts": len(receipts), "datasets": datasets,
                      "versions": {r["name"]: r["version"] for r in receipts}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
