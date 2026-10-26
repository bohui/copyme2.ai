"""Reuse stock bytes and exact scene art; do not silently generate other asset types."""
import copy
import importlib.util
import json
from pathlib import Path

from PIL import Image
import pytest

from test_novel_to_game_experiment import runner

PACKAGE = Path(__file__).resolve().parents[1] / 'experiments/novel-to-game'
spec = importlib.util.spec_from_file_location('novel_game_assets_test', PACKAGE / 'game_assets.py')
assets = importlib.util.module_from_spec(spec)
spec.loader.exec_module(assets)


def scene_plan():
    return dict(style='gouache-childhood-v1', illustrations=[dict(id='places', kind='scene-background',
        columns=2, rows=1, scenes=['home', 'school'], prompt='Two fictional, unpeopled illustrated settings.')])


def put_plan(workspace, plan):
    path = workspace / 'design/SCENE_ART_PLAN.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan))


def test_stock_pack_is_byte_identical_and_scene_cache_survives_new_game_ids(tmp_path):
    first, second, cache = (tmp_path / p for p in ('first', 'second', 'cache'))
    plan = scene_plan()
    put_plan(first, plan)
    cold = assets.prepare(first, cache)
    assert cold['missing'] == ['places']
    assert not list(cache.glob('*.png'))
    assert {a['role'] for a in cold['stock']['files']} == {
        'character-animation', 'music-loop', 'interaction-sound', 'animation-and-ui'}
    for asset in cold['stock']['files']:
        assert (first / 'build/app' / asset['url']).read_bytes() == assets.stock_source(asset).read_bytes()
    # A synthetic PNG tests storage and grid handling, not illustration quality.
    image = tmp_path / 'test.png'
    Image.new('RGB', (12, 8), 'green').save(image)
    ready = assets.record_scene(first, 'places', image, cache)
    assert ready['missing'] == []
    assert ready['scenes'][0]['cell_width'] == 6
    assert ready['scenes'][0]['cell_height'] == 8
    plan['illustrations'][0]['id'] = 'another-game-places'
    put_plan(second, plan)
    reused = assets.prepare(second, cache, require_ready=True)
    assert reused['missing'] == []
    assert reused['scenes'][0]['cache_key'] == ready['scenes'][0]['cache_key']
    assert (second / 'build/app' / reused['scenes'][0]['url']).read_bytes() == image.read_bytes()
    changed = copy.deepcopy(plan)
    changed['illustrations'][0]['prompt'] += ' Rain is visible outside.'
    put_plan(second, changed)
    assert assets.prepare(second, cache)['missing'] == ['another-game-places']
    with pytest.raises(ValueError, match='first'):
        assets.prepare(second, cache, require_ready=True)
    assert len(list(cache.glob('*.png'))) == 1


@pytest.mark.parametrize('field,value,reason', [
    ('kind', 'character-animation', 'Only scene-background'),
    ('id', '../../escape', 'unique slugs'),
    ('rows', True, 'columns and rows'),
    ('scenes', ['home'], 'each scene cell'),
])
def test_scene_plan_rejects_non_scene_art_and_unsafe_or_ambiguous_layout(field, value, reason):
    plan = scene_plan()
    plan['illustrations'][0][field] = value
    with pytest.raises(ValueError, match=reason):
        assets.validate_plan(plan)


def test_cache_rejects_corruption_and_never_overwrites_different_predefined_art(tmp_path):
    workspace, cache = tmp_path / 'game', tmp_path / 'cache'
    put_plan(workspace, scene_plan())
    image = tmp_path / 'test.png'
    Image.new('RGB', (12, 8), 'green').save(image)
    ready = assets.record_scene(workspace, 'places', image, cache)
    key = ready['scenes'][0]['cache_key']
    (cache / (key + '.png')).write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='cache integrity'):
        assets.prepare(workspace, cache)
    stock = ready['stock']['files'][0]
    (workspace / 'build/app' / stock['url']).write_bytes(b'local different art')
    with pytest.raises(ValueError, match='Refusing to replace'):
        assets.prepare(workspace, cache)
    assert (workspace / 'build/app' / stock['url']).read_bytes() == b'local different art'


