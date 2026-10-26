"""Generation uses a validated, host-owned continuous walk rather than a free-form hub."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

from test_novel_to_game_experiment import runner

PACKAGE = Path(__file__).resolve().parents[1] / 'experiments/novel-to-game'


def journey():
    runner()  # Resolve the package's sibling imports, as the CLI does.
    spec = importlib.util.spec_from_file_location('test_memoir_journey', PACKAGE / 'journey.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def packet():
    return json.loads((PACKAGE.parents[1] / 'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())['input']


def plan():
    return json.loads((PACKAGE / 'examples/age-eight-linear/JOURNEY_PLAN.json').read_text())


def test_complete_source_uses_one_forward_stream_with_reused_locations():
    module, value, source = journey(), plan(), packet()
    bound = module.bind_journey(value, source)
    assert [s['chapter'] for s in bound['stops']] == ['C' + str(i) for i in range(1, 11)]
    assert {s['avatar'] for s in bound['segments']} == {'child-casual'}
    assert {s['age_label'] for s in bound['segments']} == {'Age 8'}
    assert 'uncertain' in bound['order_note']
    assert [s['scene'] for s in bound['segments']].count('school') == 2
    assert all(s['start'] == bound['segments'][i - 1]['end'] for i, s in enumerate(bound['segments']) if i)


@pytest.mark.parametrize('mutation,reason', [
    ('order', 'timeline order'), ('duplicate', 'timeline order'), ('gap', 'without gaps'),
    ('reverse', 'positions must increase'), ('portal', 'not travel links'),
])
def test_invalid_model_routes_are_rejected_before_build(mutation, reason):
    value, source, module = plan(), packet(), journey()
    if mutation == 'order':
        value['stops'][0], value['stops'][1] = value['stops'][1], value['stops'][0]
    elif mutation == 'duplicate':
        value['stops'][1]['chapter'] = 'C1'
    elif mutation == 'gap':
        value['segments'][1]['start'] += 100
    elif mutation == 'reverse':
        value['stops'][2]['x'] = value['stops'][1]['x'] - 10
    else:
        value['segments'][1]['travel_to'] = 'home'
    with pytest.raises(ValueError, match=reason):
        module.validate_journey(value, source['chapters'], source['timeline'])


def test_life_stage_and_approved_profession_select_stock_variants():
    module = journey()
    source = packet()
    value = dict(version=1, blend=180, segments=[], stops=[])
    ages = [8, 16, 26, 40, 45, 45, 70, 72, 75, 80]
    for i, (event, age) in enumerate(zip(source['timeline'], ages)):
        event['age'] = dict(minimum=age, maximum=age)
        value['segments'].append(dict(id='part-' + str(i), scene='home', title='A remembered place', start=i * 1000, end=(i + 1) * 1000))
        value['stops'].append(dict(chapter='C' + str(i + 1), segment='part-' + str(i), x=i * 1000 + 160))
    profile = {'C5': dict(outfit='professional', profession='Teacher'), 'C6': dict(outfit='workwear', profession='Carpenter')}
    bound = module.bind_journey(value, source, profile)
    assert [s['avatar'] for s in bound['segments'][:7]] == ['child-casual', 'teen-casual',
        'young-adult-casual', 'adult-casual', 'adult-professional', 'adult-workwear', 'senior-casual']
    assert bound['segments'][4]['profession'] == 'Teacher'
    assert module.bind_journey(value, source)['segments'][4]['avatar'] == 'adult-casual'
    with pytest.raises(ValueError, match='approved profession'):
        module.bind_journey(value, source, {'C5': dict(outfit='workwear')})


def test_materialisation_preserves_source_owns_runtime_and_makes_real_input_replay(tmp_path):
    module, source, value = journey(), packet(), plan()
    module.write_json(tmp_path, 'design/JOURNEY_PLAN.json', value)
    public = runner().public_source(source)
    public['chapters'][0]['text'] += '\n</script><script>untrusted source text</script>'
    module.materialise(tmp_path, source, public)
    app = tmp_path / 'build/app'
    html = (app / 'index.html').read_text()
    assert 'data-route="single-chronological-stream"' in html
    assert '</script><script>untrusted source text</script>' not in html
    assert '\\u003c/script\\u003e' in html
    assert 'game.js' not in html
    for name in ('journey-runtime.js', 'journey-runtime.css'):
        assert (app / name).read_bytes() == (PACKAGE / 'runtime' / name).read_bytes()
    replay = json.loads((tmp_path / 'build/playthrough.json').read_text())
    assert len(replay['steps']) <= 100
    assert [s['checkpoint'] for s in replay['steps'] if 'checkpoint' in s] == ['input', 'coreLoop', 'outcome', 'restart']
    assert all(s['selector'] == '#right' and 50 <= s['duration_ms'] <= 5000 for s in replay['steps'] if s['action'] == 'hold')
    assert sum(s['selector'] == '#passage' for s in replay['steps']) == 10


def test_builder_gets_runtime_fingerprint_and_cannot_replace_html_or_movement(tmp_path):
    module = runner()
    module.HERE = tmp_path / 'game'
    module.initialise()
    for name in ('concepts/CONCEPT.md', 'design/GAME_DESIGN.md'):
        path = module.HERE / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('Approved linear walk')
    (module.HERE / 'design/JOURNEY_PLAN.json').write_text(json.dumps(plan()))
    request = module.run_stage('whitebox', dry_run=True)
    payload = json.loads(request['input'])
    assert payload['allowed_output_paths'] == ['build/BUILD_BRIEF.md', 'build/app/game.css']
    assert set(payload['host_runtime_sha256']) == {'index.html', 'journey-runtime.js', 'journey-runtime.css'}
    assert (module.HERE / 'build/app/index.html').is_file()
    assert '<!-- MEMOIR_JOURNEY -->' in payload['saved_artifacts']['build/template.html']
    assert 'whitebox_logic' not in module.STAGES and 'whitebox_replay' not in module.STAGES


def test_custom_memoir_input_is_saved_and_resumed_without_age_eight_analysis(tmp_path):
    source = packet()
    source['chapters'] = source['chapters'][:2]
    source['timeline'] = source['timeline'][:2]
    source['title'] = 'An approved lifetime story'
    source['fictional'] = True
    for event, age in zip(source['timeline'], (26, 70)):
        event['age'] = dict(minimum=age, maximum=age)
    input_file, brief, output = tmp_path / 'source.json', tmp_path / 'brief.md', tmp_path / 'game'
    input_file.write_text(json.dumps(dict(input=source)))
    brief.write_text('Approved fictional source. One continuous lifetime walk, age-appropriate stock avatars, scene illustrations only.\n')
    command = [sys.executable, '-B', str(PACKAGE / 'stages.py'), 'analyze', '--output', str(output)]
    first = subprocess.run(command + ['--source', str(input_file), '--brief', str(brief)], capture_output=True, text=True, timeout=15)
    assert first.returncode == 0, first.stderr
    saved = json.loads((output / 'stages/analyze/preview-request.json').read_text())
    payload = json.loads(saved['input'])
    assert payload['source_data_contract']['count'] == 2
    assert payload['source']['chapters'] == source['chapters']
    assert not (output / 'analysis/SOURCE_BIBLE.md').exists()
    assert not (output / 'analysis-reused.json').exists()
    second = subprocess.run(command, capture_output=True, text=True, timeout=15)
    assert second.returncode == 0, second.stderr
    assert json.loads((output / 'stages/analyze/preview-request.json').read_text()) == saved
    module = runner()
    assert module.public_source(source)['title'] == source['title']
    assert module.public_source(source)['fictional'] is True
