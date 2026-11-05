"""The one-time development cleanup is archived, scoped and safe to resume."""
import hashlib
import json
from types import SimpleNamespace

import pytest

from scripts import reset_development_prompts as cleanup
from test_prompt_publication import repo, commit, git, NAME, TARGET


@pytest.fixture
def reset_repo(repo, monkeypatch):
    root, _, client = repo
    (root / 'config').mkdir()
    (root / 'docs').mkdir()
    (root / 'config/langfuse-evaluation-bindings.json').write_text(json.dumps({'project_id': 'project'}))
    records = [dict(name=NAME, published_versions=[dict(version=1, prompt=client.versions[1],
        config={'preserved': True}, labels=[], tags=[], sha256=cleanup.digest(client.versions[1]))])]
    source = json.dumps(records) + '\n'
    (root / 'docs/archive.json').write_text(source)
    manifest = dict(project_id='project', archive='docs/archive.json', archive_sha256=cleanup.digest(source),
                    remove=[], reset=[NAME])
    (root / cleanup.MANIFEST).write_text(json.dumps(manifest) + '\n')
    commit(root, 'Archive development prompts')
    git(root, 'push', 'origin', 'main')
    client.api.projects = SimpleNamespace(get=lambda: SimpleNamespace(data=[SimpleNamespace(id='project')]))
    monkeypatch.setattr(cleanup, 'prompt_registry', lambda *args, **kwargs: {NAME: TARGET})
    client.deletes = []
    def delete(name, **kwargs):
        assert kwargs == {'request_options': {'max_retries': 0}}
        client.deletes.append(name)
        client.versions.clear()
    client.api.prompts.delete = delete
    return root, client, manifest


def test_reset_plans_then_deletes_only_the_archived_prompt(reset_repo):
    root, client, _ = reset_repo
    assert cleanup.reset(client, root=root) == [dict(name=NAME, deleted=False)]
    assert not client.deletes
    assert cleanup.reset(client, root=root, execute=True) == [dict(name=NAME, deleted=True)]
    assert len(client.deletes) == 1
    assert cleanup.reset(client, root=root, execute=True) == []


@pytest.mark.parametrize('unsafe', ['foreign_project', 'new_version', 'changed_content', 'unmerged', 'uncommitted_archive', 'unknown_name'])
def test_reset_rejects_foreign_unmerged_or_unarchived_state(reset_repo, monkeypatch, unsafe):
    root, client, _ = reset_repo
    if unsafe == 'foreign_project':
        client.api.projects.get = lambda: SimpleNamespace(data=[SimpleNamespace(id='other')])
    elif unsafe == 'new_version':
        client.versions[2] = 'Unarchived prompt'
    elif unsafe == 'changed_content':
        client.versions[1] = 'Unarchived content'
    elif unsafe == 'unmerged':
        (root / 'new.txt').write_text('unmerged')
        commit(root)
    elif unsafe == 'uncommitted_archive':
        (root / 'docs/archive.json').write_text('[]\n')
    else:
        monkeypatch.setattr(cleanup, 'prompt_registry', lambda *args, **kwargs: {})
    with pytest.raises(ValueError):
        cleanup.reset(client, root=root, execute=True)
    assert not client.deletes


def test_reset_checks_uncertain_deletion_before_any_retry(reset_repo):
    root, client, _ = reset_repo
    delete = client.api.prompts.delete
    def uncertain(*args, **kwargs):
        delete(*args, **kwargs)
        raise TimeoutError()
    client.api.prompts.delete = uncertain
    assert cleanup.reset(client, root=root, execute=True)[0]['deleted']
    assert len(client.deletes) == 1


@pytest.mark.parametrize('versions', [[1], [1, 2]])
def test_reset_preserves_completed_baseline_and_later_versions(reset_repo, versions):
    root, client, manifest = reset_repo
    fetch = client.api.prompts.get
    def baseline(*args, **kwargs):
        value = fetch(*args, **kwargs)
        value.config = {'development_baseline': manifest['archive_sha256']}
        return value
    client.api.prompts.get = baseline
    client.versions = {v: 'Current assembled prompt' for v in versions}
    assert cleanup.reset(client, root=root, execute=True) == []
    assert not client.deletes
