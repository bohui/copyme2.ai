"""Validate a single timeline walk and render it with the host-owned game runtime."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from game_assets import pack_catalog, select_avatar, write_bytes, write_json

PACKAGE = Path(__file__).resolve().parent
RUNTIME = PACKAGE / 'runtime'


def validate_journey(plan, chapters, timeline):
    if not isinstance(plan, dict) or set(plan) != {'version', 'blend', 'segments', 'stops'} or type(plan['version']) is not int or plan['version'] != 1:
        raise ValueError('Journey plan requires version, blend, segments and stops')
    if type(plan['blend']) is not int or not 80 <= plan['blend'] <= 240:
        raise ValueError('Use an illustrated overlap from 80 to 240 world units')
    public = {c['chapter_id']: 'C' + str(i + 1) for i, c in enumerate(chapters)}
    order = [public[e['formal_chapter_id']] for e in timeline if e.get('formal_chapter_id') in public]
    if len(order) != len(chapters) or len(set(order)) != len(order):
        raise ValueError('Supply one approved timeline position per chapter')
    segments, stops = plan['segments'], plan['stops']
    if not isinstance(segments, list) or not 1 <= len(segments) <= len(chapters):
        raise ValueError('Use one continuous sequence of source-supported segments')
    ids, edge = set(), 0
    for segment in segments:
        if not isinstance(segment, dict) or set(segment) != {'id', 'scene', 'title', 'start', 'end'}:
            raise ValueError('Segment fields must describe continuous scenery, not travel links')
        for key in ('id', 'scene'):
            if not isinstance(segment[key], str) or not re.fullmatch(r'[a-z][a-z0-9-]{0,47}', segment[key]):
                raise ValueError('Segment and scene IDs must be slugs')
        if segment['id'] in ids or not isinstance(segment['title'], str) or not 1 <= len(segment['title']) <= 80:
            raise ValueError('Use unique segment IDs and short place titles')
        ids.add(segment['id'])
        if any(type(segment[k]) is not int for k in ('start', 'end')) or segment['start'] != edge or not 640 <= segment['end'] - edge <= 4000:
            raise ValueError('Segments must join without gaps, branches or coordinate resets')
        edge = segment['end']
    if not isinstance(stops, list) or [s.get('chapter') if isinstance(s, dict) else None for s in stops] != order:
        raise ValueError('Every chapter must occur once in the approved timeline order')
    lookup, previous, used = {s['id']: s for s in segments}, -1000, set()
    for stop in stops:
        if set(stop) != {'chapter', 'segment', 'x'} or stop['segment'] not in lookup or type(stop['x']) is not int:
            raise ValueError('Each memory needs one segment and a world position')
        segment = lookup[stop['segment']]
        if not segment['start'] + 100 <= stop['x'] <= segment['end'] - 100 or stop['x'] - previous < 240:
            raise ValueError('Memory positions must increase with room to read each marker')
        previous = stop['x']
        used.add(stop['segment'])
    if used != ids:
        raise ValueError('Each illustrated segment must serve a source memory')
    if len(stops) == 1 and stops[0]['x'] < 640:
        raise ValueError('A one-memory walk needs enough forward travel to demonstrate its camera')
    return plan


def life_stage(event):
    age = event.get('age', {}).get('minimum')
    if isinstance(age, (int, float)) and not isinstance(age, bool) and 0 <= age <= 120:
        return 'childhood' if age < 13 else 'adolescence' if age < 18 else 'young-adulthood' if age < 35 else 'adulthood' if age < 65 else 'older-adulthood'
    stage = event.get('life_stage', '').replace('_', '-').lower()
    aliases = {'young-adult': 'young-adulthood', 'middle-aged': 'adulthood', 'senior': 'older-adulthood'}
    stage = aliases.get(stage, stage)
    if stage not in {'childhood', 'adolescence', 'young-adulthood', 'adulthood', 'older-adulthood'}:
        raise ValueError('Supply an approved life stage rather than inventing an age')
    return stage


def bind_journey(plan, packet, profile=None):
    validate_journey(plan, packet['chapters'], packet['timeline'])
    profile = {} if profile is None else profile
    ids = {c['chapter_id']: 'C' + str(i + 1) for i, c in enumerate(packet['chapters'])}
    events = {ids[e['formal_chapter_id']]: e for e in packet['timeline']}
    if not isinstance(profile, dict) or set(profile) - set(events):
        raise ValueError('Character profile must refer to approved source chapters')
    bound = json.loads(json.dumps(plan))
    for segment in bound['segments']:
        looks, labels = [], []
        for stop in (s for s in bound['stops'] if s['segment'] == segment['id']):
            event = events[stop['chapter']]
            approved = profile.get(stop['chapter'], {})
            if not isinstance(approved, dict) or set(approved) - {'outfit', 'profession'}:
                raise ValueError('Character profile accepts only approved outfit and profession')
            profession = approved.get('profession', '')
            if not isinstance(profession, str) or len(profession) > 80:
                raise ValueError('Use a short approved profession label')
            outfit = approved.get('outfit', 'casual')
            if outfit != 'casual' and not profession.strip():
                raise ValueError('Work clothing requires an approved profession, not a model guess')
            stage = life_stage(event)
            variant = select_avatar(stage, outfit)
            if variant is None:
                raise ValueError('No stock avatar for the approved life stage')
            age = event.get('age', {})
            label = 'Age ' + str(age['minimum']) if age.get('minimum') is not None and age.get('minimum') == age.get('maximum') else stage.replace('-', ' ').capitalize()
            stop['age_label'] = label
            labels.append(label)
            looks.append((stage, outfit, variant, profession))
        if len(set(looks)) != 1:
            raise ValueError('Split scenery at a life-stage, outfit or profession change')
        stage, _, variant, profession = looks[0]
        segment.update(avatar=variant, age_label=labels[0] if len(set(labels)) == 1 else stage.replace('-', ' ').capitalize(),
            profession=profession)
    bound['order_note'] = 'Follow the supplied timeline in one continuous walk. Some dates and ordering within a life stage are uncertain.'
    return bound


def runtime_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(RUNTIME.iterdir()) if p.is_file()}


def inert_json(value):
    return json.dumps(value, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')


def playthrough(plan, source):
    steps, x = [], 80
    chapters = {c['id']: c for c in source['chapters']}
    def travel(target):
        nonlocal x
        while x != target:
            direction = 1 if target > x else -1
            end = x + direction * min(1800, abs(target - x))
            steps.append(dict(action='hold', selector='#right' if direction > 0 else '#left', value='Enter',
                duration_ms=math.ceil(abs(end - x) / 560 * 1000) + 500, target_x=end))
            x = end

    def read_memory(chapter, count):
        steps.extend([dict(action='click', selector='#interact'),
            dict(action='assert_text', selector='#passage', value=chapters[chapter]['text']),
            dict(action='click', selector='#continue'),
            dict(action='assert_attr', selector='#game', attribute='data-visited', value=str(count))])

    for index, stop in enumerate(plan['stops']):
        travel(stop['x'])
        assertion = dict(action='assert_attr', selector='#game', attribute='data-near', value=stop['chapter'])
        if index == 0:
            assertion['checkpoint'] = 'input'
        elif index == 1:
            assertion['checkpoint'] = 'coreLoop'
        steps.append(assertion)
        if len(plan['stops']) == 1:
            steps.append(dict(action='assert_attr',selector='#game',attribute='data-segment',value=stop['segment'],checkpoint='coreLoop'))
        read_memory(stop['chapter'], index + 1)
        if index == 1:
            travel(plan['stops'][0]['x'])
            read_memory(plan['stops'][0]['chapter'], 2)
    steps.append(dict(action='assert_attr', selector='#game', attribute='data-phase', value='complete', checkpoint='outcome'))
    last=plan['stops'][-1]
    travel(last['x'])
    read_memory(last['chapter'], len(plan['stops']))
    travel(last['x'] - 100)
    steps.append(dict(action='assert_attr',selector='#player',attribute='data-facing',value='left'))
    travel(last['x'])
    read_memory(last['chapter'], len(plan['stops']))
    steps.extend([dict(action='click', selector='#restart'),
        dict(action='assert_attr', selector='#game', attribute='data-x', value='80', checkpoint='restart')])
    if len(steps) > max(100, 7 * len(plan['stops']) + 20):
        raise ValueError('Replay exceeds the route-sized input budget; reduce traversal distance')
    return dict(initial=dict(selector='#progress', text='Memories 0/' + str(len(plan['stops']))), steps=steps,
        terminal='Journey complete — ' + str(len(plan['stops'])) + '/' + str(len(plan['stops'])) + ' memories', restart='initial-state')


def materialise(workspace, packet, source, *, require_art=False):
    plan_path = workspace / 'design/JOURNEY_PLAN.json'
    if not plan_path.exists():
        return
    profile_path = workspace / 'source/character-profile.json'
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else None
    plan = bind_journey(json.loads(plan_path.read_text()), packet, profile)
    catalog_path = workspace / 'build/asset-catalog.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else dict(stock=pack_catalog(), scenes=[])
    scenes = [dict((k, s[k]) for k in ('url', 'columns', 'rows', 'scenes', 'width', 'height')) for s in catalog['scenes'] if s['status'] == 'ready']
    covered = {name for s in scenes for name in s['scenes']}
    if require_art and {s['scene'] for s in plan['segments']} - covered:
        raise ValueError('Every journey location needs its ready scene illustration')
    plan['illustrations'] = scenes
    plan['stock_url'] = 'assets/stock/' + catalog['stock']['id'] + '/'
    html = (RUNTIME / 'index.html').read_text()
    write_bytes(workspace, 'build/template.html', html.encode())
    for name, value in [('MEMOIR_SOURCE', source), ('MEMOIR_JOURNEY', plan)]:
        marker = '<!-- ' + name + ' -->'
        script_id = 'memoir-source' if name == 'MEMOIR_SOURCE' else 'memoir-journey'
        html = html.replace(marker, '<script id="' + script_id + '" type="application/json">' + inert_json(value) + '</script>')
    html = html.replace('<!-- STOCK_CSS -->', '<link rel="stylesheet" href="' + plan['stock_url'] + 'stock.css">' if scenes else '')
    write_bytes(workspace, 'build/app/index.html', html.encode())
    for name in ('journey-runtime.js', 'journey-runtime.css'):
        write_bytes(workspace, 'build/app/' + name, (RUNTIME / name).read_bytes())
    if not (workspace / 'build/app/game.css').exists():
        write_bytes(workspace, 'build/app/game.css', b'/* Model styling extends the host-owned journey runtime. */\n')
    write_json(workspace, 'build/journey.json', plan)
    write_json(workspace, 'build/playthrough.json', playthrough(plan, source))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True, help='Approved composer/timeline input JSON')
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--require-art', action='store_true')
    args = parser.parse_args()
    packet = json.loads(args.source.read_text())['input']
    plan = json.loads(args.plan.read_text())
    validate_journey(plan, packet['chapters'], packet['timeline'])
    write_json(args.output, 'design/JOURNEY_PLAN.json', plan)
    write_json(args.output, 'source/input.json', dict(input=packet))
    benchmark=packet==json.loads((PACKAGE.parents[1]/'skills/memoir-story-game/tests/fixtures/age-eight.json').read_text())['input']
    events={e['formal_chapter_id']:e for e in packet['timeline']}
    source=dict(title=packet.get('title','The Blue Gate · Age Eight' if benchmark else 'A life, one journey'),
        fictional=packet.get('fictional',benchmark),chapters=[dict(id='C'+str(i+1),title=events[c['chapter_id']]['title'],
        text='\n\n'.join(b['text'] for b in c['blocks'])) for i,c in enumerate(packet['chapters'])])
    materialise(args.output, packet, source, require_art=args.require_art)
    print(json.dumps(dict(status='READY', runtime='memoir-linear-v2', memories=len(plan['stops']))))
