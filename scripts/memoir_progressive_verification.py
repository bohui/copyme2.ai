"""Evidence and streaming measurements for a retained fifty-round rerun."""
import asyncio
import hashlib
import json
import re
import time


def sources_unchanged(before, after):
    fields = ('id', 'project_id', 'text', 'language', 'kind', 'status', 'version', 'sequence')
    return len(after) >= len(before) and all(
        all(old.get(key) == new.get(key) for key in fields) for old, new in zip(before, after))


def original_evidence(checkpoint, sources):
    originals = {s['id']: s for s in sources}
    checked = 0
    for page in checkpoint['pages']:
        for passage in page['records']:
            for ref in passage['source_refs']:
                source = originals.get(ref.get('source_id'))
                start, end = ref.get('char_start'), ref.get('char_end')
                if (source is None or str(ref.get('version')) != str(source['version'])
                    or type(start) is not int or type(end) is not int
                    or not 0 <= start < end <= len(source['text'])
                    or ('quote' in ref and ref['quote'] != source['text'][start:end])):
                    raise ValueError('invalid_original_passage_evidence')
                checked += 1
    return {'references_verified': checked, 'original_sources_retained': len(sources)}


def preserve_unchanged(previous, current, previous_events, events, *, privacy_fence=None):
    privacy_changed = False
    if previous and privacy_fence is not None:
        if (privacy_fence.get('previous_snapshot_id') != previous['draft']['snapshot_id']
            or privacy_fence.get('current_snapshot_id') != current['draft']['snapshot_id']
            or any(not isinstance(privacy_fence.get(key),str)
                or re.fullmatch('[0-9a-f]{64}',privacy_fence[key]) is None
                for key in ('previous_privacy_digest','current_privacy_digest'))):
            raise ValueError('invalid_checkpoint_privacy_fence')
        privacy_changed = privacy_fence['previous_privacy_digest'] != privacy_fence['current_privacy_digest']
    old_events = {e['id']: e for e in previous_events}
    new_events = {e['id']: e for e in events}
    latest = {r['id']: r for p in current['pages'] for r in p['records']}
    checked, changed, privacy_changed_passages = [], 0, 0
    for page in (previous or {}).get('pages', []):
        for old in page['records']:
            if privacy_changed:
                privacy_changed_passages += 1
                continue
            dependencies = {old['event_id']}
            # Conservatively include every previously canonical event touching
            # the passage's source spans, rather than just its leading event.
            for event in old_events.values():
                if any(a['source_id'] == b['source_id'] and str(a['version']) == str(b['version'])
                       for a in event.get('source_refs', []) for b in old['source_refs']):
                    dependencies.add(event['id'])
            if (previous['draft'].get('policy_epoch') != current['draft'].get('policy_epoch')
                or any(key not in new_events or key not in old_events
                    or new_events[key]['revision'] != old_events[key]['revision'] for key in dependencies)):
                changed += 1
                continue
            new = latest.get(old['id'])
            if new is None or new['preview']['text'] != old['preview']['text']:
                raise ValueError('unchanged_memoir_writing_changed_or_missing')
            checked.append({'id': old['id'], 'sha256': hashlib.sha256(old['preview']['text'].encode()).hexdigest()})
    return {'unchanged_passages': checked, 'changed_event_passages': changed,
            'privacy_changed_passages': privacy_changed_passages,
            'scope': 'passage text whose canonical dependencies and policy stayed unchanged'}


