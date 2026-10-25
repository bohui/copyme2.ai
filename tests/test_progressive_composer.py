"""Five-round summaries and exact carry-forward through the real model boundary."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest

from apps.api.canonical_composer import compose_shared_snapshot
from apps.api.lifetime_memory_lane_engine import BoundedLaneInput
from apps.api.progressive_composer import batch_job, summary_partition
from test_canonical_composer_provenance import controlled_draft
from test_lifetime_memory_lane_engine import page, Publisher
from test_lifetime_composer_capacity import (sql, event_database, private_database, attachment_database, database,  # noqa: F401
    resolve, rpc, literal, service, create_lane, OWNER)


def batch_page():
    current = page('composer')
    sources = []
    for index in range(5):
        text = f'I repaired bicycle {index + 1} in our shed.'
        sources.append({**current['source'], 'id': str(UUID(int=20 + index)), 'sequence': index + 1,
            'text': text, 'char_start': 0, 'char_end': len(text), 'original_length': len(text)})
    events = [{**current['partition'], 'id': str(UUID(int=40 + i)), 'title': s['text'],
        'source_refs': [dict(source_id=s['id'], version=1, quote=s['text'], char_start=0, char_end=len(s['text']))]}
        for i, s in enumerate(sources)]
    current.update(source=sources[0], partition=events[0], coverage_round=5, base_revision=0,
        batch=dict(schema_version=1, starting_after=0, through_source=5, next_offset=100000,
            cursor=[5, events[-1]['id'], 'last-ref'], sources=sources, events=events,
            new_messages=sources, previous=None, previous_summary=None))
    return current


def draft_all(packet):
    request = packet['request']
    result = controlled_draft(packet, request['sources'][0]['text'], 'Bicycles in our shed')
    refs = [ref for e in request['events'] for ref in e['source_refs']]
    ids = [e['id'] for e in request['events']]
    result['title_source_refs'] = refs
    result['source_summary'][0].update(text='Bicycle repairs in our shed.', source_refs=refs, event_ids=ids)
    result['outline'][0].update(source_refs=refs, event_ids=ids)
    body = result['chapters'][0] if result['chapters'] else result['storyline']
    body.update(source_refs=refs, event_ids=ids)
    template = body['blocks'][0]
    body['blocks'] = [{**deepcopy(template), 'id': 'passage-' + event['id'],
        'text': ' '.join(next(s['text'][ref['char_start']:ref['char_end']] for s in request['sources'] if s['id'] == ref['source_id'])
                         for ref in event['source_refs']),
        'source_refs': event['source_refs']} for event in request['events']]
    result['event_dispositions'] = [{**result['event_dispositions'][0], 'event_id': event_id} for event_id in ids]
    return result


class Broker:
    def __init__(self):
        self.checkpoints = {}
    async def rpc(self, name, **payload):
        if name == 'read_memoir_checkpoint':
            return deepcopy(self.checkpoints.get(payload['p_key']))
        if name == 'save_memoir_checkpoint':
            self.checkpoints[payload['p_key']] = deepcopy(payload['p_value'])
            return True
        assert name == 'record_lifetime_lane_output'
        return True


def compose(current, phases, broker, mutate_unchanged=False):
    def model(request):
        bounded = BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        packet = json.loads(bounded.packet)['payload']
        phases.append(bounded.phase)
        if bounded.phase == 'prepare':
            partition = packet['partition']
            assert packet['sources'] == current['batch']['new_messages']
            result = dict(event_id=partition['id'], context='New bicycle memories, with their original evidence.',
                          source_refs=partition['source_refs'])
        elif bounded.phase == 'draft':
            result = draft_all(packet)
            if mutate_unchanged:
                result['chapters'][0]['blocks'][-1]['text'] = 'An unsolicited rewrite of unchanged prose.'
        else:
            result = dict(ready_for_user_review=True, publication_approved=False, findings=[])
        return httpx.Response(200, json={'reply': json.dumps(result)})
    worker = SimpleNamespace(broker=broker, worker_url='https://synthetic.invalid', worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model), lane_publisher=Publisher())
    return asyncio.run(compose_shared_snapshot(batch_job(current), worker))


@pytest.mark.parametrize('control', ['excluded_topics', 'paused_topics'])
def test_restricted_batch_retains_model_preparation(control):
    current = batch_page()
    current['preferences'][control] = ['A restricted topic']
    phases = []
    bundle = compose(current, phases, Broker())
    assert bundle['status'] == 'ready'
    assert phases == ['prepare', 'draft', 'review']
    assert bundle['request']['context']['prepared_partitions'][0]['context'] == 'New bicycle memories, with their original evidence.'


def test_lossless_context_preserves_unicode_whitespace_and_message_order():
    current = batch_page()
    messages = deepcopy(current['batch']['new_messages'][:2])
    for source, text in zip(messages, [' 🌱 e\u0301。\n我不记得年份。 ', '父亲说是1984年，但我不确定。']):
        source.update(text=text, char_start=0, char_end=len(text), original_length=len(text))
    current['batch']['new_messages'] = messages
    before = deepcopy(current)
    phases = []
    bundle = compose(current, phases, Broker())
    summary, = bundle['request']['context']['prepared_partitions']
    assert summary['context'] == ' 🌱 e\u0301。\n我不记得年份。 \n\n父亲说是1984年，但我不确定。'
    assert summary['source_refs'] == summary_partition(current)['source_refs']
    assert phases == ['draft', 'review']
    assert current == before


@pytest.mark.parametrize('length,phases', [(4000, ['draft', 'review']), (4001, ['prepare', 'draft', 'review'])])
def test_original_character_limit_is_inclusive_and_never_truncates(length, phases):
    current = batch_page()
    messages = deepcopy(current['batch']['new_messages'][:2])
    for source, text in zip(messages, ['🌱' * 2000, '忆' * (length - 2002)]):
        source.update(text=text, char_start=0, char_end=len(text), original_length=len(text))
    current['batch']['new_messages'] = messages
    observed = []
    bundle = compose(current, observed, Broker())
    summary, = bundle['request']['context']['prepared_partitions']
    assert observed == phases
    assert summary['source_refs'] == summary_partition(current)['source_refs']
    if length == 4000:
        assert len(summary['context']) == 4000
        assert summary['context'].startswith('🌱' * 2000 + '\n\n')
        assert summary['context'].endswith('忆' * 1998)
    else:
        assert summary['context'] == 'New bicycle memories, with their original evidence.'


@pytest.mark.parametrize('change', ['family', 'partial_window'])
def test_context_needing_attribution_or_window_interpretation_retains_preparation(change):
    current = batch_page()
    current['batch']['new_messages'] = deepcopy(current['batch']['new_messages'])
    source = current['batch']['new_messages'][0]
    if change == 'family':
        source.update(id=str(UUID(int=90)), author_role='family_contributor')
    else:
        source.update(char_start=1, char_end=len(source['text']) + 1, original_length=len(source['text']) + 2)
    phases = []
    bundle = compose(current, phases, Broker())
    assert bundle['status'] == 'ready'
    assert phases == ['prepare', 'draft', 'review']


def test_incomplete_privacy_cannot_use_lossless_preparation_to_reach_a_model():
    current = batch_page()
    current['preferences']['privacy_complete'] = False
    phases = []
    with pytest.raises(ValueError, match='[Pp]rivacy'):
        compose(current, phases, Broker())
    assert phases == []


def test_generation_pause_prevents_registering_new_preparation(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED', 'true')
    current = batch_page()
    recorded = []

    class RecordingBroker(Broker):
        async def rpc(self, name, **payload):
            if name == 'record_lifetime_lane_output':
                recorded.append(payload)
            return await super().rpc(name, **payload)

    from apps.api.lifetime_memory_lane_engine import LaneGenerationPaused
    phases = []
    with pytest.raises(LaneGenerationPaused):
        compose(current, phases, RecordingBroker())
    assert phases == []
    assert recorded == []


def test_empty_checkpoint_never_invents_preparation_or_prose():
    current = batch_page()
    current['batch'].update(sources=[], events=[], new_messages=[])
    current.update(source=None, partition=None)
    phases = []
    result = compose(current, phases, Broker())
    assert result == {'status': 'insufficient_context', 'preview': None, 'summary': None}
    assert phases == []


def test_five_short_originals_need_only_draft_and_review():
    current = batch_page()
    before = deepcopy(current)
    phases = []
    bundle = compose(current, phases, Broker())
    assert bundle['status'] == 'ready'
    assert phases == ['draft', 'review']
    assert current == before
    assert len(bundle['request']['context']['prepared_partitions']) == 1
    assert bundle['request']['context']['checkpoint_delta'] == {'starting_after': 0, 'through_source': 5}
    for e in current['batch']['events']:
        assert any(e['id'] in s['event_ids'] for s in bundle['sections'])


def test_twenty_round_backlog_summarizes_latest_messages_while_drafting_earlier_evidence():
    current = batch_page()
    current.update(source_high_water=20, coverage_round=20)
    current['batch']['starting_after'] = 15
    current['batch']['new_messages'] = deepcopy(current['batch']['new_messages'])
    for index, source in enumerate(current['batch']['new_messages']):
        source.update(id=str(UUID(int=100 + index)), sequence=16 + index)
    phases = []
    bundle = compose(current, phases, Broker())
    assert bundle['status'] == 'ready'
    assert phases == ['draft', 'review']
    assert bundle['request']['context']['checkpoint_delta'] == {'starting_after': 15, 'through_source': 5}


def test_first_chapter_after_empty_checkpoints_starts_at_chapter_revision_zero():
    current = batch_page()
    current['base_revision'] = 5
    phases = []
    bundle = compose(current, phases, Broker())
    assert bundle['status'] == 'ready'
    assert bundle['request']['prior_state']['revision'] == 5
    assert bundle['draft']['chapters'][0]['base_revision'] == 0
    assert phases == ['draft', 'review']


def test_draft_schema_rejects_a_source_that_only_appears_in_the_message_summary():
    from jsonschema import Draft202012Validator
    from apps.api.lifetime_memory_lane_engine import LaneFence, lane_contract
    current = batch_page()
    current['batch']['new_messages'] = [{**current['batch']['sources'][0], 'id': str(UUID(int=100))}]
    fence = LaneFence.model_validate({key: current[key] for key in LaneFence.model_fields if key in current})
    _, schema = lane_contract('draft', current['locale'], batch=True, fence=fence)
    reference_schema = schema['$defs']['ref']
    ref=current['batch']['events'][0]['source_refs'][0]
    valid = {key:ref[key] for key in ('source_id','char_start','char_end')}
    valid['version']=str(ref['version'])
    validator = Draft202012Validator(reference_schema)
    validator.validate(valid)
    invalid = {**valid, 'source_id': current['batch']['new_messages'][0]['id']}
    assert not validator.is_valid(invalid)


def test_draft_schema_cannot_join_separate_canonical_evidence_spans():
    from jsonschema import Draft202012Validator
    from apps.api.lifetime_memory_lane_engine import LaneFence, lane_contract
    current=batch_page()
    event=current['batch']['events'][0]
    first={**event['source_refs'][0],'char_start':0,'char_end':2,'quote':current['batch']['sources'][0]['text'][:2]}
    second={**first,'char_start':3,'char_end':5,'quote':current['batch']['sources'][0]['text'][3:5]}
    event['source_refs']=[first,second]
    fence=LaneFence.model_validate({key:current[key] for key in LaneFence.model_fields if key in current})
    _,schema=lane_contract('draft',current['locale'],batch=True,fence=fence)
    validator=Draft202012Validator(schema['$defs']['ref'])
    references=[{**{key:ref[key] for key in ('source_id','char_start','char_end')},'version':str(ref['version'])} for ref in (first,second)]
    for ref in references:validator.validate(ref)
    assert not validator.is_valid({**references[0],'char_end':second['char_end']})
    assert not validator.is_valid({**references[0],'char_start':None,'char_end':None})


def test_pg_off_cadence_revision_does_not_consume_the_next_five_round_summary(sql):  # noqa: F811
    identity=resolve(sql);project=identity['project_id']
    def add(first,last):
        for i in range(first,last+1):
            rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{UUID(int=i)}',{literal('Original round '+str(i))}")
        sql("update public.user_narrator_source set processing_status='succeeded';")
    def finish_fixture(claim):
        sql(f"update public.user_lifetime_lane_snapshot set state='completed' where id='{claim['snapshot_id']}'; "
            f"update public.user_memoir_lane set token=null,lease_until=null,run_deadline=null,pending=true,available_at=clock_timestamp() where id='{lane}';")
    add(1,5);lane=create_lane(sql,identity,'composer',5)
    first=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert len(first['batch']['new_messages'])==5
    finish_fixture(first);add(6,8)
    sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) select '{OWNER}',{literal(project)},client_turn_id,sequence from public.user_narrator_source where user_id='{OWNER}' and project_id={literal(project)} and sequence between 6 and 8;")
    partial=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert partial['coverage_round']==8 and partial['source_high_water']==8
    assert sql(f"select milestone from public.user_lifetime_lane_snapshot where id='{partial['snapshot_id']}';").stdout.strip()=='5'
    assert partial['batch']['new_messages']==[]
    finish_fixture(partial);add(9,10)
    sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) select '{OWNER}',{literal(project)},client_turn_id,sequence from public.user_narrator_source where user_id='{OWNER}' and project_id={literal(project)} and sequence between 9 and 10; "
        f"update public.user_memoir_lane set target_milestone=10 where id='{lane}';")
    final=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert [s['sequence'] for s in final['batch']['new_messages']]==list(range(6,11))
    assert final['batch']['starting_after']==5
    originals=sql('select jsonb_agg(to_jsonb(s) order by sequence) from public.user_narrator_source s;').stdout
    finish_fixture(final)
    sql(f"update public.user_lifetime_lane_snapshot set state='stale' where id='{final['snapshot_id']}'; "
        f"update public.user_memoir_lane set attempts=0 where id='{lane}';")
    repaired=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert repaired['snapshot_id']!=final['snapshot_id']
    assert [s['sequence'] for s in repaired['batch']['new_messages']]==list(range(6,11))
    assert sql('select jsonb_agg(to_jsonb(s) order by sequence) from public.user_narrator_source s;').stdout==originals


def test_second_checkpoint_keeps_unchanged_prose_and_uses_only_the_new_messages_for_summary():
    current = batch_page()
    first = compose(current, [], Broker())
    current = deepcopy(current)
    current.update(page_number=4, coverage_round=10, base_revision=1)
    current['batch']['previous'] = first
    current['batch']['starting_after'] = 5
    current['batch']['through_source'] = 10
    current['batch']['new_messages'] = [{**s, 'id': str(UUID(int=80 + i)), 'sequence': i + 6,
        'text': 'Later I taught a neighbour to repair bicycles.', 'char_start': 0, 'char_end': 45, 'original_length': 45}
        for i, s in enumerate(current['batch']['sources'])]
    for s in current['batch']['new_messages']:
        s['char_end'] = s['original_length'] = len(s['text'])
    added = current['batch']['new_messages'][0]
    current['batch']['sources'].append(added)
    current['batch']['events'][0]['revision'] = 2
    current['batch']['events'][0]['source_refs'].append(dict(source_id=added['id'], version=1, quote=added['text'],
        char_start=0, char_end=len(added['text'])))
    phases = []
    second = compose(current, phases, Broker(), mutate_unchanged=True)
    assert phases == ['draft', 'review']
    old_blocks = first['manuscript']['chapters'][0]['blocks']
    new_blocks = second['manuscript']['chapters'][0]['blocks']
    assert {b['id']: b for b in new_blocks[1:]} == {b['id']: b for b in old_blocks[1:]}
    assert 'neighbour' in new_blocks[0]['text']
    assert summary_partition(current)['source_refs'][0]['source_id'] == current['batch']['new_messages'][0]['id']
    assert second['request']['prior_state']['revision'] == 1


def test_multiple_stored_sample_chapters_supply_one_bounded_prior_body_without_rewriting_text():
    from apps.api.progressive_composer import batch_job
    from apps.api.canonical_composer import composition_request
    current=batch_page()
    first=compose(current,[],Broker())
    current['batch']['previous']=deepcopy(first)
    current['batch']['previous'].pop('manuscript')
    current['batch']['previous']['kind']='sample_chapter'
    blocks=[s for s in current['batch']['previous']['sections'] if 'block' in s]
    for index,section in enumerate(blocks):
        section['chapter_id']='stored-sample-'+str(index)
        section['block']['id']='paragraph'
    before=deepcopy(current)
    request,_=composition_request(batch_job(current))
    chapters=request['prior_state']['chapters']
    assert len(chapters)==1
    body=chapters[0]['chapter']['blocks']
    assert [b['text'] for b in body]==[s['block']['text'] for s in blocks]
    assert len({b['id'] for b in body})==len(body)
    assert current==before


def test_repair_admission_and_composer_share_stale_projection_validation(monkeypatch):
    from apps.api.canonical_composer import validate_canonical_candidate
    from apps.api.lifetime_memory_lane_engine import validate_lane_payload
    request = {'snapshot': {'id': 'snapshot'}, 'prior_state': {'revision': 1},
        'context': {'projection_invalidated_chapter_ids': ['chapter'], 'prepared_partitions': []}}
    candidate = {'carry_forward_chapter_ids': ['chapter']}
    plan = {'ready': True}
    async def operation(phase, *args):
        return deepcopy(plan if phase == 'plan' else {'ok': True, 'errors': []})
    monkeypatch.setattr('apps.api.memoir_preview.skill_operation', operation)
    monkeypatch.setattr('apps.api.canonical_composer.canonical_evidence_errors', lambda *args: [])
    monkeypatch.setattr('apps.api.lifetime_memory_lane_engine.canonical_lane_request', lambda *args: deepcopy(request))
    validation = asyncio.run(validate_canonical_candidate(request, candidate))
    assert validation['errors'][0]['code'] == 'STALE_CANONICAL_PROJECTION'
    bounded = SimpleNamespace(phase='draft', fence=SimpleNamespace(batch={}),
        packet=json.dumps({'payload': {'request':request, 'plan':plan, 'candidate':candidate,'validation':validation}}))
    asyncio.run(validate_lane_payload(bounded))
    # An incomplete proof still cannot enter the worker.
    data = json.loads(bounded.packet)
    data['payload']['validation'] = {'ok': True, 'errors': []}
    bounded.packet = json.dumps(data)
    with pytest.raises(ValueError, match='canonical page proof'):
        asyncio.run(validate_lane_payload(bounded))


def test_canonical_repair_errors_are_stable_after_transport_key_sorting():
    from apps.api.canonical_composer import canonical_evidence_errors
    ref={'source_id':'source','version':'1','char_start':3,'char_end':8}
    request={'sources':[{'id':'source','version':'1','text':'Original memory.'}],
        'events':[{'id':'event','source_refs':[{**ref,'char_start':0,'char_end':3}]}],
        'prior_state':{'chapters':[]},'context':{}}
    draft={'outline':[{'source_refs':[ref]}],'chapters':[{'source_refs':[ref]}],
        'carry_forward_chapter_ids':[]}
    before=canonical_evidence_errors(request,draft)
    after=canonical_evidence_errors(request,json.loads(json.dumps(draft,sort_keys=True)))
    assert before and before==after


@pytest.mark.parametrize('protected', [False, True])
def test_pg_five_round_batch_groups_quotes_and_persists_progressive_passages(sql, protected):  # noqa: F811 - fixture
    identity = resolve(sql)
    project = identity['project_id']
    originals = []
    for i in range(5):
        text = f'I repaired bicycle {i + 1} in our shed.'
        original = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{UUID(int=100+i)}',{literal(text)}")
        originals.append(original)
        event = dict(kind='event', title=text, life_stage='childhood', stage_evidence=[dict(source_id=original['id'], version=1, quote=text)],
                     source_refs=[dict(source_id=original['id'], version=1, quote=text)])
        rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([dict(id=original['id'],version=1)])},{literal([event])}")
    lane = create_lane(sql, identity, skill='composer', rounds=5)
    current = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert len(current['batch']['new_messages']) == 5
    assert len(current['batch']['events']) == 5
    assert current['batch']['starting_after'] == 0
    class NativeBroker:
        async def rpc(self, name, **payload):
            args = ','.join(f'{k}=>{literal(v)}' for k, v in payload.items())
            return json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null');").stdout.strip())
    broker = NativeBroker()
    phases = []
    bundle = compose(current, phases, broker)
    assert phases == ['draft', 'review']
    saved = service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{current['token']}',0,{literal(bundle)}")
    assert saved['status'] == 'page_saved'
    tail = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{current['token']}'")
    assert tail['complete']
    done = service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{current['token']}'")
    assert done['pages'] == 1 and done['retrieval_complete']
    assert sql('select count(*) from public.user_lifetime_memoir_section;').stdout.strip() == '5'
    head = rpc(sql, 'read_lifetime_private_draft_head', f"{literal(project)},'en-AU'")
    assert head['status'] == 'ready' and head['coverage_round'] == 5
    assert head['preview']['text']
    initial = {section['id']: section['preview']['text'] for section in
        rpc(sql, 'read_lifetime_private_draft_page', f"{literal(project)},'{head['snapshot_id']}',null,8")['records']}
    saved_events = rpc(sql, 'read_user_memory_events', literal(project))['events']
    target = next(e for e in saved_events if e['source_refs'][0]['source_id'] == originals[0]['id'])
    if protected:
        sql(f"update public.user_lifetime_memoir_section set approved=true where source_id='{originals[0]['id']}';")
    for i in range(5):
        text = 'Later I taught a neighbour to repair bicycles.' if i == 0 else 'Thank you.'
        original = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{UUID(int=200+i)}',{literal(text)}")
        changes = []
        if i == 0:
            changes = [dict(existing_id=target['id'], expected_revision=target['revision'], kind='event', title='Bicycle repairs and teaching',
                life_stage='childhood', stage_evidence=[dict(source_id=originals[0]['id'],version=1,quote=originals[0]['text'])],
                source_refs=[dict(source_id=originals[0]['id'],version=1,quote=originals[0]['text']),dict(source_id=original['id'], version=1, quote=text)])]
        manifest = [dict(id=original['id'],version=1)] + ([dict(id=originals[0]['id'],version=1)] if i == 0 else [])
        rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal(manifest)},{literal(changes)}")
    sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) select '{OWNER}',{literal(project)},client_turn_id,sequence from public.user_narrator_source where user_id='{OWNER}' and project_id={literal(project)} and sequence between 6 and 10;")
    sql(f"update public.user_memoir_lane set pending=true,target_milestone=10,target_event=(select event_sequence from public.user_memoir_project where user_id='{OWNER}' and project_id={literal(project)}) where id='{lane}';")
    current = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert current['batch']['starting_after'] == 5
    assert len(current['batch']['new_messages']) == 5
    assert current['batch']['previous'] is not None
    phases = []
    bundle = compose(current, phases, broker, mutate_unchanged=True)
    assert phases == ['draft', 'review']
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{current['token']}',0,{literal(bundle)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{current['token']}'")
    updated = rpc(sql, 'read_lifetime_private_draft_head', f"{literal(project)},'en-AU'")
    records = rpc(sql, 'read_lifetime_private_draft_page', f"{literal(project)},'{updated['snapshot_id']}',null,8")['records']
    final = {s['id']: (s['preview'] or s['proposed_preview'])['text'] for s in records}
    assert len(final) == len(initial) == 5
    changed = next(key for key, text in initial.items() if 'bicycle 1' in text)
    if protected:
        assert final[changed] == initial[changed]
        assert 'neighbour' in next(s['proposed_preview']['text'] for s in records if s['id'] == changed)
    else:
        assert 'neighbour' in final[changed]
    assert {k: v for k, v in final.items() if k != changed} == {k: v for k, v in initial.items() if k != changed}
    assert len(next(s['source_refs'] for s in records if s['id'] == changed)) == (1 if protected else 2)
    if protected:
        refs = json.loads(sql(f"select proposal->'source_refs' from public.user_lifetime_memoir_section where partition_key={literal(changed)} and snapshot_id='{updated['snapshot_id']}';").stdout.strip())
        assert len(refs) == 2
    # Secondary evidence, rather than only the leading source, participates in
    # withdrawal cleanup. Original narrator rows were never rewritten by compose.
    assert rpc(sql, 'read_user_memory_events', literal(project))['sources'][0]['text'] == originals[0]['text']
    secondary = current['batch']['new_messages'][0]['id']
    sql(f"update public.user_narrator_source set status='withdrawn' where id='{secondary}';")
    assert sql(f"select count(*) from public.user_lifetime_memoir_section where partition_key={literal(changed)} and snapshot_id='{updated['snapshot_id']}';").stdout.strip() == '0'


def test_pg_long_original_summary_resumes_exact_windows_and_cannot_skip_proof(sql):  # noqa: F811
    identity = resolve(sql)
    project = identity['project_id']
    text = 'Original testimony. ' * 260
    rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{UUID(int=300)}',{literal(text)}")
    # The background extraction lane completed without proposing an event.
    sql("update public.user_narrator_source set processing_status='succeeded';")
    lane = create_lane(sql, identity, skill='composer', rounds=5)
    current = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    digest = current['page_digest']
    failure = sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane}','{current['token']}',0,'{{\"status\":\"insufficient_context\"}}',{literal(digest)});", check=False)
    assert failure.returncode != 0 and 'saved background summary' in failure.stderr
    tampered = deepcopy(current)
    tampered['batch']['new_messages'][0]['text'] = 'Forged evidence'
    failure = sql(f"set role service_role;select public.lock_lifetime_memoir_lane_publication({literal(tampered)});", check=False)
    assert failure.returncode != 0 and 'stale progressive authority' in failure.stderr
    class NativeBroker:
        async def rpc(self, name, **payload):
            args = ','.join(f'{k}=>{literal(v)}' for k, v in payload.items())
            return json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null');").stdout.strip())
    windows = []
    number = 0
    while not current['complete']:
        original = current['batch']['new_messages'][0]
        assert original['text'] == text[original['char_start']:original['char_end']]
        windows.append(original['text'])
        phases = []
        bundle = compose(current, phases, NativeBroker())
        assert bundle['status'] == 'insufficient_context' and phases == ['prepare']
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{current['token']}',{number},{literal(bundle)}")
        number += 1
        current = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{current['token']}'")
    assert ''.join(windows) == text and number == 3
    assert service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{current['token']}'")['retrieval_complete']


@pytest.mark.parametrize('reason,seconds',[('LIFETIME_PROVIDER_AUTHORITY_UNAVAILABLE',15),('LIFETIME_GENERATION_PAUSED',300)])
def test_pg_transient_authority_retry_keeps_originals_and_snapshot_cursor(sql,reason,seconds):  # noqa: F811
    identity=resolve(sql)
    original=rpc(sql,'accept_user_narrator_source',f"{literal(identity['project_id'])},'{UUID(int=400)}','Exact original testimony.'")
    lane=create_lane(sql,identity)
    current=service(sql,'claim_memoir_lane',f"'{lane}',900")
    result=service(sql,'defer_lifetime_memoir_lane',f"'{lane}','{current['token']}',{literal(reason)}")
    assert result['status']=='pending' and result['retrieval_complete'] is False
    delay=float(sql(f"select extract(epoch from available_at-clock_timestamp()) from public.user_memoir_lane where id='{lane}';").stdout.strip())
    assert seconds-3<delay<=seconds
    assert sql(f"select page_number from public.user_lifetime_lane_snapshot where id='{current['snapshot_id']}';").stdout.strip()=='0'
    assert rpc(sql,'read_user_memory_events',literal(identity['project_id']))['sources'][0]['text']==original['text']
