import hashlib
import json
from types import SimpleNamespace

import pytest

from apps.api.prompt_artifact import load_prompt_artifact
from scripts.export_langfuse_prompt import sync_prompt
from scripts.export_langfuse_prompts import export_prompts, selected_prompts
from apps.api.prompt_composition import render_prompt_artifact
from scripts.prompt_registry import ROOT, prompt_registry
from scripts.evaluate_langfuse_prompt import dataset_input_text, dataset_version, experiment_task


class PromptClient:
    def __init__(self, prompt="New prompt"):
        self.prompt = prompt
        self.calls = []

    def get_prompt(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return SimpleNamespace(name=name, version=kwargs["version"], prompt=self.prompt,
                               is_fallback=False)


def test_exact_langfuse_version_is_exported_and_verified(tmp_path):
    path = tmp_path / "apps/api/prompts/mira/system.md"
    path.parent.mkdir(parents=True)
    path.write_text("Original prompt", encoding="utf-8")
    client = PromptClient()

    receipt = sync_prompt(client, target="mira", name="memoir/agents/mira/system",
                          version=7, root=tmp_path)

    assert client.calls == [("memoir/agents/mira/system", {
        "version": 7, "type": "text", "cache_ttl_seconds": 0, "max_retries": 0})]
    assert load_prompt_artifact(path) == "New prompt"
    assert receipt["sha256"] == hashlib.sha256(b"New prompt").hexdigest()
    assert json.loads(path.with_name(path.name + ".langfuse.json").read_text()) == {
        "schema_version": 1, "name": "memoir/agents/mira/system", "version": 7,
        "type": "text", "sha256": receipt["sha256"]}
    sync_prompt(client, target="mira", name="memoir/agents/mira/system",
                version=7, root=tmp_path, check=True)


def test_drift_or_wrong_remote_version_cannot_replace_artifact(tmp_path):
    path = tmp_path / "apps/api/prompts/mira/system.md"
    path.parent.mkdir(parents=True)
    path.write_text("Original prompt", encoding="utf-8")
    client = PromptClient()
    sync_prompt(client, target="mira", name="memoir/agents/mira/system",
                version=7, root=tmp_path)
    path.write_text("Local edit", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Langfuse prompt artifact"):
        sync_prompt(client, target="mira", name="memoir/agents/mira/system",
                    version=8, root=tmp_path)
    assert path.read_text(encoding="utf-8") == "Local edit"

    with pytest.raises(ValueError, match="repository prompt Markdown"):
        sync_prompt(client, target="../outside.md", name="memoir/agents/mira/system",
                    version=8, root=tmp_path)

    receipt_path = path.with_name(path.name + ".langfuse.json")
    receipt_path.unlink()
    with pytest.raises(ValueError, match="Missing Langfuse prompt receipt"):
        load_prompt_artifact(path)
    bad_client = PromptClient()
    bad_client.get_prompt = lambda name, **kwargs: SimpleNamespace(
        name=name, version=99, prompt="Wrong version", is_fallback=False)
    with pytest.raises(ValueError, match="different"):
        sync_prompt(bad_client, target="mira", name="memoir/agents/mira/system",
                    version=8, root=tmp_path)
    assert path.read_text(encoding="utf-8") == "Local edit"


def test_checked_in_reply_prompt_is_the_runtime_source():
    from apps.api.conversation_reply import reply_instructions

    assert reply_instructions() == render_prompt_artifact(ROOT / "apps/api/prompts/mira/system.md")


def test_current_export_uses_highest_numeric_version_without_production_label(tmp_path, monkeypatch):
    path = tmp_path / "apps/api/prompts/mira/system.md"
    path.parent.mkdir(parents=True)
    path.write_text("Old", encoding="utf-8")
    monkeypatch.setattr("scripts.export_langfuse_prompts.prompt_registry",
                        lambda root: {"memoir/agents/mira/system": str(path.relative_to(root))})

    class CurrentClient:
        def __init__(self):
            self.calls = []
            self.api = SimpleNamespace(prompts=SimpleNamespace(list=self.list))

        def list(self, **kwargs):
            return SimpleNamespace(data=[SimpleNamespace(name="memoir/agents/mira/system",
                                                          versions=[1, 3, 2])])

        def get_prompt(self, name, **kwargs):
            self.calls.append(kwargs)
            return SimpleNamespace(name=name, version=kwargs["version"],
                                   prompt="Current", is_fallback=False)

    client = CurrentClient()
    receipts = export_prompts(client, name="system", root=tmp_path)
    assert receipts[0]["version"] == 3
    assert path.read_text(encoding="utf-8") == "Current"
    assert [call["version"] for call in client.calls] == [3, 3]
    export_prompts(client, name="system", check=True, root=tmp_path)
    assert client.calls[-1]["version"] == 3


def test_unused_browser_instructions_are_not_managed_prompts():
    assert not any(name.startswith('memoir/interview/browser/') for name in prompt_registry())


def test_mira_prompts_are_agent_owned_and_redundant_fragments_are_retired():
    prefix = 'memoir/agents/mira/'
    registry = prompt_registry(include_unpublished=True)
    names = {name.removeprefix(prefix) for name in registry if name.startswith(prefix)}
    assert names == {
        'system', 'policy-review', 'repair', 'repair-codes', 'strategy-proposal',
    }
    assert all('/' not in name for name in names)
    assert all(path.startswith('apps/api/prompts/mira/')
               for name, path in registry.items() if name.startswith(prefix))
    assert not any(name.startswith('memoir/skills/memoir-interviewer/') for name in registry)
    evaluation_prefix = 'memoir/evaluation/agents/mira/'
    assert {name.removeprefix(evaluation_prefix) for name in registry
            if name.startswith(evaluation_prefix)} == {'comparison', 'rubric'}
    assert not any(name.startswith('memoir/evaluation/skills/memoir-interviewer/') for name in registry)


def test_skill_instructions_have_one_langfuse_name_and_developer_contracts_are_not_prompts():
    registry = prompt_registry()
    assert registry["memoir/skills/memoir-family-tree/instructions"] == "skills/memoir-family-tree/SKILL.md"
    assert registry["memoir/skills/memoir-place-journey/instructions"] == "skills/memoir-place-journey/SKILL.md"
    assert "memoir/memory/family-tree" not in registry
    assert "skills/memoir-family-tree/references/contract.md" not in registry.values()
    assert "skills/memoir-place-groups/references/contract.md" not in registry.values()
    assert "skills/memoir-place-journey/references/contract.md" not in registry.values()
    assert "skills/memoir-composer/references/sources.md" not in registry.values()


def test_catalog_has_one_owner_per_source_and_no_unused_receipts():
    registry = prompt_registry()
    receipts = set()
    for directory in ('skills', 'apps/api/prompts', 'tests/evaluation'):
        receipts.update(path.relative_to(ROOT).as_posix() for path in (ROOT / directory).rglob('*.langfuse.json'))
    assert receipts <= {relative + '.langfuse.json' for relative in registry.values()}
    assert all((ROOT / relative).is_file() for relative in registry.values())
    for name, relative in registry.items():
        receipt_path = ROOT / (relative + '.langfuse.json')
        if not receipt_path.is_file():
            continue  # New sources can await publication on their branch.
        receipt = json.loads(receipt_path.read_text())
        assert receipt['name'] == name
        if name.startswith('memoir/skills/'):
            assert relative.startswith('skills/' + name.split('/')[2] + '/')
        assert not name.startswith(('memoir/composer/', 'memoir/memory/', 'memoir/interview/', 'memoir/research/'))
    publishing = prompt_registry(include_unpublished=True)
    assert publishing['memoir/skills/memoir-composer/instructions'] == 'skills/memoir-composer/SKILL.md'
    assert 'skills/memoir-composer/references/workflows.md' not in registry.values()


def test_export_rejects_ambiguous_short_names():
    registry = prompt_registry()
    with pytest.raises(ValueError, match='Ambiguous prompt short name'):
        selected_prompts('en-AU', registry)
    assert selected_prompts('memoir/skills/memoir-composer/prepare', registry) == {
        'memoir/skills/memoir-composer/prepare': 'skills/memoir-composer/prompts/prepare.md'}


def test_prompt_experiment_uses_exact_prompt_and_dataset_input():
    calls = []
    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="Reply"))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=Completions()))
    prompt = SimpleNamespace(prompt="Pinned instructions", name="memoir/agents/mira/system", version=7)
    task = experiment_task(prompt, "model-a", client)

    assert task(item=SimpleNamespace(input={"text": "A memory"})) == "Reply"
    assert calls == [{"model": "model-a", "messages": [
        {"role": "system", "content": "Pinned instructions"},
        {"role": "user", "content": "A memory"}], "langfuse_prompt": prompt}]
    assert dataset_input_text({"question": "A memory"}) == '{"question": "A memory"}'
    with pytest.raises(ValueError, match="text or structured JSON"):
        task(item=SimpleNamespace(input=None))
    with pytest.raises(ValueError, match="timezone-aware"):
        dataset_version("2026-10-18T12:00:00")
    assert dataset_version("2026-10-18T12:00:00Z").utcoffset().total_seconds() == 0
    experiment_task(SimpleNamespace(prompt="Pinned instructions\n"), "model-a", client)(
        item=SimpleNamespace(input={"text": "A memory"}))
    assert calls[-1]["messages"][0]["content"] == "Pinned instructions\n"


def test_retired_workflows_cannot_be_exported_again():
    registry = prompt_registry()
    assert not any(name.startswith(("memoir/memory/fallback/", "memoir/memory/workspace/",
                                    "memoir/memory/marker/")) for name in registry)
    assert not {"memoir/interview/journalist", "memoir/composer/draft",
                "memoir/composer/organiser-task", "memoir/interview/collector-repair",
                "memoir/skills/memoir-author-timeline/legacy-marker"} & registry.keys()


def test_legacy_collector_setting_is_rejected(monkeypatch):
    from apps.api.collector_configuration import collector_configuration, CollectorConfigurationError

    monkeypatch.delenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', raising=False)
    assert collector_configuration('model').prompt_version == 'reply-v2'
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'legacy')
    with pytest.raises(CollectorConfigurationError):
        collector_configuration('model')
