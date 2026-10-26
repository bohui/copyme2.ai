"""Checkpoint recovery uses isolated workspaces and an in-process HTTP transport."""
import json

import pytest

from test_novel_to_game_experiment import PACKAGE, runner


@pytest.fixture
def stage_runner(tmp_path, monkeypatch):
    module = runner()
    module.HERE = tmp_path / 'game'
    module.ROOT = tmp_path / 'repo'
    fixture = module.ROOT / 'skills/memoir-story-game/tests/fixtures/age-eight.json'
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes((PACKAGE.parents[1] / 'skills/memoir-story-game/tests/fixtures/age-eight.json').read_bytes())
    module.KEY = 'synthetic-checkpoint-test-key'
    calls = []
    files = {}
    client = module.httpx.Client

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        stage = json.loads(body['input'])['stage']
        result = dict(id='synthetic-response-' + str(len(calls)), status='completed',
            model=module.MODEL, reasoning=dict(effort='max'), output=[dict(type='message',
                content=[dict(type='output_text', text=json.dumps(dict(
                    files=[dict(path=p, content=v) for p, v in files[stage].items()], notes='Synthetic fixture')))])])
        event = dict(type='response.completed', response=result)
        return module.httpx.Response(200, text='data: ' + json.dumps(event) + '\n\n')

    monkeypatch.setattr(module.httpx, 'Client', lambda **kwargs: client(
        transport=module.httpx.MockTransport(respond), **kwargs))
    files['concept'] = {'concepts/CONCEPT.md': 'Saved fictional RPG concept'}
    return module, files, calls


def test_checkpoint_restores_missing_concept_for_downstream_design(stage_runner):
    module, files, calls = stage_runner
    receipt = module.run_stage('concept')
    working = module.HERE / 'concepts/CONCEPT.md'
    working.unlink()

    assert module.run_stage('concept') == receipt
    assert working.read_text() == files['concept']['concepts/CONCEPT.md']
    design = json.loads(module.run_stage('design', dry_run=True)['input'])
    assert design['saved_artifacts']['concepts/CONCEPT.md'] == working.read_text()
    assert len(calls) == 1
    assert len(list((module.HERE / 'stages/concept').glob('attempt-*-request.json'))) == 1


def test_checkpoint_rejects_altered_working_concept_without_overwriting_or_calling(stage_runner):
    module, files, calls = stage_runner
    module.run_stage('concept')
    working = module.HERE / 'concepts/CONCEPT.md'
    working.write_text('An intentional later revision')

    with pytest.raises(ValueError, match='Working artifact differs.*concepts/CONCEPT.md'):
        module.run_stage('concept')
    assert working.read_text() == 'An intentional later revision'
    assert len(calls) == 1
    archive = module.HERE / 'stages/concept/artifacts/concepts/CONCEPT.md'
    assert archive.read_text() == files['concept']['concepts/CONCEPT.md']


def test_checkpoint_reuses_unchanged_working_output_without_rewriting_it(stage_runner):
    module, files, calls = stage_runner
    receipt = module.run_stage('concept')
    working = module.HERE / 'concepts/CONCEPT.md'
    before = working.stat().st_mtime_ns
    assert module.run_stage('concept') == receipt
    assert working.read_text() == files['concept']['concepts/CONCEPT.md']
    assert working.stat().st_mtime_ns == before
    assert len(calls) == 1


@pytest.mark.parametrize('mutation', ['missing', 'altered'])
def test_fresh_analyze_checkpoint_checks_working_bible_before_concept(stage_runner, mutation):
    module, files, calls = stage_runner
    bible = (PACKAGE / 'examples/age-eight-patch/analysis/SOURCE_BIBLE.md').read_text()
    files['analyze'] = {'analysis/SOURCE_BIBLE.md': bible}
    receipt = module.run_stage('analyze')
    working = module.HERE / 'analysis/SOURCE_BIBLE.md'
    assert not (module.HERE / 'analysis-reused.json').exists()
    if mutation == 'missing':
        working.unlink()
        assert module.run_stage('analyze') == receipt
        assert working.read_text() == bible
        concept = json.loads(module.run_stage('concept', dry_run=True)['input'])
        assert concept['saved_artifacts']['analysis/SOURCE_BIBLE.md'] == bible
    else:
        working.write_text(bible + '\nAn unverified revision')
        with pytest.raises(ValueError, match='Working artifact differs.*analysis/SOURCE_BIBLE.md'):
            module.run_stage('analyze')
        assert working.read_text() == bible + '\nAn unverified revision'
        with pytest.raises(AssertionError, match='changed after generation'):
            module.run_stage('concept', dry_run=True)
    assert len(calls) == 1


