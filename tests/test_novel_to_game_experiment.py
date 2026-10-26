"""The branch experiment prepares RPG requests offline and resumes exact checkpoints."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'experiments/novel-to-game'


def runner():
    spec = importlib.util.spec_from_file_location('novel_game_experiment', PACKAGE / 'stages.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_default_preview_needs_no_credentials_and_contains_the_complete_source(tmp_path):
    workspace = tmp_path / 'rpg'
    result = subprocess.run([sys.executable, str(PACKAGE / 'stages.py'), 'concept',
        '--output', str(workspace), '--env-file', str(tmp_path / 'missing.env')],
        text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)['calls'] == 0
    request = json.loads((workspace / 'stages/concept/preview-request.json').read_text())
    packet = json.loads(request['input'])
    source = json.loads((ROOT / 'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())['input']
    assert request['model'] == 'gpt-6.1-sol' and request['reasoning']['effort'] == 'max'
    assert request['stream'] is True
    assert request['metadata']['upstream_revision'] == runner().dependency_revision()
    assert packet['format_contract']['format'] == 'rpg-side-scroller'
    assert packet['format_contract']['navigation'] == 'horizontal_with_scrolling_camera'
    assert packet['format_contract']['controlled_character'] == 'memoir_author'
    assert packet['source']['chapters'] == source['chapters']
    assert {e['id'] for e in packet['source']['timeline']} == {e['id'] for e in source['timeline']}
    assert len(packet['source']['chapters']) == len(packet['source']['timeline']) == 10
    assert not (workspace / 'stages/concept/checkpoint.json').exists()


def test_legacy_puzzle_workspace_is_preserved_and_cannot_supply_rpg_checkpoints(tmp_path):
    module = runner()
    module.HERE = tmp_path
    original = tmp_path / 'CONCEPT.md'
    original.write_text('Historical repair-puzzle concept')
    with pytest.raises(AssertionError, match='fresh output directory'):
        module.run_stage('concept', dry_run=True)
    assert original.read_text() == 'Historical repair-puzzle concept'
    assert not (tmp_path / 'format-profile.json').exists()


def test_changed_prose_cannot_reuse_analysis_with_the_same_chapter_ids(tmp_path):
    module = runner()
    module.HERE = tmp_path / 'output'
    module.ROOT = tmp_path / 'repo'
    fixture = module.ROOT / 'skills/memoir-story-game/tests/fixtures/age-eight.json'
    fixture.parent.mkdir(parents=True)
    value = json.loads((ROOT / 'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())
    value['input']['chapters'][0]['blocks'][0]['text'] += ' A changed source passage.'
    fixture.write_text(json.dumps(value))
    with pytest.raises(AssertionError, match='does not match the full input'):
        module.run_stage('concept', dry_run=True)
    assert not (module.HERE / 'analysis-reused.json').exists()


def test_matching_saved_stage_reuses_its_artifact_without_opening_a_provider(tmp_path, monkeypatch):
    module = runner()
    module.HERE = tmp_path
    request = module.run_stage('concept', dry_run=True)
    stage = tmp_path / 'stages/concept'
    artifact = stage / 'artifacts/concepts/CONCEPT.md'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('Saved RPG concept')
    checkpoint = dict(request_sha256=module.digest(json.dumps(request, sort_keys=True, ensure_ascii=False)),
        outputs={'concepts/CONCEPT.md': module.digest(artifact.read_text())}, response_id='saved-rpg-response')
    (stage / 'checkpoint.json').write_text(json.dumps(checkpoint))

    def forbidden(*args, **kwargs):
        raise AssertionError('provider must not open for a matching checkpoint')

    monkeypatch.setattr(module.httpx, 'Client', forbidden)
    assert module.run_stage('concept')['response_id'] == 'saved-rpg-response'
    assert not list(stage.glob('attempt-*-request.json'))


def test_archived_code_prompts_and_game_match_the_original_snapshot():
    module = runner()
    archive = PACKAGE / 'examples/age-eight-patch'
    manifest = json.loads((archive / 'snapshot.json').read_text())
    assert len(manifest['files']) == 24
    for name, expected in manifest['files'].items():
        assert module.digest((archive / name).read_text()) == expected, name


def test_repository_harness_links_the_dependency_and_memoir_adapter():
    skills = {'novel-to-game', 'novel-game-analyze', 'game-concept', 'game-world-design',
        'game-art-direction', 'game-build', 'game-qa'}
    links = ROOT / '.agents/skills'
    for name in skills:
        link = links / name
        assert link.is_symlink()
        assert link.resolve() == ROOT / 'deps/novel-to-game/skills' / name
        assert (link / 'SKILL.md').is_file()
    assert (links / 'memoir-novel-to-game').resolve() == PACKAGE


def test_missing_dependency_gives_the_install_command(tmp_path):
    module = runner()
    module.SKILL = tmp_path / 'missing/skills'
    with pytest.raises(RuntimeError, match='make deps-install'):
        module.dependency_revision()


def test_upstream_upgrade_changes_request_provenance_and_invalidates_reuse(tmp_path, monkeypatch):
    module = runner()
    dependency = tmp_path / 'upstream'
    module.SKILL = dependency / 'skills'
    module.HERE = tmp_path / 'output'
    for name in ('novel-to-game/SKILL.md', 'game-concept/SKILL.md',
                 'game-concept/references/concept-method.md'):
        path = module.SKILL / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Synthetic upstream instructions')

    def git(*args):
        return subprocess.check_output(['git', '-C', str(dependency), *args], text=True).strip()

    git('init', '-q')
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'v1')
    before = module.run_stage('concept', dry_run=True)
    assert before['metadata']['upstream_revision'] == git('rev-parse', 'HEAD')
    stage = module.HERE / 'stages/concept'
    artifact = stage / 'artifacts/concepts/CONCEPT.md'
    artifact.parent.mkdir(parents=True)
    artifact.write_text('Previously generated concept')
    (stage / 'checkpoint.json').write_text(json.dumps(dict(
        request_sha256=module.digest(json.dumps(before, sort_keys=True, ensure_ascii=False)),
        outputs={'concepts/CONCEPT.md': module.digest(artifact.read_text())}, response_id='old-result')))
    (module.SKILL / 'game-concept/SKILL.md').write_text('Updated upstream instructions')
    with pytest.raises(RuntimeError, match='local changes'):
        module.run_stage('concept', dry_run=True)
    git('add', '.')
    git('-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', 'commit', '-qm', 'v2')
    after = module.run_stage('concept', dry_run=True)
    assert after['metadata']['upstream_revision'] == git('rev-parse', 'HEAD')
    assert before['metadata']['upstream_revision'] != after['metadata']['upstream_revision']
    assert before['instructions'] != after['instructions']

    def new_generation(*args, **kwargs):
        raise RuntimeError('new dependency requires regeneration')

    monkeypatch.setattr(module.httpx, 'Client', new_generation)
    with pytest.raises(RuntimeError, match='requires regeneration'):
        module.run_stage('concept')
    assert artifact.read_text() == 'Previously generated concept'


@pytest.mark.parametrize('duration', [None, True, 0, 49, 5001, '1000'])
def test_replay_rejects_missing_or_unbounded_held_inputs(duration):
    spec = importlib.util.spec_from_file_location('novel_game_verify', PACKAGE / 'verify.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with pytest.raises(ValueError):
        module.hold_duration({'duration_ms': duration})