def test_staging_refuses_a_link_outside_the_game_workspace(tmp_path):
    workspace, outside = tmp_path / 'game', tmp_path / 'outside'
    (workspace / 'build').mkdir(parents=True)
    outside.mkdir()
    (workspace / 'build/app').symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match='escapes its directory'):
        assets.prepare(workspace, tmp_path / 'cache')
    assert list(outside.iterdir()) == []


def test_scene_grid_and_style_changes_invalidate_art_but_id_and_whitespace_do_not(tmp_path, monkeypatch):
    plan = scene_plan()
    art = plan['illustrations'][0]
    key = assets.scene_key(plan, art)
    renamed = dict(art, id='other', prompt='\n' + art['prompt'] + '\n')
    assert assets.scene_key(plan, renamed) == key
    assert assets.scene_key(plan, dict(art, columns=1, rows=2)) != key
    pack = assets.pack_catalog()
    pack['scene_style']['description'] += ' Different palette.'
    monkeypatch.setattr(assets, 'pack_catalog', lambda: pack)
    assert assets.scene_key(plan, art) != key


def test_art_preview_supplies_stock_not_image_binaries_and_live_build_waits_for_scenes(tmp_path, monkeypatch):
    module = runner()
    module.HERE = tmp_path / 'game'
    module.ROOT = tmp_path / 'repo'
    # Keep the complete source fixture while putting the shared cache under the test root.
    fixture = module.ROOT / 'skills/memoir-story-game/tests/fixtures/age-eight.json'
    fixture.parent.mkdir(parents=True)
    fixture.write_bytes((PACKAGE.parents[1] / 'skills/memoir-story-game/tests/fixtures/age-eight.json').read_bytes())
    module.initialise()
    (module.HERE / 'design').mkdir(exist_ok=True)
    (module.HERE / 'design/JOURNEY_PLAN.json').write_bytes((PACKAGE / 'examples/age-eight-linear/JOURNEY_PLAN.json').read_bytes())
    for stage in ('art', 'production'):
        for name in module.STAGES[stage]['inputs']:
            path = module.HERE / name
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('Existing approved handoff')
    request = module.run_stage('art', dry_run=True)
    payload = json.loads(request['input'])
    catalog = json.loads(payload['saved_artifacts']['build/asset-catalog.json'])
    assert catalog['policy'] == 'reuse-stock-generate-scene-backgrounds-only'
    assert catalog['stock']['avatar']['row_states'] == ['idle', 'walk']
    assert catalog['stock']['audio']['default'] == 'off'
    assert 'design/SCENE_ART_PLAN.json' in payload['allowed_output_paths']
    assert 'data:image' not in request['input']
    assert request['model'] == 'gpt-6.1-sol' and request['reasoning']['effort'] == 'max'

    def forbidden(*args, **kwargs):
        raise AssertionError('No paid provider call before planned scene assets exist')

    monkeypatch.setattr(module.httpx, 'Client', forbidden)
    with pytest.raises(ValueError, match='scene illustrations first'):
        module.run_stage('production')
    plan = scene_plan()
    put_plan(module.HERE, plan)
    image = tmp_path / 'test.png'
    Image.new('RGB', (12, 8), 'green').save(image)
    assets.record_scene(module.HERE, 'places', image, module.ROOT / 'var/novel-to-game-scene-cache')
    production = module.run_stage('production', dry_run=True)
    build_catalog = json.loads(json.loads(production['input'])['saved_artifacts']['build/asset-catalog.json'])
    assert build_catalog['missing'] == []
    assert build_catalog['scenes'][0]['sha256'] == assets.sha256(image)
    assert len(list((module.HERE / 'build/app/assets/stock').rglob('*.png'))) == 2
    assert not list(module.HERE.glob('stages/*/attempt-*-request.json'))