@pytest.mark.parametrize('mutation', ['missing', 'altered'])
def test_invalid_archive_regenerates_instead_of_restoring_unverified_content(stage_runner, mutation):
    module, files, calls = stage_runner
    module.run_stage('concept')
    archive = module.HERE / 'stages/concept/artifacts/concepts/CONCEPT.md'
    if mutation == 'missing':
        archive.unlink()
    else:
        archive.write_text('Corrupted saved artifact')
    (module.HERE / 'concepts/CONCEPT.md').unlink()
    files['concept']['concepts/CONCEPT.md'] = 'Newly generated fictional concept'

    receipt = module.run_stage('concept')
    assert receipt['response_id'] == 'synthetic-response-2'
    assert len(calls) == 2
    assert (module.HERE / 'concepts/CONCEPT.md').read_text() == archive.read_text() == files['concept']['concepts/CONCEPT.md']
    assert receipt['outputs']['concepts/CONCEPT.md'] == module.digest(archive.read_text())
    assert len(list((module.HERE / 'stages/concept').glob('attempt-*-request.json'))) == 2


@pytest.mark.parametrize('mutation', ['task', 'input'])
def test_changed_request_regenerates_without_restoring_an_old_output(stage_runner, mutation):
    module, files, calls = stage_runner
    before = module.run_stage('concept')
    (module.HERE / 'concepts/CONCEPT.md').unlink()
    kwargs = {}
    if mutation == 'task':
        kwargs['task_override'] = 'A revised approved concept task'
    else:
        (module.HERE / 'PRODUCT_BRIEF.md').write_text('A revised approved product brief')
    files['concept']['concepts/CONCEPT.md'] = 'A revised fictional concept'
    after = module.run_stage('concept', **kwargs)
    assert before['request_sha256'] != after['request_sha256']
    assert after['response_id'] == 'synthetic-response-2'
    assert (module.HERE / 'concepts/CONCEPT.md').read_text() == files['concept']['concepts/CONCEPT.md']
    assert len(calls) == 2


def test_changed_source_cannot_reuse_fresh_analysis_with_the_same_ids(stage_runner):
    module, files, calls = stage_runner
    files['analyze'] = {'analysis/SOURCE_BIBLE.md': (PACKAGE / 'examples/age-eight-patch/analysis/SOURCE_BIBLE.md').read_text()}
    before = module.run_stage('analyze')
    source_path = module.HERE / 'source/input.json'
    source = json.loads(source_path.read_text())
    source['input']['chapters'][0]['blocks'][0]['text'] += ' Another fictional detail.'
    source_path.write_text(json.dumps(source))
    with pytest.raises(AssertionError, match='does not match the full input'):
        module.run_stage('concept', dry_run=True)
    after = module.run_stage('analyze')
    assert before['request_sha256'] != after['request_sha256']
    assert before['source_sha256'] != after['source_sha256']
    assert after['response_id'] == 'synthetic-response-2'
    assert len(calls) == 2


def design_checkpoint(stage_runner):
    module, files, calls = stage_runner
    files['design'] = {
        'design/GAME_DESIGN.md': 'Approved fictional continuous walk',
        'design/JOURNEY_PLAN.json': (PACKAGE / 'examples/age-eight-linear/JOURNEY_PLAN.json').read_text(),
    }
    module.run_stage('concept')
    receipt = module.run_stage('design')
    return receipt


def test_missing_design_plan_is_restored_before_host_materialisation(stage_runner):
    module, files, calls = stage_runner
    receipt = design_checkpoint(stage_runner)
    (module.HERE / 'design/JOURNEY_PLAN.json').unlink()
    (module.HERE / 'build/app/index.html').unlink()

    assert module.run_stage('design') == receipt
    assert (module.HERE / 'design/JOURNEY_PLAN.json').read_text() == files['design']['design/JOURNEY_PLAN.json']
    html = (module.HERE / 'build/app/index.html').read_text()
    assert 'id="memoir-source"' in html and 'id="memoir-journey"' in html
    for name, expected in module.runtime_hashes().items():
        if name != 'index.html':
            assert module.digest((module.HERE / 'build/app' / name).read_text()) == expected
    assert len(calls) == 2


