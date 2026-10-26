"""Grounded scene options and a lossless handoff of the owner's selection."""
from collections import defaultdict

from pydantic import BaseModel, Field


class SceneProposal(BaseModel):
    model_config = {'extra': 'forbid'}
    chapter_id: str = Field(min_length=1, max_length=200)
    block_index: int = Field(ge=0, le=7, strict=True)
    title: str = Field(min_length=1, max_length=100)
    person: str | None = Field(min_length=2, max_length=80)
    quote: str = Field(min_length=1, max_length=400)
    event_ids: list[str] = Field(min_length=1, max_length=128)


class GameProposal(BaseModel):
    model_config = {'extra': 'forbid'}
    scenes: list[SceneProposal] = Field(min_length=1, max_length=128)


class SceneOption(SceneProposal):
    recommended: bool = Field(strict=True)
    reason: str = Field(min_length=1, max_length=240)


class ScenePool(BaseModel):
    model_config = {'extra': 'forbid'}
    scenes: list[SceneOption] = Field(min_length=1, max_length=128)


class GameBrief(BaseModel):
    model_config = {'extra': 'forbid'}
    design_brief: str = Field(min_length=1, max_length=6000)
    scene_indices: list[int] = Field(min_length=1, max_length=128)


def validate_scenes(packet, proposal, *, require_coverage=True):
    proposal = GameProposal.model_validate(proposal).model_dump(mode='json')
    chapters = {c['chapter_id']: c for c in packet['chapters']}
    event_ids = {e['id'] for e in packet['timeline']}
    covered = set()
    for scene in proposal['scenes']:
        chapter = chapters.get(scene['chapter_id'])
        index = scene['block_index']
        if not chapter or index >= len(chapter['blocks']):
            raise ValueError('game_chapter_required')
        quote = scene['quote']
        if (chapter['blocks'][index]['text'].count(quote) != 1
                or scene['person'] and scene['person'] not in quote
                or not set(scene['event_ids']) <= set(chapter['event_ids']) & event_ids
                or len(set(scene['event_ids'])) != len(scene['event_ids'])):
            raise ValueError('game_scene_grounding_invalid')
        if scene['title'] not in quote:
            scene['title'] = quote[:100].rsplit(' ', 1)[0] if len(quote) > 100 and ' ' in quote[:100] else quote[:100]
        covered.update(scene['event_ids'])
    if require_coverage and covered != event_ids:
        raise ValueError('game_timeline_coverage_required')
    return proposal


def validate_pool(packet, value):
    pool = ScenePool.model_validate(value).model_dump(mode='json')
    bare = {'scenes': [{k: v for k, v in s.items() if k not in {'recommended', 'reason'}} for s in pool['scenes']]}
    grounded = validate_scenes(packet, bare)
    stages = {event['id']: event.get('life_stage') or 'unplaced' for event in packet['timeline']}
    seen, recommendations = set(), defaultdict(bool)
    for option, scene in zip(pool['scenes'], grounded['scenes']):
        identity = (scene['chapter_id'], scene['block_index'], scene['quote'])
        scene_stages = {stages[event_id] for event_id in scene['event_ids']}
        if identity in seen or len(scene_stages) != 1:
            raise ValueError('game_pool_duplicate_or_mixed_stage')
        seen.add(identity)
        stage = next(iter(scene_stages))
        recommendations[stage] |= option['recommended']
        option.update(scene)
    if not all(recommendations.values()):
        raise ValueError('game_stage_recommendation_required')
    event_order={e['id']:i for i,e in enumerate(packet['timeline'])}
    chapters={c['chapter_id']:c for c in packet['chapters']}
    pool['scenes'].sort(key=lambda s:(min(event_order[e] for e in s['event_ids']),s['block_index'],
        chapters[s['chapter_id']]['blocks'][s['block_index']]['text'].index(s['quote'])))
    return pool


def selected_scenes(packet):
    pool, selection = packet.get('scene_pool'), packet.get('selection')
    if not pool or not selection:
        raise ValueError('game_human_selection_required')
    chosen = set(selection['scene_ids'])
    options = [s for s in pool['scenes'] if s['id'] in chosen]
    if not chosen or len(chosen) != len(selection['scene_ids']) or len(options) != len(chosen):
        raise ValueError('game_selection_invalid')
    proposal = {'scenes': [{k: s[k] for k in SceneProposal.model_fields} for s in options]}
    return validate_scenes(packet, proposal, require_coverage=False)


def public_scenes(proposal):
    return [dict(index=i, title=s['title'], person=s['person'], quote=s['quote'])
            for i, s in enumerate(proposal['scenes'])]


def validate_brief(brief, count):
    value = GameBrief.model_validate(brief).model_dump(mode='json')
    if value['scene_indices'] != list(range(count)):
        raise ValueError('game_brief_selection_changed')
    return value
