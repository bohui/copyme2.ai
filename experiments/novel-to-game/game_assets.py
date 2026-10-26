"""Stage the shared art pack and cache only planned scene illustrations; no API calls."""
import argparse
import hashlib
import json
from pathlib import Path
import re

from PIL import Image

PACKAGE = Path(__file__).resolve().parent
PACK = PACKAGE / 'assets/illustrated-lifetime-v1'
DEFAULT_CACHE = PACKAGE.parents[1] / 'var/novel-to-game-scene-cache'


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def write_bytes(root, name, data, *, immutable=False):
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('Asset path escapes its directory: ' + name)
    if immutable and path.exists() and path.read_bytes() != data:
        raise ValueError('Refusing to replace a different asset: ' + name)
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(path.suffix + '.next')
    if pending.is_symlink():
        raise ValueError('Asset temporary path is a symlink')
    pending.write_bytes(data)
    pending.replace(path)
    return path


def write_json(root, name, value):
    return write_bytes(root, name, (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def pack_catalog():
    pack = json.loads((PACK / 'manifest.json').read_text())
    for asset in pack['files']:
        path = stock_source(asset)
        if sha256(path) != asset['sha256']:
            raise ValueError('Shared art pack integrity failed: ' + asset['file'])
        asset['url'] = 'assets/stock/' + pack['id'] + '/' + asset['file']
    return pack


def stock_source(asset):
    path = PACK / asset.get('source', asset['file'])
    if not path.resolve().is_relative_to(PACK.parent):
        raise ValueError('Stock source escapes the versioned asset library')
    return path


def select_avatar(stage, outfit='casual'):
    if outfit not in ('casual', 'professional', 'workwear'):
        raise ValueError('Use an approved stock outfit')
    variants = pack_catalog()['variants']
    return next((v['id'] for v in variants if v['stage'] == stage and v['outfit'] == outfit),
        next((v['id'] for v in variants if v['stage'] == stage and v['outfit'] == 'casual'), None))


def validate_plan(plan):
    if not isinstance(plan, dict) or set(plan) != {'style', 'illustrations'} or plan['style'] != pack_catalog()['scene_style']['id']:
        raise ValueError('Scene plan must use the shared pack scene style')
    if not isinstance(plan['illustrations'], list) or not 1 <= len(plan['illustrations']) <= 24:
        raise ValueError('Scene plan requires 1 to 24 illustrations')
    ids = set()
    for art in plan['illustrations']:
        if not isinstance(art, dict) or set(art) != {'id', 'kind', 'prompt', 'columns', 'rows', 'scenes'}:
            raise ValueError('Use only scene illustration fields')
        if not isinstance(art['id'], str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', art['id']) or art['id'] in ids:
            raise ValueError('Scene illustration IDs must be unique slugs')
        ids.add(art['id'])
        if art['kind'] != 'scene-background':
            raise ValueError('Only scene-background illustrations may be generated')
        if not isinstance(art['prompt'], str) or not art['prompt'].strip() or len(art['prompt']) > 12000:
            raise ValueError('Scene illustration needs a bounded, nonempty prompt')
        if any(type(art[k]) is not int or not 1 <= art[k] <= 6 for k in ('columns', 'rows')):
            raise ValueError('Scene atlas requires 1 to 6 columns and rows')
        scenes = art['scenes']
        if not isinstance(scenes, list) or len(scenes) != art['columns'] * art['rows'] or any(
                not isinstance(s, str) or not s.strip() or len(s) > 120 for s in scenes) or len(set(scenes)) != len(scenes):
            raise ValueError('Name each scene cell once, in row-major order')
    return plan


def scene_key(plan, art):
    # Logical IDs, game source text and music changes do not change an illustration.
    spec = {k: v for k, v in art.items() if k != 'id'}
    spec['prompt'] = spec['prompt'].replace('\r\n', '\n').strip()
    return hashlib.sha256(canonical(dict(style=pack_catalog()['scene_style'], **spec)).encode()).hexdigest()


def png_info(path, art):
    if path.stat().st_size > 20_000_000:
        raise ValueError('Scene PNG exceeds 20 MB')
    with Image.open(path) as image:
        if image.format != 'PNG':
            raise ValueError('Scene artwork must be PNG')
        width, height = image.size
        image.verify()
    if width % art['columns'] or height % art['rows']:
        raise ValueError('Scene PNG does not divide into the planned atlas grid')
    return dict(width=width, height=height, cell_width=width // art['columns'], cell_height=height // art['rows'])


def cached_scene(plan, art, cache=DEFAULT_CACHE):
    key=scene_key(plan,art)
    cached,receipt=cache/(key+'.png'),cache/(key+'.json')
    if not cached.exists() or not receipt.exists():return None
    record=json.loads(receipt.read_text())
    if record['cache_key']!=key or record['sha256']!=sha256(cached):
        raise ValueError('Scene cache integrity failed: '+art['id'])
    return dict(cache_key=key,sha256=record['sha256'],**png_info(cached,art))


def cache_scene(plan, art, image, cache=DEFAULT_CACHE):
    info=png_info(image,art);key=scene_key(plan,art)
    write_bytes(cache,key+'.png',image.read_bytes(),immutable=True)
    write_json(cache,key+'.json',dict(cache_key=key,sha256=sha256(image),**info))
    return cached_scene(plan,art,cache)


def prepare(workspace, cache=DEFAULT_CACHE, *, include_scenes=True, require_ready=False):
    pack = pack_catalog()
    for asset in pack['files']:
        write_bytes(workspace, 'build/app/' + asset['url'], stock_source(asset).read_bytes(), immutable=True)
    catalog = dict(policy='reuse-stock-generate-scene-backgrounds-only', stock=pack, scenes=[], missing=[])
    plan_path = workspace / 'design/SCENE_ART_PLAN.json'
    if include_scenes and plan_path.exists():
        plan = validate_plan(json.loads(plan_path.read_text()))
        for art in plan['illustrations']:
            key = scene_key(plan, art)
            item = dict(art, cache_key=key, url='assets/scenes/' + art['id'] + '-' + key[:12] + '.png')
            cached = cached_scene(plan,art,cache)
            if cached:
                item.update(cached,status='ready')
                write_bytes(workspace, 'build/app/' + item['url'], (cache/(key+'.png')).read_bytes(), immutable=True)
            else:
                item['status'] = 'missing'
                catalog['missing'].append(art['id'])
            catalog['scenes'].append(item)
    elif include_scenes:
        catalog['missing'].append('design/SCENE_ART_PLAN.json')
    write_json(workspace, 'build/asset-catalog.json', catalog)
    if require_ready and catalog['missing']:
        raise ValueError('Generate or restore the planned scene illustrations first: ' + ', '.join(catalog['missing']))
    return catalog


def record_scene(workspace, art_id, image, cache=DEFAULT_CACHE):
    plan = validate_plan(json.loads((workspace / 'design/SCENE_ART_PLAN.json').read_text()))
    art = next((a for a in plan['illustrations'] if a['id'] == art_id), None)
    if art is None:
        raise ValueError('Unknown scene illustration: ' + art_id)
    cache_scene(plan,art,image,cache)
    return prepare(workspace, cache)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'record'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cache', type=Path, default=DEFAULT_CACHE)
    parser.add_argument('--id', help='Scene illustration ID, for record')
    parser.add_argument('--image', type=Path, help='Original image-generation PNG, for record')
    args = parser.parse_args()
    if args.action == 'record' and (not args.id or not args.image):
        parser.error('record requires --id and --image')
    result = record_scene(args.output, args.id, args.image, args.cache) if args.action == 'record' else prepare(args.output, args.cache)
    print(json.dumps(dict(policy=result['policy'], missing=result['missing'], scenes=result['scenes']), ensure_ascii=False))