def test_output_set_is_checked_before_restoring_any_missing_file(stage_runner):
    module, files, calls = stage_runner
    design_checkpoint(stage_runner)
    missing = module.HERE / 'design/GAME_DESIGN.md'
    missing.unlink()
    altered = module.HERE / 'design/JOURNEY_PLAN.json'
    revision = altered.read_text() + '\n'
    altered.write_text(revision)
    with pytest.raises(ValueError, match='Working artifact differs.*design/JOURNEY_PLAN.json'):
        module.run_stage('design')
    assert not missing.exists()
    assert altered.read_text() == revision
    assert len(calls) == 2


def test_design_receipt_requires_the_complete_output_manifest(stage_runner):
    module, files, calls = stage_runner
    receipt = design_checkpoint(stage_runner)
    receipt['outputs'].pop('design/JOURNEY_PLAN.json')
    (module.HERE / 'stages/design/checkpoint.json').write_text(json.dumps(receipt))
    (module.HERE / 'design/JOURNEY_PLAN.json').unlink()
    with pytest.raises(ValueError, match='missing required stage outputs'):
        module.run_stage('design')
    assert not (module.HERE / 'design/JOURNEY_PLAN.json').exists()
    assert len(calls) == 2


@pytest.mark.parametrize('mutation', ['missing_brief', 'later_style', 'missing_css'])
def test_whitebox_reuse_preserves_shared_build_output_evolution(stage_runner, mutation):
    module, files, calls = stage_runner
    design_checkpoint(stage_runner)
    files['whitebox'] = {'build/BUILD_BRIEF.md': 'Synthetic whitebox brief', 'build/app/game.css': 'body { color: navy; }'}
    receipt = module.run_stage('whitebox')
    brief, css = module.HERE / 'build/BUILD_BRIEF.md', module.HERE / 'build/app/game.css'
    brief.unlink()
    if mutation == 'missing_brief':
        assert module.run_stage('whitebox') == receipt
        assert brief.read_text() == files['whitebox']['build/BUILD_BRIEF.md']
        assert css.read_text() == files['whitebox']['build/app/game.css']
    else:
        if mutation == 'later_style':
            css.write_text('/* Intentional later production styling */')
        else:
            css.unlink()  # Host preparation seeds a default stylesheet before the reuse check.
        with pytest.raises(ValueError, match='Working artifact differs.*build/app/game.css'):
            module.run_stage('whitebox')
        assert not brief.exists()
        if mutation == 'later_style':
            assert css.read_text() == '/* Intentional later production styling */'
        else:
            assert css.read_text() == '/* Model styling extends the host-owned journey runtime. */\n'
    assert len(calls) == 3


def test_returning_to_whitebox_preserves_actual_production_outputs(stage_runner):
    from PIL import Image
    from game_assets import record_scene

    module, files, calls = stage_runner
    design_checkpoint(stage_runner)
    files['whitebox'] = {'build/BUILD_BRIEF.md': 'Whitebox brief', 'build/app/game.css': '/* Whitebox styling */'}
    module.run_stage('whitebox')
    (module.HERE / 'whitebox-feedback.json').write_text('Synthetic whitebox feedback')
    scenes = sorted({s['scene'] for s in json.loads(files['design']['design/JOURNEY_PLAN.json'])['segments']})
    art_plan = dict(style='gouache-childhood-v1', illustrations=[dict(id='places', kind='scene-background',
        columns=3, rows=2, scenes=scenes, prompt='Synthetic unpeopled places for the checkpoint test.')])
    files['art'] = {'design/ART_DIRECTION.md': 'Synthetic art direction', 'design/SCENE_ART_PLAN.json': json.dumps(art_plan)}
    module.run_stage('art')
    image = module.HERE.parent / 'synthetic-scene.png'
    Image.new('RGB', (12, 8), 'green').save(image)
    record_scene(module.HERE, 'places', image, module.ROOT / 'var/novel-to-game-scene-cache')
    files['production'] = {'build/BUILD_BRIEF.md': 'Production brief', 'build/app/game.css': '/* Production styling */'}
    production = module.run_stage('production')

    with pytest.raises(ValueError, match='Working artifact differs.*build/BUILD_BRIEF.md'):
        module.run_stage('whitebox')
    for name, content in files['production'].items():
        assert (module.HERE / name).read_text() == content
        assert production['outputs'][name] == module.digest(content)
    assert len(calls) == 5


