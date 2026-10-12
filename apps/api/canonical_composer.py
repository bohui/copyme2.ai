"""Read-only projection of the shared event contract into composer 1.x.

The composer never extracts or mutates events here. Its period labels are
presentation groups, while all event IDs remain the server-owned canonical IDs.
"""
import copy
import asyncio
import hashlib
import json
import os
from types import SimpleNamespace

from .memoir_preview import compose_candidate, composer_call
from .memory_events import EvidenceRef
from .recall import free_recall_rounds, private_draft_cadence
from .stage_readiness import LIFE_STAGES


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def section_event_ids(block, chapter, request):
    def overlap(left, right):
        if left['source_id'] != right['source_id'] or str(left['version']) != str(right['version']):
            return False
        if all(key in left and key in right for key in ('char_start', 'char_end')):
            return left['char_start'] < right['char_end'] and right['char_start'] < left['char_end']
        return True
    ids = [event['id'] for event in request['events'] if event['id'] in chapter['event_ids']
           and any(overlap(ref, evidence) for ref in block['source_refs'] for evidence in event['source_refs'])]
    return ids or chapter['event_ids']


def canonical_evidence_errors(request, draft):
    """Validate actual prose evidence, regardless of how old text is reused."""
    events = {event['id']: event['source_refs'] for event in request['events']}
    sources = {(source['id'], str(source['version'])): source['text'] for source in request['sources']}
    windows = request.get('context', {}).get('source_windows', {})
    errors = []

    def supported(ref, event_ids):
        key = (ref['source_id'], str(ref['version']))
        text = sources.get(key)
        if text is None:
            return False
        # Omitting offsets cites the whole source, not any convenient matching
        # occurrence. It cannot widen a narrow authorised canonical reference.
        offset = windows.get(ref['source_id'], {}).get('char_start', 0)
        start, end = ref.get('char_start', offset), ref.get('char_end', offset + len(text))
        if start < offset or end > offset + len(text):
            return False
        ranges = sorted((evidence['char_start'], evidence['char_end'])
            for event_id in event_ids for evidence in events.get(event_id, [])
            if (evidence['source_id'], str(evidence['version'])) == key)
        cursor = start
        for lower, upper in ranges:
            if lower > cursor:
                break
            cursor = max(cursor, upper)
            if cursor >= end:
                return True
        return False

    def inspect(value, event_ids, path):
        if isinstance(value, dict):
            scoped = value.get('event_ids', event_ids)
            for field in ('source_refs', 'title_source_refs'):
                if any(not supported(ref, scoped) for ref in value.get(field, [])):
                    errors.append({'code': 'NONCANONICAL_EVIDENCE_SPAN', 'at': path + '.' + field,
                        'message': 'Cite spans covered by the current canonical event evidence, not another occurrence or the whole source.'})
            for key, child in value.items():
                if key not in {'source_refs', 'title_source_refs'}:
                    inspect(child, scoped, path + '.' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, event_ids, f'{path}.{index}')

    inspect(draft, list(events), 'draft')
    carried = set(draft['carry_forward_chapter_ids'])
    for prior in request['prior_state']['chapters']:
        if prior['chapter']['id'] in carried:
            inspect(prior['chapter'], list(events), 'carried.' + prior['chapter']['id'])
    return errors


