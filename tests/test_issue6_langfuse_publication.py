"""Publication boundary tests. Langfuse HTTP responses are controlled here."""
import json
from pathlib import Path
import subprocess
import sys
from copy import deepcopy
import pytest
import httpx


ROOT = Path(__file__).resolve().parents[1]


def test_export_preserves_reviewed_synthetic_cases_and_exact_runtime_prompts(tmp_path):
    destination = tmp_path / "publication.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/issue6_langfuse_publication.py"),
         "--export", str(destination)], capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    export = json.loads(destination.read_text())
    assert export["project_id"] == "cmut9t75w00071z02n8bdv7it"
    assert [(dataset["dimension"], len(dataset["items"])) for dataset in export["datasets"]] == [
        ("event-grounding", 8), ("temporal-placement", 14),
        ("chapter-continuity", 2), ("bilingual-consistency", 4),
    ]
    from apps.api.memory_events import extraction_instructions
    from apps.api.memoir_preview import composer_instructions
    assert [prompt["prompt"] for prompt in export["prompts"]] == [
        extraction_instructions(),
        *(composer_instructions(phase) for phase in ("prepare", "index", "draft", "review")),
    ]
    assert all(prompt["labels"] == ["issue6-evaluation"] for prompt in export["prompts"])
    assert export["provider_requests"] == 0
    assert export["semantic_acceptance"] == "pending_human_review_and_live_experiments"


def evaluate_code(source, context):
    # Execute the public Langfuse function contract with Node's standard runtime.
    program = source + "\nconsole.log(JSON.stringify(evaluate(JSON.parse(require('fs').readFileSync(0, 'utf8')))));"
    result = subprocess.run(["node", "-e", program], input=json.dumps(context),
                            capture_output=True, text=True, check=True)
    return {score["name"]: score for score in json.loads(result.stdout)["scores"]}


def test_managed_evaluator_keeps_missing_outputs_and_pending_human_judgments_distinct():
    from scripts.issue6_langfuse_evaluators import evaluator_definitions
    source = evaluator_definitions()[0]["sourceCode"]
    scores = evaluate_code(source, {"observation": {"input": {}, "output": None, "metadata": {}}})
    assert scores["schema_and_original_evidence"]["value"] == "unavailable"
    assert scores["schema_and_original_evidence"]["dataType"] == "TEXT"
    assert scores["factual_entailment"]["value"] == "unavailable"


def test_managed_evaluator_uses_application_evidence_validation_and_rejects_stale_receipts():
    from scripts.issue6_langfuse_publication import build_manifest
    from scripts.issue6_langfuse_evaluators import application_receipt, evaluator_definitions
    item = build_manifest()["datasets"][0]["items"][2]
    output = {"events": [{"kind": "event", "title": "First job",
                          "source_refs": [{"source_id": "s1", "version": 1,
                                           "quote": "I worked in a factory in 1970."}]}]}
    receipt = application_receipt(item["metadata"]["case_id"], output,
                                  worker_completed=True, completed_sources={"s1": 1})
    context = {"observation": {"input": item["input"], "output": output,
                               "metadata": {"issue6_application_receipt": receipt}},
               "experiment": {"itemExpectedOutput": item["expectedOutput"], "itemMetadata": item["metadata"]}}
    source = evaluator_definitions()[0]["sourceCode"]
    scores = evaluate_code(source, context)
    assert scores["schema_and_original_evidence"]["value"] == 0
    assert scores["event_count"]["value"] == 0
    assert scores["factual_entailment"]["value"] == "human_review_required"
    changed = deepcopy(context)
    changed["observation"]["output"] = {"events": []}
    assert evaluate_code(source, changed)["event_count"]["value"] == "unavailable"


@pytest.mark.parametrize("completed,coverage,expected", [
    (False, {"s1": 1}, "unavailable"),
    (True, {}, "unavailable"),
    (True, {"s1": 2}, "unavailable"),
    (True, {"s1": 1}, 1),
])
def test_empty_extraction_requires_worker_completion_and_original_source_coverage(completed, coverage, expected):
    from scripts.issue6_langfuse_publication import build_manifest
    from scripts.issue6_langfuse_evaluators import application_receipt, evaluator_definitions
    item = build_manifest()["datasets"][0]["items"][0]
    output = {"events": []}
    receipt = application_receipt(item["metadata"]["case_id"], output,
                                  worker_completed=completed, completed_sources=coverage)
    context = {"observation": {"input": item["input"], "output": output,
                               "metadata": {"issue6_application_receipt": receipt}},
               "experiment": {"itemExpectedOutput": item["expectedOutput"], "itemMetadata": item["metadata"]}}
    scores = evaluate_code(evaluator_definitions()[0]["sourceCode"], context)
    assert scores["event_count"]["value"] == expected
    assert scores["expected_placement"]["value"] == ("not_applicable" if expected == 1 else "unavailable")


def test_publication_rejects_other_project_before_any_asset_write():
    from scripts.issue6_langfuse_publication import ORIGIN, build_manifest, publish

    def wrong_project(request):
        assert request.method == "GET", "A wrong project must receive no writes"
        return httpx.Response(200, json={"data": [{"id": "other", "name": "other"}]})

    with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(wrong_project)) as client:
        with pytest.raises(ValueError, match="project"):
            publish(build_manifest(), client)


