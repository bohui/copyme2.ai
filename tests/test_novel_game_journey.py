"""Generation uses a validated, host-owned continuous walk rather than a free-form hub."""
import copy
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


def shared_scene():
    source = packet()
    source['chapters'] = source['chapters'][:2]
    source['timeline'] = source['timeline'][:2]
    value = dict(version=1, blend=180,
        segments=[dict(id='home', scene='home', title='A remembered place', start=0, end=1000)],
        stops=[dict(chapter='C1', segment='home', x=160), dict(chapter='C2', segment='home', x=640)])
    return value, source


def separate_memories(value):
    value = copy.deepcopy(value)
    value['segments'].append(dict(id='later', scene='home', title='The same place later', start=1000, end=2000))
    value['stops'][1].update(segment='later', x=1160)
    return value


@pytest.mark.parametrize('ages,stage,avatar', [
    ((8, 8), 'childhood', 'child-casual'),
    ((8, 9), 'childhood', 'child-casual'),
    ((0, 12), 'childhood', 'child-casual'),
    ((13, 17), 'adolescence', 'teen-casual'),
    ((18, 34), 'young-adulthood', 'young-adult-casual'),
    ((35, 64), 'adulthood', 'adult-casual'),
    ((65, 80), 'older-adulthood', 'senior-casual'),
])
def test_shared_scenery_groups_by_life_stage_and_keeps_each_memory_age(ages, stage, avatar):
    module, (value, source) = journey(), shared_scene()
    for event, age in zip(source['timeline'], ages):
        event['age'] = dict(minimum=age, maximum=age)
    original = copy.deepcopy((value, source))
    assert module.validate_journey(value, source['chapters'], source['timeline']) == value
    bound = module.bind_journey(value, source)
    assert len(bound['segments']) == 1
    assert bound['segments'][0]['avatar'] == avatar
    assert bound['segments'][0]['age_label'] == ('Age ' + str(ages[0]) if ages[0] == ages[1] else stage.replace('-', ' ').capitalize())
    assert [s['age_label'] for s in bound['stops']] == ['Age ' + str(age) for age in ages]
    assert (value, source) == original


@pytest.mark.parametrize('ages', [(12, 13), (17, 18), (34, 35), (64, 65)])
def test_real_life_stage_boundaries_still_require_separate_scenery(ages):
    module, (value, source) = journey(), shared_scene()
    for event, age in zip(source['timeline'], ages):
        event['age'] = dict(minimum=age, maximum=age)
    with pytest.raises(ValueError, match='Split scenery'):
        module.bind_journey(value, source)
    bound = module.bind_journey(separate_memories(value), source)
    assert bound['segments'][0]['avatar'] != bound['segments'][1]['avatar']


@pytest.mark.parametrize('outfit', ['professional', 'workwear'])
def test_same_approved_profession_and_outfit_can_span_exact_ages(outfit):
    module, (value, source) = journey(), shared_scene()
    for event, age in zip(source['timeline'], (40, 41)):
        event['age'] = dict(minimum=age, maximum=age)
    profile = {chapter: dict(outfit=outfit, profession='Teacher') for chapter in ('C1', 'C2')}
    bound = module.bind_journey(value, source, profile)
    assert bound['segments'][0]['avatar'] == 'adult-' + outfit
    assert bound['segments'][0]['profession'] == 'Teacher'
    assert [s['age_label'] for s in bound['stops']] == ['Age 40', 'Age 41']


@pytest.mark.parametrize('age,first,second', [
    (40, dict(profession='Teacher'), dict(profession='Carpenter')),
    (40, dict(outfit='professional', profession='Teacher'), dict(outfit='workwear', profession='Teacher')),
    (26, dict(outfit='professional', profession='Teacher'), dict(outfit='workwear', profession='Teacher')),
])
def test_approved_profession_or_outfit_changes_still_require_separate_scenery(age, first, second):
    module, (value, source) = journey(), shared_scene()
    for event in source['timeline']:
        event['age'] = dict(minimum=age, maximum=age)
    profile = dict(C1=first, C2=second)
    with pytest.raises(ValueError, match='Split scenery'):
        module.bind_journey(value, source, profile)
    bound = module.bind_journey(separate_memories(value), source, profile)
    assert [s['profession'] for s in bound['segments']] == [first['profession'], second['profession']]
    if age == 26:  # Both approved outfits fall back to the age-appropriate casual avatar.
        assert {s['avatar'] for s in bound['segments']} == {'young-adult-casual'}