def restore_unchanged_sections(request, draft):
    """Restore stored bytes before validation, evidence review and rendering."""
    preserved = request.get('context', {}).get('preserved_sections', [])
    bodies = [(chapter['id'], chapter) for chapter in draft.get('chapters', [])]
    if draft.get('kind') == 'sample_storyline':
        bodies.append(('sample_storyline', draft['storyline']))
    for chapter_id, chapter in bodies:
        prior = [s for s in preserved if s['chapter_id'] == chapter_id]
        # Preserve an unchanged passage when a one-body sample changes between
        # chapter and storyline. Do not reassign prose among arbitrary chapters.
        blocks = []
        for section in preserved:
            if 'block' not in section:
                continue
            if section['chapter_id'] == chapter_id:
                blocks.append(section)
                continue
            events = set(section['event_ids'])
            eligible = [(identity, body) for identity, body in bodies
                if events and events.issubset(set(body['event_ids'])) and
                (identity == 'sample_storyline' or section['chapter_id'] == 'sample_storyline')]
            if len(eligible) == 1 and eligible[0][0] == chapter_id:
                blocks.append(section)
        if len({s['block']['id'] for s in blocks}) != len(blocks):
            raise ValueError('Ambiguous preserved block identity across sample presentations')
        by_id = {s['block']['id']: s['block'] for s in blocks}
        preserved_events = {event_id for section in blocks for event_id in section['event_ids']}
        chapter['blocks'] = [copy.deepcopy(by_id.get(block['id'], block)) for block in chapter['blocks']
            if block['id'] in by_id or not set(section_event_ids(block, chapter, request)).issubset(preserved_events)]
        seen = {b['id'] for b in chapter['blocks']}
        chapter['blocks'].extend(copy.deepcopy(s['block']) for s in blocks if s['block']['id'] not in seen)
        chapter['source_refs'] = list({fingerprint(ref): ref for ref in chapter['source_refs']}.values())
        heading = next((s for s in prior if 'heading' in s), None)
        if heading:
            chapter.update(copy.deepcopy(heading['heading']))
            for entry in draft.get('outline', []):
                if entry['chapter_id'] == chapter_id:
                    entry['title'] = heading['heading']['title']
            if draft.get('kind') in {'sample_chapter', 'sample_storyline'}:
                draft['title'] = heading['heading']['title']
                draft['title_source_refs'] = copy.deepcopy(heading['source_refs'])
    return draft


