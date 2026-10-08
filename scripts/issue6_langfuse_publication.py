#!/usr/bin/env python3
"""Export and publish the reviewed, synthetic Issue 6 evaluation assets.

This command does not dispatch models or experiments, publish scores, change
application prompt loading, or assign a production prompt label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import uuid
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ORIGIN = "http://127.0.0.1:3001"
PROJECT_ID = "cmut9t75w00071z02n8bdv7it"
PROJECT_NAME = "memior"
PREFIX = "memoir/issue6/20261008-v1/"
ENVIRONMENT = "issue6-synthetic-evaluation"
DATASET_PATH = ROOT / "tests/evaluation/issue6_semantic_datasets.json"
DATASET_SHA256 = "bea8a31f8d4ab0539e2f1c99e08978acbcb4d60ffc25bf36579f04c8a27392c7"
EVALUATOR_SHA256 = "979560b162713d750a3cd92b0295c635e3611c92ba23bf80d27063b604089d96"
VALIDATOR_SHA256 = "cc626253dfecb2fa8f75d846334167f0ebd4e1321f2e092de6fb352918dcc403"
STAGES_SHA256 = "d11fc1a0c9ca1b6219d09c5f271a1c0fa3ba8e296025c2cffe58aacd09b1b5fd"
PROMPT_SOURCE_SHA256 = {
    "apps/api/memoir_preview.py": "523c0ce0725faa48290e9df8000071e3ef3e8d8ceaa697f4e0fb54b9df1b1d96",
    "skills/memoir-author-timeline/SKILL.md": "c080d55ae77bfcbce70a710335786258e70cf4def8fbc2f78fdd7d7af5946840",
    "skills/memoir-author-timeline/references/contract.md": "faabc0d8bb702279984f0924263f412a7852d8639b8bee6733d859c4dbd6ae84",
    "skills/memoir-composer/SKILL.md": "b0fed6a84bd9b19d6cfc6dd85353398c45954841faa5ba32379bd1b5442f4789",
    "skills/memoir-composer/references/editorial-and-length.md": "62d2b1a58054e08c6bdc5e5521190c82e27607da57a3d91de4c5396245bc8f78",
    "skills/memoir-composer/references/workflows.md": "50c556582c3fda00fed1349751c171eb83c8db1ef3288021ed3652ec2579a8e3",
    "skills/memoir-composer/references/editorial-review.prompt.md": "1906db785d7f4d7c1289a325ce8e69fdbaf322c92c10a31b6000fc6a62b7ab06",
    "skills/memoir-composer/schemas/draft.schema.json": "d84a990f03f2b4585ee0cd8d87c8781011a27bb9ed3b311ea8c4df0d0dffcd61",
    "skills/memoir-composer/schemas/request.schema.json": "87ce640e5c6f16383174ed5d675c1185e76466564b36bacf8d501cec791bea4f",
}


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def content_hash(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode())


def build_manifest():
    """Return a credential-free export of the reviewed synthetic source."""
    from apps.api.memory_events import extraction_instructions, extraction_schema
    from apps.api.memoir_preview import composer_instructions, composer_output_schema
    from scripts.issue6_langfuse_evaluators import evaluator_definitions

    raw = DATASET_PATH.read_bytes()
    if sha256(raw) != DATASET_SHA256:
        raise ValueError("Reviewed dataset hash changed; review a new publication version.")
    if sha256((ROOT / "scripts/issue6_semantic_evaluation.py").read_bytes()) != EVALUATOR_SHA256:
        raise ValueError("Reviewed application evaluator hash changed.")
    if sha256((ROOT / "apps/api/memory_events.py").read_bytes()) != VALIDATOR_SHA256 or sha256((ROOT / "apps/api/stage_readiness.py").read_bytes()) != STAGES_SHA256:
        raise ValueError("Reviewed application extraction validator or stage vocabulary changed.")
    if any(sha256((ROOT / path).read_bytes()) != expected for path, expected in PROMPT_SOURCE_SHA256.items()):
        raise ValueError("Reviewed runtime prompt source changed; review a new publication version.")
    fixture = json.loads(raw)
    if fixture["synthetic"] is not True or fixture["contains_customer_data"] is not False:
        raise ValueError("Only the reviewed synthetic dataset is publishable.")
    provenance = {
        "suite": fixture["suite"], "version": fixture["version"],
        "source_revision": fixture["source_revision"],
        "dataset_content_hash": DATASET_SHA256,
        "application_evaluator_sha256": EVALUATOR_SHA256,
        "application_validator_sha256": VALIDATOR_SHA256,
        "stage_vocabulary_sha256": STAGES_SHA256,
        "prompt_source_sha256": PROMPT_SOURCE_SHA256,
        "synthetic": True, "contains_customer_data": False,
        "rubric_version": fixture["rubric_version"],
        "human_review_status": fixture["human_rubric"]["review_status"],
        "provider_requests": 0,
    }
    datasets = []
    for dataset in fixture["datasets"]:
        items = []
        for item in dataset["items"]:
            items.append({
                "id": str(uuid.uuid5(uuid.UUID("20b12930-1bb9-5f3a-bfe5-c8c8ff518e93"),
                                    PROJECT_ID + "/" + dataset["name"] + "/" + item["case_id"])),
                "datasetName": dataset["name"], "input": item["input"],
                "expectedOutput": item["expected_output"], "status": "ACTIVE",
                "metadata": {**provenance, "dimension": dataset["dimension"],
                             "case_id": item["case_id"], "pair_id": item["pair_id"],
                             "language": item["language"], "case_content_hash": content_hash(item)},
            })
        metadata = {**provenance, "dimension": dataset["dimension"],
                    "human_rubric": fixture["human_rubric"], "item_count": len(items)}
        datasets.append({"name": dataset["name"], "description": dataset["description"],
                         "metadata": metadata, "dimension": dataset["dimension"], "items": items})
    prompts = []
    definitions = [("timeline", extraction_instructions(), extraction_schema())]
    definitions.extend(("composer/" + phase, composer_instructions(phase), composer_output_schema(phase))
                       for phase in ("prepare", "index", "draft", "review"))
    for name, instructions, schema in definitions:
        config = {**provenance, "phase": name, "instruction_sha256": sha256(instructions.encode()),
                  "output_schema": schema, "runtime_loading": "git_application_builders",
                  "publication_purpose": "evaluation-only"}
        prompts.append({"name": PREFIX + "prompts/" + name, "type": "text", "prompt": instructions,
                        "config": config, "labels": ["issue6-evaluation"], "tags": ["issue6", "synthetic"],
                        "commitMessage": "Exact application instructions; evaluation-only; no production label."})
    return {"schema_version": 1, "origin": ORIGIN, "project_id": PROJECT_ID,
            "project_name": PROJECT_NAME, "provenance": provenance, "datasets": datasets,
            "prompts": prompts, "evaluators": evaluator_definitions(), "provider_requests": 0,
            "semantic_acceptance": "pending_human_review_and_live_experiments"}


class PublicationAPI:
    """Fixed public API surface; errors deliberately omit bodies and auth."""
    def __init__(self, client):
        self.client = client

    def request(self, method, path, *, params=None, body=None, absent_ok=False):
        try:
            response = self.client.request(method, path, params=params, json=body)
        except httpx.RequestError:
            raise ValueError("Langfuse request outcome unknown; read back before repeating publication.") from None
        if absent_ok and response.status_code == 404:
            return None
        if response.status_code not in (200, 201):
            raise ValueError(f"Langfuse {method} {path.split('/')[4]} failed: HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError:
            raise ValueError("Langfuse returned an invalid API response.") from None

    def catalog(self, kind, *, dataset_name=None):
        path = "/api/public/dataset-items" if kind == "dataset-items" else "/api/public/v2/" + kind
        results, cursor = [], None
        for page in range(1, 101):
            params = {"limit": 100}
            if kind in ("evaluators", "evaluation-rules"):
                if cursor:
                    params["cursor"] = cursor
            else:
                params["page"] = page
            if dataset_name is not None:
                params["datasetName"] = dataset_name
            result = self.request("GET", path, params=params)
            if not isinstance(result.get("data"), list):
                raise ValueError("Langfuse catalog response lacks asset data.")
            results.extend(result["data"])
            meta = result.get("meta") or {}
            if kind in ("evaluators", "evaluation-rules"):
                next_cursor = meta.get("cursor")
                if not next_cursor:
                    return results
                if next_cursor == cursor:
                    raise ValueError("Langfuse catalog did not advance.")
                cursor = next_cursor
            elif page >= meta.get("totalPages", 1):
                return results
        raise ValueError("Langfuse catalog exceeds the bounded publication preflight.")


def _matching(actual, expected, keys):
    if actual is None or any(actual.get(key) != expected.get(key) for key in keys):
        raise ValueError("Existing or read-back asset conflicts with the reviewed publication; no overwrite is allowed.")


def _named(catalog, name):
    candidates = [asset for asset in catalog if asset.get("name") == name]
    if len(candidates) > 1:
        raise ValueError("Ambiguous duplicate asset names; review existing versions before publication.")
    return candidates[0] if candidates else None


def _rule(dimension, dataset_id, evaluator_id):
    return {"name": PREFIX + "rules/" + dimension, "enabled": False, "sampling": 1,
            "evaluatorAssignments": [{"evaluatorId": evaluator_id}],
            "filter": [
                {"column": "datasetId", "type": "stringOptions", "operator": "any of", "value": [dataset_id]},
                {"column": "isExperimentItemRootSpan", "type": "boolean", "operator": "=", "value": True},
                {"column": "environment", "type": "stringOptions", "operator": "any of", "value": [ENVIRONMENT]},
            ]}


def _check_rule(actual, expected):
    _matching(actual, expected, ("name", "enabled", "sampling", "filter"))
    assignments = actual.get("evaluatorAssignments", [])
    if len(assignments) != 1 or assignments[0].get("evaluatorId") != expected["evaluatorAssignments"][0]["evaluatorId"] or assignments[0].get("variableMapping"):
        raise ValueError("Existing evaluation rule has a conflicting evaluator assignment.")


def publish(manifest, client):
    """Publish bounded assets and return a secret-free read-back receipt."""
    if str(client.base_url).rstrip("/") != ORIGIN:
        raise ValueError("Publication is limited to the approved local Langfuse origin.")
    if client.follow_redirects:
        raise ValueError("Publication requires redirects disabled.")
    if manifest != build_manifest():
        raise ValueError("Publication accepts only the current reviewed synthetic export.")
    api = PublicationAPI(client)
    projects = api.request("GET", "/api/public/projects").get("data", [])
    if len(projects) != 1 or projects[0].get("id") != PROJECT_ID or projects[0].get("name") != PROJECT_NAME:
        raise ValueError("Existing credentials do not identify exactly the approved project.")
    catalogs = {kind: api.catalog(kind) for kind in ("datasets", "prompts", "evaluators", "evaluation-rules")}
    existing_datasets, existing_prompts, existing_evaluators, existing_rules, existing_items = {}, {}, {}, {}, {}
    # Preflight every possible conflict before the first write. Never overwrite.
    for dataset in manifest["datasets"]:
        name = dataset["name"]
        existing = _named(catalogs["datasets"], name)
        if existing:
            existing = api.request("GET", "/api/public/v2/datasets/" + quote(name, safe=""))
            _matching(existing, dataset, ("name", "description", "metadata"))
            allowed_ids = {item["id"] for item in dataset["items"]}
            if any(item.get("id") not in allowed_ids for item in api.catalog("dataset-items", dataset_name=name)):
                raise ValueError("Reviewed dataset contains unexpected items; no automatic deletion is allowed.")
        existing_datasets[name] = existing
        for item in dataset["items"]:
            saved = api.request("GET", "/api/public/dataset-items/" + item["id"], absent_ok=True)
            if saved:
                _matching(saved, item, ("id", "datasetName", "input", "expectedOutput", "metadata", "status"))
            existing_items[item["id"]] = saved
    for prompt in manifest["prompts"]:
        name = prompt["name"]
        saved = None
        if _named(catalogs["prompts"], name):
            saved = api.request("GET", "/api/public/v2/prompts/" + quote(name, safe=""), params={"label": "latest"})
            _matching(saved, prompt, ("name", "type", "prompt", "config"))
            if "issue6-evaluation" not in saved.get("labels", []) or "production" in saved.get("labels", []):
                raise ValueError("Existing prompt labels conflict with evaluation-only publication.")
        existing_prompts[name] = saved
    for evaluator in manifest["evaluators"]:
        name = evaluator["name"]
        saved = _named(catalogs["evaluators"], name)
        if saved:
            saved = api.request("GET", "/api/public/v2/evaluators/" + saved["id"])
            _matching(saved, evaluator, ("name", "type", "sourceCode", "sourceCodeLanguage", "description"))
        existing_evaluators[name] = saved
    for dataset, evaluator in zip(manifest["datasets"], manifest["evaluators"]):
        name = PREFIX + "rules/" + dataset["dimension"]
        saved = _named(catalogs["evaluation-rules"], name)
        if saved:
            ds = existing_datasets[dataset["name"]]
            ev = existing_evaluators[evaluator["name"]]
            if not ds or not ev:
                raise ValueError("Existing evaluation rule refers to unreviewed assets.")
            _check_rule(saved, _rule(dataset["dimension"], ds["id"], ev["id"]))
        existing_rules[name] = saved

    receipt = {"project_id": PROJECT_ID, "origin": ORIGIN,
               "manifest_sha256": content_hash(manifest), "provenance": manifest["provenance"],
               "datasets": [], "prompts": [], "evaluators": [], "rules": [],
               "provider_requests": 0, "experiments_started": 0, "scores_published": 0,
               "semantic_acceptance": manifest["semantic_acceptance"]}
    for dataset in manifest["datasets"]:
        name = dataset["name"]
        if not existing_datasets[name]:
            api.request("POST", "/api/public/v2/datasets", body={k: dataset[k] for k in ("name", "description", "metadata")})
        saved = api.request("GET", "/api/public/v2/datasets/" + quote(name, safe=""))
        _matching(saved, dataset, ("name", "description", "metadata"))
        for item in dataset["items"]:
            if not existing_items[item["id"]]:
                api.request("POST", "/api/public/dataset-items", body=item)
            read_back = api.request("GET", "/api/public/dataset-items/" + item["id"])
            _matching(read_back, item, ("id", "datasetName", "input", "expectedOutput", "metadata", "status"))
        read_items = api.catalog("dataset-items", dataset_name=name)
        if {item["id"] for item in read_items} != {item["id"] for item in dataset["items"]} or len(read_items) != len(dataset["items"]):
            raise ValueError("Dataset item read-back count or identity differs from the reviewed fixture.")
        expected_items = {item["id"]: item for item in dataset["items"]}
        for read_item in read_items:
            _matching(read_item, expected_items[read_item["id"]], ("id", "datasetName", "input", "expectedOutput", "metadata", "status"))
        existing_datasets[name] = saved
        item_versions = {item["id"]: item.get("updatedAt") for item in read_items}
        snapshot = max((version for version in item_versions.values() if version), default=None)
        receipt["datasets"].append({"name": name, "id": saved["id"], "item_count": len(read_items),
                                    "dataset_version": snapshot, "item_versions": item_versions,
                                    "url": f"{ORIGIN}/project/{PROJECT_ID}/datasets/{saved['id']}"})
    for prompt in manifest["prompts"]:
        name = prompt["name"]
        saved = existing_prompts[name] or api.request("POST", "/api/public/v2/prompts", body=prompt)
        saved = api.request("GET", "/api/public/v2/prompts/" + quote(name, safe=""), params={"version": saved["version"]})
        _matching(saved, prompt, ("name", "type", "prompt", "config"))
        if "issue6-evaluation" not in saved.get("labels", []) or "production" in saved.get("labels", []):
            raise ValueError("Published prompt is not evaluation-only.")
        receipt["prompts"].append({"name": name, "version": saved["version"],
                                   "instruction_sha256": prompt["config"]["instruction_sha256"], "labels": saved["labels"],
                                   "url": f"{ORIGIN}/project/{PROJECT_ID}/prompts/{quote(name, safe='')}"})
    for evaluator in manifest["evaluators"]:
        name = evaluator["name"]
        saved = existing_evaluators[name] or api.request("POST", "/api/public/v2/evaluators", body=evaluator)
        saved = api.request("GET", "/api/public/v2/evaluators/" + saved["id"])
        _matching(saved, evaluator, ("name", "type", "sourceCode", "sourceCodeLanguage", "description"))
        existing_evaluators[name] = saved
        receipt["evaluators"].append({"name": name, "id": saved["id"], "version": saved["version"],
                                      "source_code_sha256": sha256(evaluator["sourceCode"].encode()),
                                      "status": "staged_callback_and_human_review_pending"})
    for dataset, evaluator in zip(manifest["datasets"], manifest["evaluators"]):
        rule = _rule(dataset["dimension"], existing_datasets[dataset["name"]]["id"], existing_evaluators[evaluator["name"]]["id"])
        saved = existing_rules[rule["name"]] or api.request("POST", "/api/public/v2/evaluation-rules", body=rule)
        saved = api.request("GET", "/api/public/v2/evaluation-rules/" + saved["id"])
        _check_rule(saved, rule)
        receipt["rules"].append({"name": rule["name"], "id": saved["id"], "enabled": saved["enabled"], "filter": saved["filter"]})
    receipt["verified_counts"] = {"datasets": len(receipt["datasets"]),
                                  "items": sum(d["item_count"] for d in receipt["datasets"]),
                                  "prompts": len(receipt["prompts"]), "evaluators": len(receipt["evaluators"]),
                                  "disabled_rules": len(receipt["rules"])}
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--export", required=True, type=Path)
    parser.add_argument("--publish", action="store_true", help="Publish configuration only; no model or experiment dispatch")
    parser.add_argument("--credential-file", type=Path, help="Existing environment file; only the COPYME2AI Langfuse keys are used privately")
    parser.add_argument("--receipt", type=Path, help="Secret-free read-back receipt, required for publication")
    args = parser.parse_args()
    try:
        protected = {DATASET_PATH.resolve(), Path(__file__).resolve(),
                     *(ROOT / path for path in PROMPT_SOURCE_SHA256),
                     ROOT / "apps/api/memory_events.py", ROOT / "apps/api/stage_readiness.py",
                     ROOT / "scripts/issue6_semantic_evaluation.py", ROOT / "scripts/issue6_langfuse_evaluators.py"}
        if args.credential_file:
            protected.add(args.credential_file.resolve())
        destinations = [path.resolve() for path in (args.export, args.receipt) if path]
        if any(path in protected for path in destinations) or len(destinations) != len(set(destinations)):
            raise ValueError("Export and receipt paths must be distinct and preserve source and credential files.")
        manifest = build_manifest()
        args.export.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        if args.publish:
            if not args.credential_file or not args.receipt:
                raise ValueError("Publication requires the existing credential file and a read-back receipt path.")
            from dotenv import dotenv_values
            values = dotenv_values(args.credential_file, interpolate=False)
            public_key = values.get("LANGFUSE_COPYME2AI_PUBLIC_KEY")
            secret_key = values.get("LANGFUSE_COPYME2AI_SECRET_KEY")
            if not public_key or not secret_key:
                raise ValueError("Existing project credentials are unavailable; no credentials will be created or guessed.")
            with httpx.Client(base_url=ORIGIN, auth=(public_key, secret_key), timeout=15,
                              trust_env=False, follow_redirects=False) as client:
                receipt = publish(manifest, client)
            args.receipt.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
            print(json.dumps({"receipt": str(args.receipt), "verified_counts": receipt["verified_counts"], "provider_requests": 0}))
        else:
            print(json.dumps({"export": str(args.export), "datasets": len(manifest["datasets"]),
                              "items": sum(len(d["items"]) for d in manifest["datasets"]),
                              "prompts": len(manifest["prompts"]), "evaluators": len(manifest["evaluators"]),
                              "provider_requests": 0}))
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1
    except OSError:
        print("Publication file access failed; no file contents are logged.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