@pytest.mark.parametrize('first,second,labels', [
    ({}, {}, ['Childhood', 'Childhood']),
    (dict(age={}), dict(age=dict(minimum=8, maximum=8)), ['Childhood', 'Age 8']),
    (dict(age=dict(minimum=None, maximum=None)), {}, ['Childhood', 'Childhood']),
    (dict(age=dict(minimum=8, maximum=9)), dict(age=dict(minimum=9, maximum=9)), ['Childhood', 'Age 9']),
])
def test_missing_or_uncertain_ages_use_the_approved_stage_without_inventing_an_age(first, second, labels):
    module, (value, source) = journey(), shared_scene()
    for event, metadata in zip(source['timeline'], (first, second)):
        event.pop('age', None)
        event.update(life_stage='childhood', **metadata)
    bound = module.bind_journey(value, source)
    assert bound['segments'][0]['age_label'] == 'Childhood'
    assert [s['age_label'] for s in bound['stops']] == labels


def test_missing_age_is_explicitly_unspecified_without_inventing_an_age():
    module, (value, source) = journey(), shared_scene()
    for event in source['timeline']:
        event.pop('age', None)
        event.pop('life_stage', None)
    bound=module.bind_journey(value,source)
    assert all(s['age_label']=='Life stage unspecified' for s in bound['stops'])
    assert bound['segments'][0]['avatar']=='adult-casual'


def test_materialised_shared_scenery_preserves_ages_source_and_the_original_plan(tmp_path):
    module, (value, source) = journey(), shared_scene()
    for event, age in zip(source['timeline'], (8, 9)):
        event['age'] = dict(minimum=age, maximum=age)
    source['chapters'][1]['blocks'][0]['text'] += '\n</script><script>untrusted source text</script>'
    original = copy.deepcopy(source)
    public = runner().public_source(source)
    module.write_json(tmp_path, 'design/JOURNEY_PLAN.json', value)
    module.materialise(tmp_path, source, public)
    bound = json.loads((tmp_path / 'build/journey.json').read_text())
    assert len(bound['segments']) == 1
    assert [s['age_label'] for s in bound['stops']] == ['Age 8', 'Age 9']
    html = (tmp_path / 'build/app/index.html').read_text()
    for name, expected in [('memoir-source', public), ('memoir-journey', bound)]:
        embedded = html.split('<script id="' + name + '" type="application/json">', 1)[1].split('</script>', 1)[0]
        assert json.loads(embedded) == expected
    assert '</script><script>untrusted source text</script>' not in html
    assert json.loads((tmp_path / 'design/JOURNEY_PLAN.json').read_text()) == value
    assert source == original


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
    movements=[s for s in replay['steps'] if s['action']=='hold']
    assert {s['selector'] for s in movements} == {'#left','#right'}
    assert all(50 <= s['duration_ms'] <= 5000 and type(s['target_x']) is int for s in movements)
    readings=[s['value'] for s in replay['steps'] if s['selector']=='#passage']
    assert set(readings)=={c['text'] for c in public['chapters']}
    assert readings.count(public['chapters'][0]['text'])>=2
    assert readings.count(public['chapters'][-1]['text'])>=2
    outcome=next(i for i,s in enumerate(replay['steps']) if s.get('checkpoint')=='outcome')
    assert any(s['selector']=='#left' for s in replay['steps'][outcome+1:])
    assert any(s['selector']=='#passage' for s in replay['steps'][outcome+1:])


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