def composer_request(job):
    previous = job.get('previous')
    if previous and 'manuscript' not in previous:
        # Restricted bundles are purged. Only independently authorised sections
        # survive as reuse data; none of their former surrounding text is copied.
        chapters = []
        for chapter_id in dict.fromkeys(s['chapter_id'] for s in previous['sections']):
            sections = [s for s in previous['sections'] if s['chapter_id'] == chapter_id]
            blocks = [copy.deepcopy(s['block']) for s in sections if 'block' in s]
            if not blocks:
                continue
            heading = next((s['heading'] for s in sections if 'heading' in s), {'title':'Memories','subtitle':''})
            ids = list(dict.fromkeys(id for s in sections for id in s['event_ids']))
            chapters.append({'id':chapter_id,'base_revision':job['base_revision'],**heading,
                'period_ids':list(dict.fromkeys('stage_'+e['life_stage'] for e in job['events'] if e['id'] in ids)),
                'event_ids':ids,'source_refs':[r for s in sections if 'block' in s for r in s['source_refs']],
                'blocks':blocks,'change_type':'enrich','update_reason':'Surviving original evidence.'})
        manuscript = {'kind':previous['kind'],'chapters':chapters}
        if previous['kind'] == 'sample_storyline':
            body = next((chapter for chapter in chapters if chapter['id']=='sample_storyline'), None)
            manuscript = {'kind':'sample_storyline','chapters':[], 'storyline':{
                'title':body['title'] if body else 'Memories',
                'source_refs':body['source_refs'] if body else [],
                'event_ids':body['event_ids'] if body else [],
                'blocks':body['blocks'] if body else []}}
        previous = {**previous,'manuscript':manuscript,'draft':{'input_fingerprint':''}}
    sources = [{key: source[key] for key in ('id', 'project_id', 'kind', 'author_role', 'text', 'status')}
               | {'version': str(source['version']), 'allowed': True, 'derived_from': [],
                  'source_order': source['sequence']} for source in job['sources']]
    for source in sources:
        if source['kind'] == 'narrator_transcript':
            source['kind'] = 'transcript'
    originals = {source['id']: source for source in sources}
    def refs(event):
        values = []
        for ref in event['source_refs']:
            source = originals.get(ref['source_id'])
            if not source or str(ref['version']) != source['version']:
                continue
            quote = ref.get('quote', '')
            if not quote:
                continue
            start, end = ref.get('char_start'), ref.get('char_end')
            if start is not None or end is not None:
                # Canonical spans identify the authorised occurrence when the
                # original contains repeated words. Never rebind them to the
                # first match, which may belong to another or vetoed event.
                if (not isinstance(start, int) or not isinstance(end, int)
                        or start < 0 or end <= start):
                    continue
                # Earlier Python/SQL validation allowed an oversized suffix
                # end because slicing clamps. Preserve its proven start and
                # quote, but emit a bounded span for the composer contract.
                offset = job.get('source_windows', {}).get(source['id'], {}).get('char_start', 0)
                end = min(end, offset + len(source['text']))
                if start < offset or start >= end or source['text'][start-offset:end-offset] != quote:
                    continue
            else:
                start = source['text'].find(quote)
                if start < 0:
                    continue
                start += job.get('source_windows', {}).get(source['id'], {}).get('char_start', 0)
                end = start + len(quote)
            values.append({'source_id': source['id'], 'version': source['version'],
                           'char_start': start, 'char_end': end})
        return values
    events, periods = [], []
    for stage in (*LIFE_STAGES, 'unplaced'):
        grouped = [e for e in job['events'] if e['life_stage'] == stage and e['status'] == 'active' and refs(e)]
        if not grouped:
            continue
        period_id = 'stage_' + stage
        periods.append({'id': period_id, 'order': len(periods), 'label': stage.replace('_', ' '),
                        'source_refs': [ref for e in grouped for ref in refs(e)]})
        for event in grouped:
            temporal = event.get('temporal', {})
            precision = temporal.get('precision', 'unknown')
            events.append({'id': event['id'], 'period_id': period_id, 'summary': event['title'],
                'source_refs': refs(event), 'status': 'active', 'narrative': True,
                'date': {'original_expression': temporal.get('expression', ''),
                    'start_year': temporal.get('year_start'), 'end_year': temporal.get('year_end'),
                    'precision': precision if precision in {'year', 'range', 'decade', 'relative', 'unknown'} else 'relative'}})
    photo_associations = []
    for original_event in job['events']:
        if original_event['id'] not in {event['id'] for event in events}:
            continue
        for association in original_event.get('photo_associations', []):
            original = originals.get(association.get('source_id'))
            quote = association.get('quote') or ''
            if (association.get('status') != 'confirmed'
                or association.get('event_id') != original_event['id']
                or association.get('provenance') != 'narrator_metadata'
                or not original or original.get('status') != 'active'
                or str(association.get('source_version')) != original['version']
                or not quote or quote not in original['text']):
                continue
            evidence = [ref for ref in refs(original_event)
                if ref['source_id'] == original['id'] and ref['version'] == original['version']
                and quote in original['text'][
                    ref['char_start']-job.get('source_windows', {}).get(original['id'], {}).get('char_start', 0):
                    ref['char_end']-job.get('source_windows', {}).get(original['id'], {}).get('char_start', 0)] ]
            if not evidence:
                continue
            photo_associations.append({'id': association['id'], 'photo_id': association['photo_id'],
                'event_id': original_event['id'], 'source_refs': evidence, 'quote': quote,
                'description': association.get('description', ''), 'provenance': 'narrator_metadata',
                'derived': True})
    key = fingerprint({'sources': job['source_manifest'], 'events': job['event_manifest'],
                       'photos': photo_associations,
                       'policy': job['policy_epoch'], 'locale': job['locale'], 'base': job['base_revision'],
                       **({'lifetime_page': [job['snapshot_id'], job['page_number'], job['input_digest'], job['preference_revision']]} if job.get('governed_page') else {})})
    # Revocation may purge the prior bytes without resetting the authoritative
    # manuscript revision. A fresh supported candidate still fences that base.
    prior = {'kind': 'sample_chapter' if job['base_revision'] else 'none',
             'revision': job['base_revision'], 'chapters': [], 'last_snapshot_fingerprint': ''}
    if previous:
        prior = {'kind': previous['manuscript']['kind'], 'revision': job['base_revision'],
            'chapters': [{'revision': job['base_revision'], 'approved': False, 'human_locked': False,
                         'chapter': copy.deepcopy(chapter)} for chapter in previous['manuscript']['chapters']],
            'last_snapshot_fingerprint': previous['draft']['input_fingerprint']}
    photo_manifest = {event_id: fingerprint([a for a in photo_associations if a['event_id'] == event_id])
                      for event_id in sorted({a['event_id'] for a in photo_associations})}
    old_photos = (previous or {}).get('photo_association_manifest', {})
    photo_dirty = sorted(event_id for event_id in set(old_photos) | set(photo_manifest)
                         if old_photos.get(event_id) != photo_manifest.get(event_id))
    if previous and 'photo_association_manifest' not in previous:
        # Older or restricted legacy bundles cannot prove that their surviving
        # sections are independent of a now-removed photo. Recompose them.
        photo_dirty = sorted(set(photo_dirty) | {
            event_id for section in previous.get('sections', []) for event_id in section['event_ids']})
    previous_revisions = (previous or {}).get('event_manifest', [])
    old = {e['id']: e['revision'] for e in previous_revisions}
    dirty = [e['id'] for e in job['event_manifest'] if old.get(e['id']) != e['revision']]
    dirty += [e['id'] for e in previous_revisions if e['id'] not in {n['id'] for n in job['event_manifest']}]
    dirty = list(dict.fromkeys(dirty + photo_dirty))
    affected_sources = list(dict.fromkeys(ref['source_id'] for event in events if event['id'] in dirty for ref in event['source_refs']))
    if not affected_sources and events:
        # A pure withdrawal can leave only safe unchanged sections to assemble.
        affected_sources = list(dict.fromkeys(ref['source_id'] for ref in events[0]['source_refs']))
    return {'schema_version': '1.0', 'request_id': key, 'event_id': key, 'project_id': job['project_id'],
        'target': {'locale': job['locale'], 'audience': 'storyteller', 'medium': 'web'},
        'policy': {'max_chapter_words': 7000, 'soft_chapter_words': 6000, 'focus_threshold': .65,
                   'max_followup_questions': 0, 'preview_preference': 'auto'},
        'trigger': {'type': 'new_context' if job['base_revision'] else 'private_draft_checkpoint', 'confirmed': True,
            'free_rounds_completed': job['coverage_round'], 'free_round_limit': free_recall_rounds(),
            'storytelling_confirmation_ref': None, 'composition_authorized': False,
            'private_draft_authorized': True, 'private_rounds_completed': job['coverage_round'],
            'private_draft_cadence': private_draft_cadence()},
        'snapshot': {'id': key, 'policy_epoch': job['policy_epoch'], 'expected_manuscript_revision': job['base_revision'],
                     'retrieval_complete': True, 'glossary_version': '1', 'preferences_version': job['locale']},
        'sources': sources, 'events': events, 'periods': periods, 'assets': [],
        'prior_state': prior, 'authorised_retirements': [],
        'context': {'canonical_event_index': True, 'dirty_event_ids': dirty, 'style': 'plain, warm, faithful',
                    **({'lifetime_page': {'schema_version': 1, 'snapshot_id': job['snapshot_id'],
                        'page_number': job['page_number'], 'coverage_scope': 'canonical_evidence_partition',
                        'snapshot_complete': False}, 'source_windows': job['source_windows'],
                        'preferences': job['preferences']} if job.get('governed_page') else {}),
                    'photo_associations': photo_associations,
                    'photo_association_manifest': photo_manifest, 'photo_dirty_event_ids': photo_dirty,
                    'incremental_model_context': 'compact', 'affected_source_ids': affected_sources,
                    'overlap_source_ids': [s['id'] for s in sources[-2:]]}}