def saved_message_summary(settings, binding, checkpoint, messages, *, previous=None):
    """Read only this owned frozen root; derived summaries must cite new originals."""
    import psycopg
    dsn = settings.get('MEMOIR_PUBLICATION_DATABASE_URL') or settings.get('SUPABASE_DB_URL')
    with psycopg.connect(dsn,connect_timeout=8,options='-c statement_timeout=10000') as connection:
        connection.read_only = True
        with connection.cursor() as cursor:
            snapshots = {'current':checkpoint, **({'previous':previous} if previous else {})}
            cursor.execute("""select id::text,root_digest,policy_epoch,preference_revision,privacy_digest
                from public.user_lifetime_lane_snapshot where user_id=%s and project_id=%s
                  and id=any(%s::uuid[]) and state in ('completed','proposed')""",
                (binding['owner_id'],binding['project_id'],[s['draft']['snapshot_id'] for s in snapshots.values()]))
            roots = {row[0]:row[1:] for row in cursor.fetchall()}
            privacy_fence = {}
            for label, saved in snapshots.items():
                draft = saved['draft']
                root = roots.get(draft['snapshot_id'])
                if (root is None or root[:3] != (draft['root_digest'],draft['policy_epoch'],saved['pages'][0]['preference_revision'])):
                    raise ValueError('checkpoint_privacy_fence_mismatch')
                privacy_fence[label+'_snapshot_id'] = draft['snapshot_id']
                privacy_fence[label+'_privacy_digest'] = root[3]
            cursor.execute("""select distinct on (c.lifetime_page,c.value->>'event_id') c.value from public.user_memoir_checkpoint c
                join public.user_lifetime_lane_snapshot root on root.id=c.lifetime_snapshot_id
                where root.id=%s and root.user_id=%s and root.project_id=%s and c.kind='prepare'
                  and c.value->>'event_id' like '%%-messages-%%'
                order by c.lifetime_page,c.value->>'event_id',c.created_at desc""",
                (checkpoint['draft']['snapshot_id'],binding['owner_id'],binding['project_id']))
            summaries = [row[0] for row in cursor.fetchall()]
    expected = {s['id']:s for s in messages}
    spans = {key:[] for key in expected}
    for summary in summaries:
        if not isinstance(summary.get('context'),str) or not summary['context'].strip():
            raise ValueError('missing_saved_message_summary')
        for ref in summary.get('source_refs',[]):
            original = expected.get(ref.get('source_id'))
            start,end=ref.get('char_start'),ref.get('char_end')
            if (original is None or str(ref.get('version'))!=str(original['version'])
                or type(start) is not int or type(end) is not int or not 0<=start<end<=len(original['text'])
                or ref.get('quote')!=original['text'][start:end]):
                raise ValueError('summary_did_not_preserve_new_original_evidence')
            spans[original['id']].append((start,end))
    for identifier,ranges in spans.items():
        position=0
        for start,end in sorted(ranges):
            if start!=position:
                raise ValueError('summary_original_coverage_gap_or_replay')
            position=end
        if position!=len(expected[identifier]['text']):
            raise ValueError('summary_original_coverage_incomplete')
    return {'saved_summaries':len(summaries),'summarised_original_messages':len(expected),
            'privacy_fence':privacy_fence,
            'summary_scope':'new original messages since the preceding checkpoint'}


async def streamed_turn(requests, url, headers, payload, *, timeout=600):
    """One bounded POST; count its admission, never retry a partial stream."""
    remaining = requests.remaining()
    if remaining <= 0 or requests.reserved >= requests.maximum or requests.read_only:
        raise ValueError('stream_admission_budget_exhausted')
    requests.reserved += 1
    if requests.on_reserve:
        requests.on_reserve(requests.reserved)
    started = time.monotonic()
    measurements = {'first_text_seconds': None, 'last_text_seconds': None,
        'saved_seconds': None, 'total_seconds': None, 'text_delta_count': 0,
        'visible_characters': 0, 'transport': 'application/x-ndjson'}
    result, saved, wire_bytes = None, False, 0
    async with asyncio.timeout(min(timeout, remaining)):
        async with requests.client.stream('POST', url, headers={**headers, 'Accept':'application/x-ndjson'},
            json=payload, timeout=min(timeout, remaining)) as response:
            response.raise_for_status()
            if response.headers.get('content-type', '').split(';')[0] != 'application/x-ndjson':
                raise ValueError('turn_did_not_stream_ndjson')
            async for line in response.aiter_lines():
                wire_bytes += len(line.encode())
                if wire_bytes > 2 * 1024 * 1024:
                    raise ValueError('stream_receipt_body_budget_exceeded')
                if not line.strip():
                    continue
                event = json.loads(line)
                elapsed = round(time.monotonic() - started, 4)
                if event.get('type') == 'error':
                    raise ValueError('stream_returned_error')
                if event.get('type') == 'text_delta' and event.get('text'):
                    if measurements['first_text_seconds'] is None:
                        measurements['first_text_seconds'] = elapsed
                    measurements.update(last_text_seconds=elapsed,
                        text_delta_count=measurements['text_delta_count'] + 1,
                        visible_characters=measurements['visible_characters'] + len(event['text']))
                elif event.get('type') == 'conversation_saved':
                    saved = True
                    measurements['saved_seconds'] = elapsed
                elif event.get('type') == 'result':
                    if result is not None:
                        raise ValueError('duplicate_stream_result')
                    result = event['data']
    measurements['total_seconds'] = round(time.monotonic() - started, 4)
    if result is None or not saved or measurements['first_text_seconds'] is None or requests.remaining() <= 0:
        raise ValueError('stream_did_not_deliver_text_and_save')
    return result, measurements