class LangfuseHTTPBoundary:
    """In-memory external API double. This is not native Langfuse evidence."""
    def __init__(self):
        self.assets = {path: {} for path in ("datasets", "prompts", "evaluators", "evaluation-rules")}
        self.items = {}
        self.writes = 0

    def __call__(self, request):
        from urllib.parse import unquote
        path = unquote(request.url.path)
        if path == "/api/public/projects":
            return httpx.Response(200, json={"data": [{"id": "cmut9t75w00071z02n8bdv7it", "name": "memior"}]})
        if path == "/api/public/dataset-items":
            if request.method == "GET":
                items = [item for item in self.items.values() if item["datasetName"] == request.url.params["datasetName"]]
                return httpx.Response(200, json={"data": items, "meta": {"totalPages": 1}})
            item = json.loads(request.content)
            self.writes += 1
            self.items[item["id"]] = item
            return httpx.Response(200, json=item)
        if path.startswith("/api/public/dataset-items/"):
            item = self.items.get(path.rsplit("/", 1)[1])
            return httpx.Response(200 if item else 404, json=item or {})
        assert path.startswith("/api/public/v2/"), "Unexpected public API"
        kind, _, key = path.removeprefix("/api/public/v2/").partition("/")
        assets = self.assets[kind]
        if request.method == "GET":
            if not key:
                return httpx.Response(200, json={"data": list(assets.values()), "meta": {"totalPages": 1}})
            entry = assets.get(key) or next((v for v in assets.values() if v.get("id") == key), None)
            return httpx.Response(200 if entry else 404, json=entry or {})
        assert request.method == "POST", "Publication cannot update or delete existing assets"
        body = json.loads(request.content)
        entry = {**body, "id": str(len(assets) + 1), "version": 1}
        self.writes += 1
        assets[body["name"]] = entry
        return httpx.Response(200, json=entry)


def test_publication_read_back_contains_exact_assets_and_repeating_it_adds_nothing():
    from scripts.issue6_langfuse_publication import ORIGIN, build_manifest, publish
    boundary = LangfuseHTTPBoundary()
    with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(boundary)) as client:
        receipt = publish(build_manifest(), client)
        assert receipt["verified_counts"] == {"datasets": 4, "items": 28, "prompts": 5, "evaluators": 4, "disabled_rules": 4}
        assert all(not rule["enabled"] for rule in boundary.assets["evaluation-rules"].values())
        written = boundary.writes
        repeated = publish(build_manifest(), client)
        assert repeated["verified_counts"] == receipt["verified_counts"]
        assert boundary.writes == written


def test_cli_missing_project_keys_stops_without_printing_other_secrets(tmp_path):
    credential_file = tmp_path / "existing.env"
    credential_file.write_text("UNRELATED_SECRET=keep-this-private\n")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/issue6_langfuse_publication.py"),
         "--export", str(tmp_path / "export.json"), "--publish",
         "--credential-file", str(credential_file), "--receipt", str(tmp_path / "receipt.json")],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "Existing project credentials are unavailable" in result.stderr
    assert "keep-this-private" not in result.stdout + result.stderr


def test_export_cannot_overwrite_the_existing_credential_file(tmp_path):
    credential_file = tmp_path / "existing.env"
    original = "UNRELATED_SECRET=preserve-this-file\n"
    credential_file.write_text(original)
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/issue6_langfuse_publication.py"),
         "--export", str(credential_file), "--credential-file", str(credential_file)],
        capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert credential_file.read_text() == original


def test_conflicting_evaluator_stops_publication_before_even_independent_dataset_writes():
    from scripts.issue6_langfuse_publication import ORIGIN, build_manifest, publish
    boundary = LangfuseHTTPBoundary()
    manifest = build_manifest()
    evaluator = manifest["evaluators"][0]
    boundary.assets["evaluators"][evaluator["name"]] = {
        **evaluator, "id": "existing", "version": 1, "sourceCode": "Conflicting source",
    }
    with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(boundary)) as client:
        with pytest.raises(ValueError, match="conflicts"):
            publish(manifest, client)
    assert boundary.writes == 0


def test_uncertain_create_stops_and_explicit_resume_reuses_the_persisted_dataset():
    from scripts.issue6_langfuse_publication import ORIGIN, build_manifest, publish
    boundary = LangfuseHTTPBoundary()
    fail_once = True

    def lost_response(request):
        nonlocal fail_once
        response = boundary(request)
        if fail_once and request.method == "POST":
            fail_once = False
            raise httpx.ReadTimeout("Controlled lost response", request=request)
        return response

    with httpx.Client(base_url=ORIGIN, transport=httpx.MockTransport(lost_response)) as client:
        with pytest.raises(ValueError, match="outcome unknown"):
            publish(build_manifest(), client)
        assert boundary.writes == 1
        receipt = publish(build_manifest(), client)
        assert receipt["verified_counts"]["datasets"] == 4
        assert len(boundary.assets["datasets"]) == 4
