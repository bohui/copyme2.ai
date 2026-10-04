"""Controlled external app-server/provider protocol, never live model evidence.

The application worker and CodexConnection execute normally. Only provider
output is read from a synthetic task-local control file supplied by the test.
"""
import json
import sys
import time
from pathlib import Path

control = json.load(open(sys.argv[1], encoding='utf-8'))


def send(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def hold(phase, packet):
    if not control.get('hold_phase') == phase:
        return
    with open(control['calls'], 'a', encoding='utf-8') as calls:
        calls.write(json.dumps({'phase': phase + '_held', 'source_ids': [s['id'] for s in packet.get('sources', packet.get('request', {}).get('sources', []))]}) + '\n')
    while Path(control['gate']).exists():
        time.sleep(.05)


def composer_reply(params):
    """Controlled literal story; copy only host IDs and protocol metadata."""
    text = next(part['text'] for part in params['input'] if part['type'] == 'text')
    packet = json.loads(text.split('Storyteller message:\n', 1)[-1])
    if 'partition' in packet:
        partition = packet['partition']
        with open(control['calls'], 'a', encoding='utf-8') as calls:
            calls.write(json.dumps({'phase': 'prepare_start', 'event_id': partition['id']}) + '\n')
        hold('prepare',packet)
        time.sleep(control.get('prepare_delay', 0))
        with open(control['calls'], 'a', encoding='utf-8') as calls:
            calls.write(json.dumps({'phase': 'prepare_end', 'event_id': partition['id']}) + '\n')
        if partition['title'] in control.get('fail_prepare', []):
            return {'controlled_external_failure': True}
        return {'event_id': partition['id'], 'context': partition['title'], 'source_refs': partition['source_refs']}
    phase = 'review' if 'candidate' in packet and 'plan' not in packet else 'draft' if 'plan' in packet else 'index'
    with open(control['calls'], 'a', encoding='utf-8') as calls:
        calls.write(json.dumps({'phase': phase,
            'source_ids':[s['id'] for s in packet.get('request',{}).get('sources',[])],
            'dirty_event_ids':packet.get('request',{}).get('context',{}).get('dirty_event_ids',[])}) + '\n')
    hold(phase, packet)
    if phase == 'review':
        if control.get('blocking_review'):
            return {'ready_for_user_review':False,'publication_approved':False,
                'findings':[{'severity':'blocking','explanation':'Controlled unsupported prose.'}]}
        return {'ready_for_user_review': True, 'publication_approved': False, 'findings': []}
    if phase == 'index':
        return {'periods': [], 'events': []}  # Canonical composition must never request this.
    request, plan = packet['request'], packet['plan']
    events = request['events']
    preserved=[s for s in request.get('context',{}).get('preserved_sections',[]) if 'block' in s]
    manifest=request.get('context',{}).get('canonical_event_manifest',events)
    if control.get('focus_first'):
        # This controlled adversary may rewrite an unchanged prior block even
        # when its raw evidence is absent from the compact model packet.
        target=preserved[0]['event_ids'][0] if preserved else events[0]['id']
        events=[next(e for e in manifest if e['id']==target)]
    refs = events[0]['source_refs']
    periods = list(dict.fromkeys(e['period_id'] for e in events if e['period_id']))
    ids = [e['id'] for e in events]
    chapter_id = 'school-chapter'
    prior = next((c for c in request['prior_state']['chapters'] if c['chapter']['id'] == chapter_id), None)
    words = control.get('prose', 'I started school around 1964.')
    chapter = {'id': chapter_id, 'base_revision': prior['revision'] if prior else 0,
        'title': control.get('title','Starting school'), 'subtitle': '', 'period_ids': periods, 'event_ids': ids,
        'source_refs': refs, 'blocks': [{'id': control.get('block_id','school-passage'), 'type': 'paragraph', 'text': words,
            'asset_id': None, 'asset_version': None, 'caption': '', 'alt': '', 'credit': '',
            'source_refs': refs, 'uncertainty': ['approximate date']}],
        'change_type': 'enrich' if prior else 'create', 'update_reason': 'Original narrator evidence.'}
    if control.get('event_prose'):
        chapter['source_refs'] = [ref for event in events for ref in event['source_refs']]
        chapter['blocks'] = [{'id': 'passage_' + event['id'], 'type': 'paragraph',
            'text': control['event_prose'][event['summary']], 'asset_id': None, 'asset_version': None,
            'caption': '', 'alt': '', 'credit': '', 'source_refs': event['source_refs'], 'uncertainty': []}
            for event in events]
    if request.get('context',{}).get('incremental_model_context')=='compact':
        seen={block['id'] for block in chapter['blocks']}
        chapter['blocks'].extend(s['block'] for s in preserved if s['block']['id'] not in seen)
        ids=list(dict.fromkeys([*ids,*(id for s in preserved for id in s['event_ids'])]))
        periods=list(dict.fromkeys(e['period_id'] for e in manifest if e['id'] in ids and e['period_id']))
        chapter.update(event_ids=ids,period_ids=periods,source_refs=[ref for b in chapter['blocks'] for ref in b['source_refs']])
    return {'schema_version': '1.0', 'project_id': request['project_id'],
        'input_snapshot_id': plan['input_snapshot_id'], 'input_fingerprint': plan['input_fingerprint'],
        'expected_manuscript_revision': plan['expected_manuscript_revision'], 'kind': plan['kind'], 'status': 'draft',
        'title': control.get('title','Starting school'), 'title_source_refs': refs, 'counter': plan['counter'],
        'source_summary': [{'id': 'school-summary', 'text': 'Started school around 1964.',
            'source_refs': refs, 'event_ids': ids, 'uncertainty': ['approximate date']}],
        'outline': [{'chapter_id': chapter_id, 'order': 0, 'title': control.get('title','Starting school'),
            'period_ids': periods, 'event_ids': ids, 'status': 'draft',
            'rationale': 'A supported episode.', 'source_refs': refs}],
        'chapters': [chapter], 'storyline': {'title': '', 'source_refs': [], 'event_ids': [], 'blocks': []},
        'carry_forward_chapter_ids': [], 'retired_chapter_ids': [], 'proposed_replacements': [],
        'event_dispositions': [{'event_id': e['id'], 'disposition': 'included' if e['id'] in ids else 'deferred',
            'chapter_ids': [chapter_id] if e['id'] in ids else [],'reason': 'Original evidence or a later supported chapter.'}
            for e in manifest], 'questions_for_mira': [], 'review_flags': [],
        'next_action': 'review_preview'}


for line in sys.stdin:
    message = json.loads(line)
    method = message.get('method')
    if 'id' not in message:
        continue
    if method == 'initialize':
        send({'id': message['id'], 'result': {'userAgent': 'issue6-controlled-provider'}})
    elif method in {'thread/start', 'thread/resume'}:
        send({'id': message['id'], 'result': {'thread': {'id': 'synthetic-thread'}}})
    elif method == 'turn/start':
        params = message['params']
        send({'id': message['id'], 'result': {'turn': {'id': 'synthetic-turn'}}})
        if control.get('delay'):
            time.sleep(control['delay'])
        if control.get('mode') == 'timeline':
            text=next(part['text'] for part in params['input'] if part['type']=='text')
            packet=json.loads(text.split('Storyteller message:\n',1)[-1])
            with open(control['calls'],'a',encoding='utf-8') as calls:
                calls.write(json.dumps({'phase':'timeline','source_ids':[s['id'] for s in packet['sources']]})+'\n')
            hold('timeline',packet)
        reply = composer_reply(params) if control.get('mode') == 'composer' else control['reply']
        if isinstance(reply, dict):
            reply = json.dumps(reply, ensure_ascii=False)
        send({'method': 'item/completed', 'params': {'threadId': params['threadId'], 'turnId': 'synthetic-turn',
            'item': {'type': 'agentMessage', 'text': reply}}})
        send({'method': 'turn/completed', 'params': {'threadId': params['threadId'],
            'turn': {'id': 'synthetic-turn', 'status': 'completed'}}})
    else:
        send({'id': message['id'], 'error': {'code': -32601, 'message': 'unsupported synthetic method'}})
