"""Read-only cutover of an owner's validated execution cache into PostgreSQL.

The cache is never testimony. Its source text must still match an authorised
original before any derived manuscript can be imported.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3

from .canonical_composer import fingerprint, section_event_ids
from .memoir_preview import skill_operation


def prune_saved_cache(owner, project):
    """Remove restricted derived bytes before acknowledging a revocation receipt."""
    path = os.getenv('MEMORY_SPARK_TASK_DB')
    if not path or not Path(path).is_file():
        return
    with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=rw', uri=True) as db:
        db.execute('PRAGMA secure_delete=ON')
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'private_draft_projects' in tables:
            db.execute("UPDATE private_draft_projects SET stale=1,draft=NULL,proposal=NULL,payload='{}',source_epoch=source_epoch+1 WHERE user_id=? AND project_id=?",
                       (owner, project))
        if 'private_draft_jobs' in tables:
            db.execute("UPDATE private_draft_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL,lease_until=NULL WHERE user_id=? AND project_id=?",
                       (owner, project))
        if 'preview_jobs' in tables:
            db.execute("UPDATE preview_jobs SET status='STALE',payload='{}',checkpoint='{}',lease_token=NULL,lease_until=NULL WHERE user_id=? AND project_id=?",
                       (owner, project))


def saved_cache_record(storage, project, locale):
    path = os.getenv('MEMORY_SPARK_TASK_DB')
    if path and Path(path).is_file():
        with sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='private_draft_projects'").fetchone():
                row = db.execute('SELECT * FROM private_draft_projects WHERE user_id=? AND project_id=? AND locale=? AND stale=0 AND draft IS NOT NULL',
                                 (storage.user_id, project, locale)).fetchone()
                if row:
                    return dict(row)
    # The existing twenty-round sample was stored in authorised user_memory,
    # whereas private checkpoints used the execution cache. Preserve either.
    candidates=[]
    for memory in storage.composition_memories():
        if memory.get('kind')!='memoir' or f'memoir-preview:{project}' not in memory.get('source_paths',[]):
            continue
        try:
            bundle=json.loads(memory['content'])
            request=bundle['request']
            if request['project_id']!=project or request['target']['locale']!=locale:
                continue
            trigger=request['trigger']
            candidates.append((memory.get('created_at') or '',{'draft':memory['content'],
                'revision':request['snapshot']['expected_manuscript_revision']+1,
                'completed_milestone':max(trigger.get('free_rounds_completed',0),trigger.get('private_rounds_completed',0)),
                'human_locked':any(c.get('approved') or c.get('human_locked') for c in request['prior_state']['chapters'])}))
        except (KeyError,TypeError,ValueError):
            continue
    return max(candidates,key=lambda item:item[0])[1] if candidates else None


def import_saved_cache(storage, project, locale):
    row=saved_cache_record(storage,project,locale)
    if not row or len(row['draft']) > 500000 or row['revision'] < 1:
        return False
    bundle = json.loads(row['draft'])
    if bundle.get('status') != 'ready' or bundle.get('validation', {}).get('ok') is not True:
        return False
    review = bundle.get('review', {})
    if review.get('ready_for_user_review') is not True or review.get('publication_approved') is not False:
        return False
    if any(f.get('severity') == 'blocking' for f in review.get('findings', [])):
        return False
    request = bundle['request']
    if request['project_id'] != project or request['target']['locale'] != locale:
        return False
    result = storage.request('POST', '/rest/v1/rpc/migrate_user_memoir_index', json={
        'p_project_id': project, 'p_events': request['events'],
    }).json()
    sources = {s['id']: s for s in result['sources']}
    source_map = result['source_id_map']
    event_map = result['event_id_map']
    for original in request['sources']:
        current = sources.get(source_map.get(original['id'], original['id']))
        if not current or current['status'] != 'active' or current['text'] != original['text']:
            return False
    def remap(value):
        if isinstance(value, list):
            return [remap(v) for v in value]
        if not isinstance(value, dict):
            return value
        result = {key: remap(v) for key, v in value.items()}
        if 'source_id' in result:
            result['source_id'] = source_map.get(result['source_id'], result['source_id'])
            if result['source_id'] in sources:
                result['version'] = str(sources[result['source_id']]['version'])
        if 'id' in result and 'text' in result and 'author_role' in result:
            result['id'] = source_map.get(result['id'], result['id'])
            result['version'] = str(sources[result['id']]['version'])
        if 'id' in result and ('period_id' in result or 'summary' in result):
            result['id'] = event_map.get(result['id'], result['id'])
        if 'event_id' in result:
            result['event_id'] = event_map.get(result['event_id'], result['event_id'])
        if 'event_ids' in result:
            result['event_ids'] = [event_map.get(v, v) for v in result['event_ids']]
        if 'source_memory_ids' in result:
            result['source_memory_ids'] = [source_map.get(v, v) for v in result['source_memory_ids']]
        return result
    bundle = remap(copy.deepcopy(bundle))
    request, draft = bundle['request'], bundle['draft']
    request.setdefault('context', {})['canonical_event_index'] = True
    async def validate():
        plan = await skill_operation('plan', request)
        draft['input_fingerprint'] = plan['input_fingerprint']
        validation = await skill_operation('validate', request, draft)
        if not validation.get('ok'):
            return False
        artifacts = await skill_operation('render', request, draft)
        bundle.update(validation=validation, manuscript=json.loads(artifacts['manuscript.json']), markdown=artifacts['memoir.md'])
        return True
    if not asyncio.run(validate()):
        return False
    events = {e['id']: e for e in result['events']}
    bundle['event_manifest'] = [{'id': id, 'revision': events[id]['revision']} for id in event_map.values()]
    bundle['source_manifest'] = [{'id': s['id'], 'version': int(s['version'])} for s in request['sources']]
    config = fingerprint({'locale': locale, 'skill': 'shared-composer-1',
        'model': os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', os.getenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')),
        'policy': request['policy']})
    bundle['content_config'] = config
    sections = []
    bodies = [(chapter['id'], chapter) for chapter in bundle['manuscript']['chapters']]
    if bundle['manuscript']['kind'] == 'sample_storyline':
        bodies.append(('sample_storyline', bundle['manuscript']['storyline']))
    for chapter_id, chapter in bodies:
        for block in chapter['blocks']:
            ids = section_event_ids(block, chapter, request)
            sections.append({'id': chapter_id + '__' + block['id'], 'chapter_id': chapter_id, 'event_ids': ids,
                'source_refs': block['source_refs'], 'content': block['text'], 'block': block,
                'fingerprint': fingerprint({'events': {id: events[id]['revision'] for id in ids},
                    'sources': block['source_refs'], 'configuration': config})})
        heading = {'title': chapter['title']}
        if chapter_id != 'sample_storyline':
            heading['subtitle'] = chapter['subtitle']
        sections.append({'id': chapter_id + '__heading', 'chapter_id': chapter_id, 'event_ids': chapter['event_ids'],
            'source_refs': chapter['source_refs'], 'content': chapter['title'],
            'heading': heading,
            'fingerprint': fingerprint({'events': {id: events[id]['revision'] for id in chapter['event_ids']},
                'sources': chapter['source_refs'], 'configuration': config})})
    bundle['sections'] = sections
    return storage.request('POST', '/rest/v1/rpc/import_user_legacy_memoir', json={
        'p_project_id': project, 'p_locale': locale, 'p_revision': row['revision'],
        'p_covered_round': row['completed_milestone'], 'p_human_locked': bool(row['human_locked']), 'p_bundle': bundle,
    }).json()['imported']
