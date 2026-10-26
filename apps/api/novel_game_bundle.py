"""Validated journey data and public, host-owned runtime/art for the isolated player."""
from functools import lru_cache
import hashlib
from importlib import import_module
import json
import re

journey = import_module('experiments.novel-to-game.journey')
assets = import_module('experiments.novel-to-game.game_assets')
PACKAGE = journey.PACKAGE
RUNTIME = journey.RUNTIME
PLACES = PACKAGE / 'assets/illustrated-places-v1'


def scene_library():
    value = json.loads((PLACES / 'manifest.json').read_text())
    if hashlib.sha256((PLACES / value['file']).read_bytes()).hexdigest() != value['sha256']:
        raise ValueError('game_scene_library_integrity')
    return value


def validate_style(css):
    if not isinstance(css, str) or len(css.encode()) > 24000:
        raise ValueError('game_style_limit')
    clean = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    if re.search(r'[<\\]',css) or re.search(r'url\s*\(|@import|expression\s*\(', clean, re.I):
        raise ValueError('game_style_invalid')
    # Runtime visibility and state cannot be overridden by model styling.
    if re.search(r'\b(?:display|visibility|pointer-events|content)\s*:', clean, re.I):
        raise ValueError('game_style_changes_behavior')
    return css


def validate_bundle(value, scenes):
    if (not isinstance(value, dict) or set(value) != {'version', 'source', 'plan', 'css', 'scene_bindings'}
            or type(value['version']) is not int or value['version'] != 1):
        raise ValueError('game_journey_bundle_invalid')
    source = value['source']
    if (not isinstance(source, dict) or set(source) != {'title', 'fictional', 'chapters'}
            or not isinstance(source['title'], str) or not 1 <= len(source['title']) <= 120
            or type(source['fictional']) is not bool):
        raise ValueError('game_journey_source_invalid')
    expected = [dict(id='C'+str(i+1), title=s['title'], text=s['quote']) for i,s in enumerate(scenes)]
    if source['chapters'] != expected:
        raise ValueError('game_journey_selection_changed')
    plan = value['plan']
    if not isinstance(plan, dict) or set(plan) != {'version', 'blend', 'segments', 'stops', 'order_note'}:
        raise ValueError('game_journey_plan_invalid')
    raw = {k: plan[k] for k in ('version', 'blend')}
    raw['segments'] = [{k:s[k] for k in ('id','scene','title','start','end')} for s in plan['segments']]
    raw['stops'] = [{k:s[k] for k in ('chapter','segment','x')} for s in plan['stops']]
    fake_chapters = [dict(chapter_id=c['id']) for c in expected]
    fake_timeline = [dict(formal_chapter_id=c['id']) for c in expected]
    journey.validate_journey(raw, fake_chapters, fake_timeline)
    variants = {v['id'] for v in assets.pack_catalog()['variants']}
    for segment in plan['segments']:
        if set(segment) != {'id','scene','title','start','end','avatar','age_label','profession'}:
            raise ValueError('game_journey_segment_invalid')
        if segment['avatar'] not in variants or any(not isinstance(segment[k],str) or len(segment[k])>120
                for k in ('age_label','profession')):
            raise ValueError('game_journey_avatar_invalid')
    for stop in plan['stops']:
        if set(stop) != {'chapter','segment','x','age_label'} or not isinstance(stop['age_label'],str):
            raise ValueError('game_journey_stop_invalid')
    if not isinstance(plan['order_note'],str) or len(plan['order_note'])>1000:
        raise ValueError('game_journey_order_invalid')
    bindings = value['scene_bindings']
    if (not isinstance(bindings,dict) or set(bindings) != {s['scene'] for s in plan['segments']}
            or any(cell not in scene_library()['cells'] for cell in bindings.values())):
        raise ValueError('game_scene_bindings_invalid')
    validate_style(value['css'])
    if len(json.dumps(value).encode()) > 250000:
        raise ValueError('game_journey_bundle_limit')
    return value


@lru_cache(maxsize=1)
def runtime_bundle():
    """No memoir data: stock art/runtime are safe to cache publicly."""
    pack = assets.pack_catalog()
    media = {}
    css = []
    for item in pack['files']:
        path = assets.stock_source(item)
        if path.suffix == '.css':
            css.append(path.read_text())
        else:
            media[item['file']] = '/api/v1/memoir/agent/story-game-assets/'+item['sha256']+'/'+item['file']
    # The import is resolved here, before the iframe receives a closed asset set.
    stock_css = re.sub(r'@import\s+[^;]+;', '', '\n'.join(css))
    if any(url.strip("\"' ") not in media for url in re.findall(r'url\(([^)]+)\)',stock_css)):
        raise ValueError('game_stock_css_unresolved')
    library = scene_library()
    media['places'] = '/api/v1/memoir/agent/story-game-assets/'+library['sha256']+'/places.png'
    template = (RUNTIME/'index.html').read_text()
    template = re.sub(r'<link[^>]+>|<script src="journey-runtime.js" defer></script>', '', template)
    template = template.replace('Read the full memoir','Read all selected memories').replace('The full memoir','Selected memories').replace(
        'All original passages, with their remembered uncertainty. Browsing here does not advance the walk.',
        'The passages selected for this game, with their remembered uncertainty. Browsing here does not advance the walk.')
    return dict(template=template, css=(RUNTIME/'journey-runtime.css').read_text()+'\n'+stock_css,
        javascript=(RUNTIME/'journey-runtime.js').read_text(), media=media, places=library)


def runtime_asset(digest,name):
    library=scene_library()
    if name=='places.png' and digest==library['sha256']:
        return PLACES/library['file']
    for item in assets.pack_catalog()['files']:
        if item['file']==name and item['sha256']==digest and not name.endswith('.css'):
            return assets.stock_source(item)
    raise ValueError('game_asset_unavailable')
