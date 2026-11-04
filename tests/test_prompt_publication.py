"""Committed branch content is the source of prompt publication."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
from urllib.parse import quote, unquote

import pytest

from apps.api.prompt_artifact import load_prompt_artifact
from scripts import publish_langfuse_prompts as publication


NAME = 'fixture/prompt'
TARGET = 'skills/example.md'
ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], capture_output=True,
                          text=True, check=True).stdout.strip()


def commit(root, message='fixture'):
    git(root, 'add', '.')
    git(root, '-c', 'commit.gpgsign=false', 'commit', '-m', message)


def identity(root):
    git(root, 'config', 'user.name', 'Prompt test')
    git(root, 'config', 'user.email', 'prompt-test@example.invalid')


class Client:
    def __init__(self):
        self.versions = {1: 'Original prompt\n'}
        self.creates = []
        self.on_create = None
        self.api = SimpleNamespace(prompts=SimpleNamespace(list=self.list,get=self.get_api_prompt))

    def list(self, **kwargs):
        return SimpleNamespace(data=[SimpleNamespace(name=NAME, versions=list(self.versions))]
                               if self.versions else [])

    def get_prompt(self, name, **kwargs):
        return SimpleNamespace(name=name, version=kwargs['version'],
            prompt=self.versions[kwargs['version']], is_fallback=False, config={'preserved': True}, labels=[],tags=[])

    def get_api_prompt(self, name, **kwargs):
        assert name == quote(NAME, safe=''), 'Raw SDK paths require an encoded hierarchical prompt name'
        return self.get_prompt(unquote(name), **kwargs)

    def create_prompt(self, **kwargs):
        self.creates.append(kwargs)
        version = max(self.versions, default=0) + 1
        self.versions[version] = kwargs['prompt']
        if self.on_create:
            self.on_create()
        return self.get_prompt(kwargs['name'], version=version)

    def flush(self):
        pass


@pytest.fixture
def repo(tmp_path, monkeypatch):
    origin = tmp_path / 'origin.git'
    subprocess.run(['git', 'init', '--bare', str(origin)], capture_output=True, check=True)
    root = tmp_path / 'repo'
    subprocess.run(['git', 'init', '--initial-branch=main', str(root)], capture_output=True, check=True)
    identity(root)
    path = root / TARGET
    path.parent.mkdir(parents=True)
    path.write_text('Original prompt\n')
    receipt = {'schema_version': 1, 'name': NAME, 'type': 'text', 'version': 1,
               'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    path.with_name(path.name + '.langfuse.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n')
    hooks = root / '.githooks'
    hooks.mkdir()
    shutil.copy2(ROOT / '.githooks/post-merge', hooks / 'post-merge')
    scripts = root / 'scripts'
    scripts.mkdir()
    (scripts / 'publish_langfuse_prompts.py').write_text(
        "import json,sys\nfrom pathlib import Path\n"
        "Path('hook-called.json').write_text(json.dumps(sys.argv[1:]))\n")
    commit(root)
    git(root, 'remote', 'add', 'origin', str(origin))
    git(root, 'push', '-u', 'origin', 'main')
    client = Client()
    monkeypatch.setattr(publication, 'prompt_registry', lambda root, **kwargs: {NAME: TARGET})
    monkeypatch.setattr(publication, 'prompt_client', lambda *args: client)
    return root, origin, client


def merged_edit(root, text='Changed merged prompt\n'):
    (root / TARGET).write_text(text)
    commit(root, 'Merged prompt change')
    git(root, 'push', 'origin', 'main')


@pytest.fixture
def retired_repo(repo,monkeypatch):
    from scripts import retire_prompt_artifacts as retirement
    root,origin,client=repo
    source=root/TARGET
    receipt=json.loads(source.with_name(source.name+'.langfuse.json').read_text())
    content=source.read_text()
    source.unlink();source.with_name(source.name+'.langfuse.json').unlink()
    (root/'config').mkdir();(root/'docs').mkdir()
    archive='docs/retired.json'
    (root/archive).write_text(json.dumps([dict(name=NAME,source=TARGET,content=content,receipt=receipt,
        published_versions=[dict(version=1,prompt=content,sha256=receipt['sha256'],config={'preserved':True})])])+'\n')
    (root/'config/prompt-coverage.json').write_text(json.dumps(dict(retired={NAME:dict(source=TARGET,archive=archive)})))
    (root/'config/langfuse-evaluation-bindings.json').write_text(json.dumps(dict(project_id='project')))
    monkeypatch.setattr(publication,'prompt_registry',lambda *a,**k:{})
    monkeypatch.setattr(retirement,'prompt_registry',lambda *a,**k:{})
    client.api.projects=SimpleNamespace(get=lambda:SimpleNamespace(data=[SimpleNamespace(id='project')]))
    client.deletes=[]
    def delete(name, **kwargs):
        assert name == quote(NAME, safe='')
        assert kwargs['request_options'] == {'max_retries':0}
        client.deletes.append(unquote(name));client.versions.clear()
    client.api.prompts.delete=delete
    commit(root,'Retire reviewed prompt');git(root,'push','origin','main')
    return root,client


def test_retirement_is_archived_exact_scoped_and_idempotent(retired_repo):
    from scripts.retire_prompt_artifacts import retire
    root,client=retired_repo
    assert retire(client,root=root)[0]['present'] and not client.deletes
    assert retire(client,root=root,execute=True)[0]['deleted']
    assert client.deletes==[NAME]
    assert not retire(client,root=root,execute=True)[0]['present']
    assert client.deletes==[NAME]


@pytest.mark.parametrize('unsafe',['feature','wrong_project','new_version'])
def test_retirement_refuses_unmerged_or_unarchived_or_foreign_changes(retired_repo,unsafe):
    from scripts.retire_prompt_artifacts import retire
    root,client=retired_repo
    if unsafe=='feature':git(root,'checkout','-b','codex/unmerged-retirement')
    elif unsafe=='wrong_project':client.api.projects.get=lambda:SimpleNamespace(data=[SimpleNamespace(id='other')])
    else:client.versions[2]='New version not yet archived\n'
    with pytest.raises(ValueError):retire(client,root=root,execute=True)
    assert not client.deletes


def test_retirement_checks_uncertain_write_before_retrying(retired_repo):
    from scripts.retire_prompt_artifacts import retire
    root,client=retired_repo
    def uncertain(name, **kwargs):
        assert name == quote(NAME, safe='')
        assert kwargs['request_options'] == {'max_retries':0}
        client.deletes.append(unquote(name));client.versions.clear();raise TimeoutError()
    client.api.prompts.delete=uncertain
    assert retire(client,root=root,execute=True)[0]['deleted']
    assert client.deletes==[NAME]


def test_retirement_rejects_an_empty_committed_archive(retired_repo):
    from scripts.retire_prompt_artifacts import retire
    root,client=retired_repo
    path=root/'docs/retired.json'
    archived=json.loads(path.read_text());archived[0]['published_versions']=[]
    path.write_text(json.dumps(archived)+'\n')
    commit(root,'Incomplete archive');git(root,'push','origin','main')
    with pytest.raises(ValueError,match='Empty or duplicate recovery versions'):
        retire(client,root=root,execute=True)
    assert not client.deletes


def test_main_sync_reuses_identical_content_without_creating_versions(repo):
    root, _, client = repo
    paths = [root / TARGET, root / (TARGET + '.langfuse.json')]
    before = [path.stat().st_mtime_ns for path in paths]
    assert publication.main(['--check'], root=root) == 0
    assert publication.main([], root=root) == 0
    assert publication.main([], root=root) == 0
    assert client.creates == []
    assert [path.stat().st_mtime_ns for path in paths] == before
    assert load_prompt_artifact(root / TARGET) == 'Original prompt\n'


def test_agent_sync_saves_names_and_receipts_and_preserves_old_history(repo, monkeypatch):
    from scripts.prompt_registry import prompt_registry

    root, _, _ = repo
    registry = {name: target for name, target in prompt_registry(include_unpublished=True).items()
                if name.startswith(('memoir/agents/', 'memoir/evaluators/agents/mira/reply/'))}
    assert len(registry) == 7
    for target in registry.values():
        path = root / target
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / target, path)
    commit(root, 'Merged Mira and Atlas agent prompts')
    git(root, 'push', 'origin', 'main')

    legacy_name = 'memoir/skills/interviewer/reply'
    historical = SimpleNamespace(name=legacy_name, version=9, prompt='Historical instructions',
                                 is_fallback=False, config={})
    saved, creates = {legacy_name: historical}, []

    def list_prompts(**kwargs):
        return SimpleNamespace(data=[SimpleNamespace(name=name, versions=[prompt.version])
            for name, prompt in saved.items() if kwargs['name'] in name])

    def get_prompt(name, **kwargs):
        assert kwargs['version'] == saved[name].version
        return saved[name]

    def create_prompt(**kwargs):
        creates.append(kwargs)
        saved[kwargs['name']] = SimpleNamespace(name=kwargs['name'], version=1,
            prompt=kwargs['prompt'], config=kwargs['config'], is_fallback=False)
        return saved[kwargs['name']]

    client = SimpleNamespace(api=SimpleNamespace(prompts=SimpleNamespace(list=list_prompts)),
        get_prompt=get_prompt, create_prompt=create_prompt, flush=lambda: None)
    monkeypatch.setattr(publication, 'prompt_registry', lambda root, **kwargs: registry)
    monkeypatch.setattr(publication, 'prompt_client', lambda *args: client)
    assert publication.main([], root=root) == 0
    assert publication.main([], root=root) == 0
    assert {row['name'] for row in creates} == set(registry)
    assert len(creates) == 7
    assert saved[legacy_name] is historical
    for name, target in registry.items():
        path = root / target
        receipt = json.loads(path.with_name(path.name + '.langfuse.json').read_text())
        assert receipt['name'] == name
        assert receipt['version'] == 1
        assert receipt['sha256'] == hashlib.sha256((ROOT / target).read_bytes()).hexdigest()
        assert load_prompt_artifact(path) == (ROOT / target).read_text()


def test_merged_change_is_published_once_and_its_stale_receipt_is_refreshed(repo):
    root, _, client = repo
    merged_edit(root)
    with pytest.raises(ValueError, match='Invalid Langfuse'):
        load_prompt_artifact(root / TARGET)
    revision = git(root, 'rev-parse', 'HEAD')
    assert publication.main([], root=root) == 0
    assert publication.main([], root=root) == 0
    assert len(client.creates) == 1
    assert client.creates[0]['prompt'] == 'Changed merged prompt\n'
    assert client.creates[0]['config'] == {'preserved': True}
    assert revision in client.creates[0]['commit_message']
    assert load_prompt_artifact(root / TARGET) == 'Changed merged prompt\n'
    assert json.loads((root / (TARGET + '.langfuse.json')).read_text())['version'] == 2


def test_committed_feature_branch_syncs_without_a_remote_and_records_its_source(repo, capsys):
    root, _, client = repo
    branch = 'feature/prompt-sync'
    git(root, 'checkout', '-b', branch)
    git(root, 'remote', 'remove', 'origin')
    (root / TARGET).write_text('Feature branch prompt\n')
    commit(root, 'Feature prompt change')
    revision = git(root, 'rev-parse', 'HEAD')
    receipt = root / (TARGET + '.langfuse.json')
    before = receipt.read_bytes()

    assert publication.main(['--check'], root=root) == 1
    assert client.creates == []
    assert receipt.read_bytes() == before
    capsys.readouterr()
    assert publication.main([], root=root) == 0
    summary = json.loads(capsys.readouterr().out.splitlines()[0])
    assert summary['git_branch'] == branch
    assert summary['git_commit'] == revision
    assert publication.main(['--check'], root=root) == 0
    assert publication.main([], root=root) == 0
    assert len(client.creates) == 1
    assert client.creates[0]['commit_message'] == f'Publish {branch} {revision}'
    assert load_prompt_artifact(root / TARGET) == 'Feature branch prompt\n'


@pytest.mark.parametrize('state', ['detached', 'dirty', 'feature-dirty', 'unpushed', 'behind'])
def test_invalid_git_source_is_refused_before_langfuse(repo, monkeypatch, tmp_path, state):
    root, origin, client = repo
    if state == 'detached':
        git(root, 'checkout', '--detach')
    elif state in {'dirty', 'feature-dirty'}:
        if state == 'feature-dirty':
            git(root, 'checkout', '-b', 'feature')
        (root / TARGET).write_text('Uncommitted prompt')
    elif state == 'unpushed':
        (root / TARGET).write_text('Local-only main change')
        commit(root)
    else:
        other = tmp_path / 'other'
        subprocess.run(['git', 'clone', '--branch', 'main', str(origin), str(other)],
                       capture_output=True, check=True)
        identity(other)
        merged_edit(other)
    monkeypatch.setattr(publication, 'prompt_client', lambda *args: pytest.fail('No Langfuse access permitted'))
    assert publication.main([], root=root) == 1
    assert client.creates == []


def test_automatic_hook_quietly_skips_feature_branches(repo, monkeypatch, capsys):
    root, _, _ = repo
    git(root, 'checkout', '-b', 'feature')
    monkeypatch.setattr(publication, 'prompt_client', lambda *args: pytest.fail('No Langfuse access permitted'))
    assert publication.main(['--after-pull'], root=root) == 0
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('change', ['branch', 'commit'])
def test_git_source_change_during_planning_stops_before_publication(repo, change):
    root, _, client = repo
    git(root, 'checkout', '-b', 'feature')
    (root / TARGET).write_text('Feature branch prompt\n')
    commit(root)
    receipt = root / (TARGET + '.langfuse.json')
    before = receipt.read_bytes()

    def change_source(**kwargs):
        if change == 'branch':
            git(root, 'checkout', '-b', 'other-feature')
        else:
            (root / 'other.txt').write_text('New commit')
            commit(root)
        return client.list(**kwargs)

    client.api.prompts.list = change_source
    assert publication.main([], root=root) == 1
    assert client.creates == []
    assert receipt.read_bytes() == before


def test_read_only_check_does_not_publish_or_rewrite_receipts(repo):
    root, _, client = repo
    merged_edit(root)
    receipt = root / (TARGET + '.langfuse.json')
    before = receipt.read_bytes()
    assert publication.main(['--check'], root=root) == 1
    assert client.creates == []
    assert receipt.read_bytes() == before


def test_new_merged_prompt_is_created_without_a_bootstrap_escape_hatch(repo):
    root, _, client = repo
    client.versions = {}
    assert publication.main([], root=root) == 0
    assert len(client.creates) == 1
    assert load_prompt_artifact(root / TARGET) == 'Original prompt\n'


def test_named_sync_only_publishes_selected_prompts(repo, monkeypatch):
    root, _, client = repo
    other = 'skills/unrelated.md'
    (root / other).write_text('Unrelated prompt\n')
    merged_edit(root)
    monkeypatch.setattr(publication, 'prompt_registry',
        lambda root, **kwargs: {NAME: TARGET, 'fixture/unrelated': other})
    assert publication.main(['--name', NAME], root=root) == 0
    assert [item['name'] for item in client.creates] == [NAME]
    assert not (root / (other + '.langfuse.json')).exists()


def test_named_sync_rejects_unknown_prompts(repo):
    root, _, client = repo
    assert publication.main(['--name', 'fixture/unknown'], root=root) == 1
    assert not client.creates


def test_retry_after_uncertain_create_reuses_the_created_version(repo):
    root, _, client = repo
    merged_edit(root)
    def uncertain_result():
        raise OSError('Response lost after creation')
    client.on_create = uncertain_result
    assert publication.main([], root=root) == 1
    client.on_create = None
    assert publication.main(['--check'], root=root) == 1
    assert len(client.creates) == 1
    assert publication.main([], root=root) == 0
    assert len(client.creates) == 1
    assert load_prompt_artifact(root / TARGET) == 'Changed merged prompt\n'


def test_edits_during_publication_are_preserved_instead_of_overwritten(repo):
    root, _, client = repo
    merged_edit(root)
    receipt = root / (TARGET + '.langfuse.json')
    before = receipt.read_bytes()
    client.on_create = lambda: (root / TARGET).write_text('Concurrent local edit')
    assert publication.main([], root=root) == 1
    assert (root / TARGET).read_text() == 'Concurrent local edit'
    assert receipt.read_bytes() == before


def test_wrong_remote_version_is_rejected_before_any_creation(repo, monkeypatch):
    root, _, client = repo
    merged_edit(root)
    original = client.get_prompt
    def wrong_version(name, **kwargs):
        prompt = original(name, **kwargs)
        prompt.version = 99
        return prompt
    monkeypatch.setattr(client, 'get_prompt', wrong_version)
    assert publication.main([], root=root) == 1
    assert client.creates == []


def test_edit_during_remote_readback_cannot_be_overwritten(repo, monkeypatch):
    root, _, client = repo
    merged_edit(root)
    original = client.get_prompt
    readbacks = []
    def edit_on_readback(name, **kwargs):
        prompt = original(name, **kwargs)
        if kwargs['version'] == 2:
            readbacks.append(2)
            if len(readbacks) == 2:
                (root / TARGET).write_text('Edit during remote readback')
        return prompt
    monkeypatch.setattr(client, 'get_prompt', edit_on_readback)
    before = (root / (TARGET + '.langfuse.json')).read_bytes()
    assert publication.main([], root=root) == 1
    assert (root / TARGET).read_text() == 'Edit during remote readback'
    assert (root / (TARGET + '.langfuse.json')).read_bytes() == before


@pytest.mark.parametrize('existing', ['configured', 'default'])
def test_hook_installation_preserves_existing_hooks(repo, existing):
    root, _, _ = repo
    if existing == 'configured':
        git(root, 'config', 'core.hooksPath', 'other-hooks')
    else:
        (root / '.git/hooks/post-merge').write_text('#!/bin/sh\nexit 0\n')
    with pytest.raises(ValueError, match='existing|Existing'):
        publication.install_hook(root)


def test_real_git_pull_dispatches_the_tracked_hook(repo, tmp_path):
    root, origin, _ = repo
    publication.install_hook(root)
    publication.install_hook(root)
    assert git(root, 'config', '--get', 'core.hooksPath') == '.githooks'
    other = tmp_path / 'upstream'
    subprocess.run(['git', 'clone', '--branch', 'main', str(origin), str(other)],
                   capture_output=True, check=True)
    identity(other)
    merged_edit(other)
    git(root, 'pull', '--ff-only', 'origin', 'main')
    assert json.loads((root / 'hook-called.json').read_text()) == ['--after-pull']
