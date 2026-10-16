"""Authoritative five-round deltas for the existing canonical composer."""
from copy import deepcopy
from hashlib import sha256
import json

from .memory_events import EvidenceRef


def batch_job(page):
    batch = page['batch']
    sources, events = deepcopy(batch['sources']), deepcopy(batch['events'])
    previous = deepcopy(batch['previous'])
    if previous and 'manuscript' not in previous and previous.get('kind') == 'sample_chapter':
        chapters = {s['chapter_id'] for s in previous['sections']}
        if len(chapters) > 1:
            # Separate bounded jobs may have stored differently named samples.
            # Their paragraphs are derived prior writing, not eight chapters
            # that a one-chapter request must implicitly carry forward.
            passages = []
            for section in previous['sections']:
                if 'block' not in section:
                    continue
                identity = sha256(json.dumps([section['chapter_id'],section['block'],section['event_ids']],
                    sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:24]
                section.update(id='progressive-memoir__'+identity,chapter_id='progressive-memoir')
                section['block']['id'] = identity
                if not any(s['id']==section['id'] for s in passages):
                    passages.append(section)
            previous['sections'] = passages
    return {**page, 'authoritative_page': deepcopy(page), 'governed_page': True,
        'sources': sources, 'events': events, 'previous': previous,
        'source_manifest': [{'id': s['id'], 'version': s['version']} for s in sources],
        'event_manifest': [{'id': e['id'], 'revision': e['revision']} for e in events],
        'source_windows': {s['id']: {k: s[k] for k in ('char_start', 'char_end', 'original_length')} for s in sources}}


def summary_partition(page):
    batch = page['batch']
    return {'id': str(page['snapshot_id']) + '-messages-' + str(batch['starting_after']),
        'kind': 'period', 'title': 'New narrator messages', 'source_refs': [
            {'source_id': s['id'], 'version': s['version'], 'quote': s['text'],
             'char_start': s['char_start'], 'char_end': s['char_end']} for s in batch['new_messages']]}


def summary_packet(page, key):
    return {'preparation_id': key, 'partition': summary_partition(page),
            'sources': deepcopy(page['batch']['new_messages'])}


def validate_summary(value, page):
    expected = summary_partition(page)
    if (set(value) != {'event_id', 'context', 'source_refs'} or value['event_id'] != expected['id']
        or not isinstance(value['context'], str) or not 0 < len(value['context']) <= 4000
        or [EvidenceRef.model_validate(r).model_dump(exclude_none=True) for r in value['source_refs']]
           != expected['source_refs']):
        raise ValueError('Batch summary differs from original message evidence')


def validate_batch(batch, project_id):
    # Message summaries and prose advance on independent source cursors.
    if (not isinstance(batch, dict) or batch.get('schema_version') != 1
        or set(batch) != {'schema_version', 'starting_after', 'through_source', 'next_offset',
            'cursor', 'sources', 'events', 'new_messages', 'previous', 'previous_summary'}
        or any(type(batch[field]) is not int or batch[field] < 0 for field in ('starting_after', 'through_source'))
        or len(batch['new_messages']) > 5 or len(batch['sources']) > 16 or len(batch['events']) > 8):
        raise ValueError('Invalid progressive composer batch')
    for field in ('sources', 'new_messages'):
        seen = set()
        for s in batch[field]:
            if (s['id'] in seen or s['project_id'] != project_id or s['status'] != 'active'
                or not isinstance(s['text'], str) or not 0 < len(s['text']) <= 2304
                or s['char_end'] != s['char_start'] + len(s['text'])
                or not 0 <= s['char_start'] < s['char_end'] <= s['original_length']):
                raise ValueError('Invalid progressive original source window')
            seen.add(s['id'])
    if batch['previous'] is not None and not isinstance(batch['previous'], dict):
        raise ValueError('Invalid prior progressive memoir')