async def compose_shared_snapshot(job, worker):
    request = composer_request(job)
    config = fingerprint({'locale': job['locale'], 'skill': 'shared-composer-4',
        'model': os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', os.getenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')),
        'policy': request['policy']})
    if job.get('previous') and job['previous'].get('content_config') != config:
        # Changing the projection invalidates carried chapters as well as
        # cached bundles. Require a reviewed replacement instead of blessing
        # stale evidence as v2, including a model's carry-forward shortcut.
        request['context']['dirty_event_ids'] = list(dict.fromkeys([
            *request['context']['dirty_event_ids'], *(e['id'] for e in request['events'])]))
        request['context']['affected_source_ids'] = list(dict.fromkeys(
            ref['source_id'] for event in request['events'] for ref in event['source_refs']))
        request['context']['projection_invalidated_chapter_ids'] = [
            prior['chapter']['id'] for prior in request['prior_state']['chapters']]
    # Even unchanged canonical event revisions cannot authorize reusing prose
    # whose photograph association changed or was explicitly removed.
    photo_dirty = set(request['context']['photo_dirty_event_ids'])
    photo_chapters = [prior['chapter']['id'] for prior in request['prior_state']['chapters']
                      if photo_dirty.intersection(prior['chapter']['event_ids'])]
    request['context']['projection_invalidated_chapter_ids'] = list(dict.fromkeys([
        *request['context'].get('projection_invalidated_chapter_ids', []), *photo_chapters]))
    if job.get('previous') and 'manuscript' in job['previous'] and not request['context']['dirty_event_ids'] and job['previous'].get('content_config') == config:
        bundle = copy.deepcopy(job['previous'])
        bundle['unchanged'] = True
        return bundle
    old_events = {e['id']: e['revision'] for e in (job.get('previous') or {}).get('event_manifest', [])}
    current_events = {e['id']: e['revision'] for e in job['event_manifest']}
    current_sources = {(s['id'], str(s['version'])) for s in job['sources']}
    request['context']['preserved_sections'] = [copy.deepcopy(section) for section in (job.get('previous') or {}).get('sections', [])
        if job['previous'].get('content_config') == config
        and not photo_dirty.intersection(section['event_ids'])
        and all(current_events.get(id) == old_events.get(id) for id in section['event_ids'])
        and all((ref['source_id'], str(ref['version'])) in current_sources for ref in section['source_refs'])]
    runtime = SimpleNamespace(worker_url=worker.worker_url, worker_secret=worker.worker_secret,
                              worker_transport=worker.worker_transport)
    storage = SimpleNamespace(user_id=job['user_id'])
    if job.get('governed_page'):
        runtime.lifetime_bounded = True
        runtime.lifetime_page = job['authoritative_page']
        runtime.lane_broker = worker.broker
        runtime.lane_publisher = getattr(worker, 'lane_publisher', None)
    checkpoint_key = fingerprint({'snapshot': request['snapshot'], 'config': config})
    checkpoint = await worker.broker.rpc('read_memoir_checkpoint', p_lane_id=job['lane_id'], p_token=job['token'], p_key=checkpoint_key) or {}
    async def progress(phase):
        await worker.broker.rpc('save_memoir_checkpoint', p_lane_id=job['lane_id'], p_token=job['token'],
                               p_key=checkpoint_key, p_kind='compose', p_value=checkpoint,
                               **({'p_page_digest': job['page_digest']} if job.get('governed_page') else {}))
    limit = min(max(int(os.getenv('MEMORY_SPARK_MEMOIR_PREPARATION_CONCURRENCY', '3')), 1), 4)
    semaphore = asyncio.Semaphore(limit)
    async def prepare(event):
        key = fingerprint({'event': event, 'config': config, 'policy_epoch': job['policy_epoch'], 'base': job['base_revision'],
            **({'lifetime_page': [job['snapshot_id'], job['page_number'], job['input_digest'], job['preference_revision']]} if job.get('governed_page') else {})})
        saved = await worker.broker.rpc('read_memoir_checkpoint', p_lane_id=job['lane_id'], p_token=job['token'], p_key=key)
        if saved:
            return saved
        async with semaphore:
            ids = {ref['source_id'] for ref in event['source_refs']}
            packet = {'preparation_id': key, 'partition': event,
                      'sources': [s for s in job['sources'] if s['id'] in ids]}
            result = await composer_call(runtime, storage, job['project_id'], job['locale'], 'prepare', packet)
            if set(result) != {'event_id', 'context', 'source_refs'} or result['event_id'] != event['id'] or not isinstance(result['context'], str) or len(result['context']) > 10000:
                raise ValueError('Invalid prepared partition')
            expected = [EvidenceRef.model_validate(ref).model_dump(exclude_none=True) for ref in event['source_refs']]
            actual = [EvidenceRef.model_validate(ref).model_dump(exclude_none=True) for ref in result['source_refs']]
            if actual != expected:
                raise ValueError('Prepared evidence differs from the canonical partition')
            await worker.broker.rpc('save_memoir_checkpoint', p_lane_id=job['lane_id'], p_token=job['token'],
                                   p_key=key, p_kind='prepare', p_value=result,
                                   **({'p_page_digest': job['page_digest']} if job.get('governed_page') else {}))
            return result
    prepared = await asyncio.gather(*(prepare(e) for e in job['events'] if e['id'] in request['context']['dirty_event_ids'] and e['status'] == 'active'), return_exceptions=True)
    failures = [result for result in prepared if isinstance(result, BaseException)]
    if failures:
        if job.get('governed_page'):
            from .lifetime_memory_lane_engine import LaneGenerationPaused
            from .lifetime_memory_activation import CanonicalActivationUnavailable
            deferred = next((error for error in failures if isinstance(error, (LaneGenerationPaused, CanonicalActivationUnavailable))), None)
            if deferred is not None:
                raise deferred
            budget_failure = next((error for error in failures if isinstance(error, ValueError) and 'budget' in str(error).lower()), None)
            if budget_failure is not None:
                raise budget_failure
        raise RuntimeError('Partition preparation needs retry') from None
    request['context']['prepared_partitions'] = prepared
    bundle = await compose_candidate(request, runtime, storage, job['project_id'], job['locale'],
                                     checkpoint=checkpoint, progress=progress)
    if bundle['status'] == 'insufficient_context':
        return bundle
    if bundle['status'] != 'ready':
        raise RuntimeError('No supported composition context')
    bundle['event_manifest'] = job['event_manifest']
    bundle['source_manifest'] = job['source_manifest']
    bundle['content_config'] = config
    bundle['photo_association_manifest'] = request['context']['photo_association_manifest']
    sections = []
    manifest = {e['id']: e['revision'] for e in job['event_manifest']}
    bodies = [(chapter['id'], chapter) for chapter in bundle['manuscript']['chapters']]
    if bundle['manuscript']['kind'] == 'sample_storyline':
        bodies.append(('sample_storyline', bundle['manuscript']['storyline']))
    for chapter_id, chapter in bodies:
        # Headings and transitions conservatively declare the chapter's events.
        # This preserves all dependencies, including multi-event original turns.
        for block in chapter['blocks']:
            event_ids = section_event_ids(block, chapter, request)
            sections.append({'id': chapter_id + '__' + block['id'], 'chapter_id': chapter_id,
                'event_ids': event_ids, 'source_refs': block['source_refs'], 'content': block['text'],
                'block': block, 'fingerprint': fingerprint({'events': {id: manifest[id] for id in event_ids},
                    'sources': block['source_refs'], 'photos': {id: bundle['photo_association_manifest'].get(id) for id in event_ids}, 'configuration': config})})
        heading = {'title': chapter['title']}
        if chapter_id != 'sample_storyline':
            heading['subtitle'] = chapter['subtitle']
        sections.append({'id': chapter_id + '__heading', 'chapter_id': chapter_id,
            'event_ids': chapter['event_ids'], 'source_refs': chapter['source_refs'],
            'content': chapter['title'], 'heading': heading,
            'fingerprint': fingerprint({'events': {id: manifest[id] for id in chapter['event_ids']},
                'sources': chapter['source_refs'], 'photos': {id: bundle['photo_association_manifest'].get(id) for id in chapter['event_ids']}, 'configuration': config})})
    bundle['sections'] = sections
    return bundle