@pytest.mark.parametrize('redirect', [None, 'inside_file', 'outside_file', 'inside_parent', 'outside_parent'])
def test_legacy_html_archive_maps_to_template_then_inserts_verified_source(stage_runner, redirect):
    module, files, calls = stage_runner
    # Exercise the retained legacy output mapping without allowing HTML in current build stages.
    module.STAGES['legacy_build'] = dict(module.STAGES['concept'], outputs=['build/app/index.html'])
    files['legacy_build'] = {'build/app/index.html': '<!doctype html><!-- MEMOIR_SOURCE -->'}
    module.initialise()
    (module.HERE / 'build/app').mkdir(parents=True)
    receipt = module.run_stage('legacy_build')
    assert set(receipt['outputs']) == {'build/template.html'}
    (module.HERE / 'build/template.html').unlink()
    target = module.HERE / 'build/app/index.html'
    target.unlink()

    if redirect:
        redirected = (module.HERE if redirect.startswith('inside') else module.HERE.parent) / 'redirected'
        redirected.mkdir()
        sentinel = redirected / 'index.html'
        sentinel.write_text('Preserve the redirected file')
        if redirect.endswith('parent'):
            target.parent.rmdir()
            target.parent.symlink_to(redirected, target_is_directory=True)
        else:
            target.symlink_to(sentinel)
        with pytest.raises(ValueError, match='Unsafe checkpoint artifact path'):
            module.run_stage('legacy_build')
        assert sentinel.read_text() == 'Preserve the redirected file'
        assert len(calls) == 1
        return

    assert module.run_stage('legacy_build') == receipt
    assert (module.HERE / 'build/template.html').read_text() == files['legacy_build']['build/app/index.html']
    html = (module.HERE / 'build/app/index.html').read_text()
    assert '<!-- MEMOIR_SOURCE -->' not in html
    source = json.loads(html.split('type="application/json">')[1].split('</script>')[0])
    saved = json.loads((module.HERE / 'source/input.json').read_text())['input']
    assert source == module.public_source(saved)
    assert len(calls) == 1


@pytest.mark.parametrize('path', ['../outside.md', '/tmp/outside.md', 'build/template.html'])
def test_receipt_cannot_restore_paths_outside_the_stage_allowlist(stage_runner, path):
    module, files, calls = stage_runner
    module.run_stage('concept')
    checkpoint = module.HERE / 'stages/concept/checkpoint.json'
    receipt = json.loads(checkpoint.read_text())
    receipt['outputs'] = {path: module.digest('Not an allowed concept output')}
    checkpoint.write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match='disallowed stage output paths'):
        module.run_stage('concept')
    assert not (module.HERE / 'build/template.html').exists()
    assert len(calls) == 1


@pytest.mark.parametrize('location', ['working_file', 'working_parent', 'archive_file', 'archive_parent'])
@pytest.mark.parametrize('destination', ['inside', 'outside'])
def test_checkpoint_refuses_symlinks_before_reading_or_restoring(stage_runner, location, destination):
    module, files, calls = stage_runner
    module.run_stage('concept')
    working = module.HERE / 'concepts/CONCEPT.md'
    archive = module.HERE / 'stages/concept/artifacts/concepts/CONCEPT.md'
    target = working if location.startswith('working') else archive
    original = target.read_text()
    target.unlink()
    redirected = (module.HERE if destination == 'inside' else module.HERE.parent) / 'redirected'
    redirected.mkdir()
    sentinel = redirected / 'CONCEPT.md'
    sentinel.write_text(original)
    if location.endswith('parent'):
        target.parent.rmdir()
        target.parent.symlink_to(redirected, target_is_directory=True)
    else:
        target.symlink_to(sentinel)
    if location.startswith('archive'):
        working.unlink()

    with pytest.raises(ValueError, match='Unsafe checkpoint artifact path'):
        module.run_stage('concept')
    assert sentinel.read_text() == original
    if location.startswith('archive'):
        assert not working.exists()
    assert len(calls) == 1
