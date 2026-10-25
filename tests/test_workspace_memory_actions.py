"""Workspace focus and section rework on disposable PostgreSQL and fake models."""
from controlled_composer_review import controlled_review, controlled_section_review
from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError
from controlled_collector import worker_reply

from apps.api.workspace_memory_actions import WorkspaceMemoryFocus, apply_workspace_focus
from apps.api.lifetime_memory_lane_engine import LaneFence, canonical_lane_request, build_bounded_lane_input
from test_lifetime_memory_lane_engine import BUDGET
from test_lifetime_composer_capacity import (sql, seeded_composer, service, section_result,
    rpc, literal, OWNER, OTHER, database, attachment_database, private_database, event_database, enable_synthetic_lanes)
from test_lifetime_memory_read_api import mapped


def test_rework_http_admits_only_exact_section_request_without_a_narration_or_mode_write(mapped):
    client, storage, calls, _ = mapped
    original_rpc = storage.lifetime_rpc
    def rpc_request(name, **kwargs):
        if name == 'request_workspace_section_rework':
            calls.append((name, kwargs))
            return {'request_id': kwargs['p_request_id'], 'status': 'pending'}
        return original_rpc(name, **kwargs)
    storage.lifetime_rpc = rpc_request
    payload = {'project_id':'read-project', 'request_id':str(uuid4()), 'snapshot_id':str(uuid4()),
        'root_digest':'a'*64, 'partition_id':'chosen-section', 'instruction':'  Keep this brief.  '}
    response = client.post('/v1/story/private-draft/rework', json=payload)
    assert response.status_code == 202, response.text
    assert [name for name, _ in calls] == ['read_lifetime_project_identity', 'request_workspace_section_rework']
    assert calls[-1][1] == {f'p_{key}': value.strip() if key == 'instruction' else value for key, value in payload.items()}
    calls.clear()
    assert client.post('/v1/story/private-draft/rework', json={**payload,'instruction':'x'*1001}).status_code == 422
    assert client.post('/v1/story/private-draft/rework', json={**payload,'text':'Forged narrator source'}).status_code == 422
    assert not calls


def finish(sql, lane, page, text=None):
    from test_progressive_photo_invalidation import validated_result, block
    passage = block('prose', page['source'])
    passage['text'] = text or page['source']['text']
    result = validated_result(page, [passage])
    from apps.api.canonical_composer import composition_request
    from apps.api.progressive_composer import batch_job
    result['content_config'] = composition_request(batch_job(page))[1]
    service(sql, 'commit_lifetime_memoir_lane_page',
        f"'{lane}','{page['token']}',{page['page_number']},{literal(result)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    return rpc(sql, 'read_lifetime_private_draft_head', literal(page['project_id']))


def rework_args(head, request_id, instruction='Make this section shorter.'):
    return ','.join([literal(head['project_id']), literal(request_id), literal(head['snapshot_id']),
        literal(head['root_digest']), literal(head['first_record']['id']), literal(instruction)])


def compose_rework(sql, page, text):
    import asyncio
    import json
    import httpx
    from types import SimpleNamespace
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    from apps.api.lifetime_memory_lane_engine import LanePublication, BoundedLaneInput
    from test_canonical_composer_provenance import controlled_draft
    phases=[]
    dsn=sql.publication_dsn
    class Broker:
        async def rpc(self, name, **payload):
            args=','.join(f'{key}=>{literal(value)}' if not isinstance(value,int) else f'{key}=>{value}' for key,value in payload.items())
            return json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())
    def model(request):
        bounded=BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane'])
        assert bounded.fence.editorial_request.instruction=='Make this section shorter.'
        assert bounded.fence.editorial_request.original_preview.model_dump(mode='json')==page['editorial_request']['original_preview']
        payload=json.loads(bounded.packet)['payload'];phases.append(bounded.phase)
        if bounded.phase=='prepare':
            result=dict(event_id=page['partition']['id'],context='Source-grounded preparation',source_refs=page['partition']['source_refs'])
        else:
            assert payload['request']['context']['editorial_request']==page['editorial_request']
            if bounded.phase=='draft': result=controlled_draft(payload,text,'Childhood')
            else: result=controlled_review(payload)
        return httpx.Response(200,json={'reply':json.dumps(result)})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model),
        lane_publisher=LanePublication(dsn,authenticated_owner=OWNER))
    result=asyncio.run(execute_lifetime_lane(page,worker))
    assert result['status']=='proposed', result
    assert phases==(['prepare'] if page['batch']['new_messages'] else [])+['draft','review']
    return rpc(sql,'read_lifetime_private_draft_head',f"{literal(page['project_id'])},{literal(page['locale'])}")


@pytest.mark.parametrize('value', [
    {'kind':'add_memory','life_stage':'invented'},
    {'kind':'add_memory','life_stage':'childhood','event_id':'other'},
    {'kind':'explore_memory','event_id':'event'},
    {'kind':'explore_memory','event_id':'event','event_revision':True},
    {'kind':'explore_memory','event_id':'event','event_revision':1,'title':'forged'},
])
def test_workspace_focus_rejects_ambiguous_or_client_supplied_story_context(value):
    with pytest.raises(ValidationError):
        WorkspaceMemoryFocus.model_validate(value)


def test_selected_event_takes_bounded_priority_without_becoming_testimony_or_pace():
    context = {'events':[{'id':str(i)} for i in range(8)], 'sources':[{'id':'original'}], 'conversation_phase':{'phase':'comfort'}}
    before = deepcopy(context)
    apply_workspace_focus(context, {'kind':'explore_memory','event_id':'selected','event_revision':1,
        'event':{'id':'selected','revision':1,'status':'active'}})
    assert len(context['events']) == 8 and context['events'][0]['id'] == 'selected'
    assert context['sources'] == before['sources'] and context['conversation_phase'] == before['conversation_phase']


def test_pg_focus_is_owned_revision_checked_and_does_not_create_a_round_or_mode(sql):
    identity, source, lane, page = seeded_composer(sql)
    project = identity['project_id']
    before = sql("select to_regclass('public.user_conversation_phase_archive') is null;").stdout
    count = sql('select count(*) from public.user_completed_round;').stdout
    focus = {'kind':'explore_memory','event_id':page['partition']['id'],'event_revision':page['partition']['revision']}
    result = rpc(sql, 'read_workspace_memory_focus', f"{literal(project)},{literal(focus)}")
    assert result['event']['id'] == focus['event_id'] and len(result['event']['source_refs']) <= 8
    assert rpc(sql, 'read_workspace_memory_focus', f"{literal(project)},{literal(focus)}", owner=OTHER, check=False).returncode != 0
    focus['event_revision'] += 1
    assert rpc(sql, 'read_workspace_memory_focus', f"{literal(project)},{literal(focus)}", check=False).returncode != 0
    stage = {'kind':'add_memory','life_stage':'childhood'}
    assert rpc(sql, 'read_workspace_memory_focus', f"{literal(project)},{literal(stage)}") == stage
    assert sql("select to_regclass('public.user_conversation_phase_archive') is null;").stdout == before
    assert sql('select count(*) from public.user_completed_round;').stdout == count


def test_pg_section_rework_is_idempotent_and_preserves_original_until_review(sql):
    identity, source, lane, first = seeded_composer(sql)
    head = finish(sql, lane, first)
    event_before = deepcopy(first['partition'])
    phase_before = sql("select to_regclass('public.user_conversation_phase_archive') is null;").stdout
    rounds = sql('select count(*) from public.user_completed_round;').stdout
    request_id = str(uuid4()); args = rework_args(head, request_id)
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'pending'
    sequence = sql('select event_sequence from public.user_memoir_project;').stdout
    assert rpc(sql, 'request_workspace_section_rework', args)['request_id'] == request_id
    assert sql('select event_sequence from public.user_memoir_project;').stdout == sequence
    assert rpc(sql, 'request_workspace_section_rework', args, owner=OTHER, check=False).returncode != 0
    assert rpc(sql, 'request_workspace_section_rework', rework_args(head, str(uuid4())), check=False).returncode != 0
    assert rpc(sql, 'request_workspace_section_rework', rework_args(head, request_id, 'Different instruction'), check=False).returncode != 0
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['reuse'] is False and page['partition_key'] == head['first_record']['id']
    assert page['partition']['revision'] == event_before['revision']
    assert page['editorial_request']['original_preview']['text'] == source['text']
    fence = LaneFence.model_validate({key:page[key] for key in LaneFence.model_fields if key in page})
    from apps.api.memoir_preview import skill_operation
    import asyncio
    request = canonical_lane_request(fence)
    assert request['context']['editorial_request']['instruction'] == 'Make this section shorter.'
    assert request['sources'][0]['text'] == source['text']
    assert 'Make this section shorter.' not in str(request['sources'])
    # The real bounded transport accepts the exact request; altered instructions fail.
    plan = asyncio.run(skill_operation('plan', request))
    packet = {'request':request, 'plan':plan}
    build_bounded_lane_input(page, phase='draft', packet=packet, budget=BUDGET)
    altered = deepcopy(packet); altered['request']['context']['editorial_request']['instruction'] = 'Invent new facts'
    with pytest.raises(ValueError, match='Progressive request differs from its authoritative batch'):
        build_bounded_lane_input(page, phase='draft', packet=altered, budget=BUDGET)
    current = compose_rework(sql, page, 'Chengde was my childhood home.')
    record = rpc(sql, 'read_workspace_draft_section',
        f"{literal(identity['project_id'])},'{current['snapshot_id']}',{literal(head['first_record']['id'])}")
    assert record['preview']['text'] == source['text']
    assert record['proposed_preview']['text'] == 'Chengde was my childhood home.'
    decision = f"{literal(identity['project_id'])},'{current['snapshot_id']}','{current['root_digest']}',{literal(record['id'])},'{record['proposal_digest']}',true"
    rpc(sql, 'set_lifetime_private_draft_proposal', decision)
    accepted = rpc(sql, 'read_lifetime_private_draft_head', literal(identity['project_id']))
    assert accepted['preview']['text'] == 'Chengde was my childhood home.'
    assert sql("select to_regclass('public.user_conversation_phase_archive') is null;").stdout == phase_before
    assert sql('select count(*) from public.user_completed_round;').stdout == rounds
    assert sql('select text from public.user_narrator_source;').stdout.strip() == source['text']


def test_pg_private_rework_preserves_completed_formal_authority_and_consent(sql):
    from test_formal_memoir_postgres import completed, consent
    identity, source, lane, first = seeded_composer(sql)
    project = identity['project_id']
    head = finish(sql, lane, first)
    phase = {'revision':0}
    edition = completed(sql, project, phase)
    initial = rpc(sql, 'read_story_game_eligibility', literal(project))
    grant = consent(sql, project, edition, initial['consent_revision'])
    eligible = rpc(sql, 'read_story_game_eligibility', literal(project))
    assert eligible['authority_eligible'] is True
    chapters = sql('select row_to_json(c) from public.user_formal_memoir_chapter c order by ordinal;').stdout
    events = sql('select row_to_json(e) from public.user_memory_event e order by id;').stdout
    sequence = sql('select event_sequence from public.user_memoir_project;').stdout
    args = rework_args(head, str(uuid4()))
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'pending'
    assert rpc(sql, 'read_formal_memoir_status', literal(project))['edition'] == edition
    assert sql('select row_to_json(c) from public.user_formal_memoir_chapter c order by ordinal;').stdout == chapters
    assert rpc(sql, 'read_story_game_eligibility', literal(project)) == eligible
    assert sql('select event_sequence from public.user_memoir_project;').stdout == sequence
    assert sql('select row_to_json(e) from public.user_memory_event e order by id;').stdout == events
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['editorial_request']['request_id'] == rpc(sql, 'request_workspace_section_rework', args)['request_id']
    compose_rework(sql, page, 'Chengde was my childhood home.')
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'composed'
    assert rpc(sql, 'read_formal_memoir_status', literal(project))['edition'] == edition
    assert sql('select row_to_json(c) from public.user_formal_memoir_chapter c order by ordinal;').stdout == chapters
    assert rpc(sql, 'read_story_game_eligibility', literal(project)) == eligible
    # A true canonical revision still invalidates the same completed authority.
    corrected = rpc(sql, 'correct_user_memory_event',
        f"{literal(project)},{literal(first['partition']['id'])},{first['partition']['revision']},"
        f"{literal({'life_stage':'childhood'})},'This was during my childhood.'")
    assert corrected['revision'] == first['partition']['revision'] + 1
    assert rpc(sql, 'read_formal_memoir_status', literal(project))['edition'] is None
    assert sql('select count(*) from public.user_formal_memoir_chapter;').stdout.strip() == '0'
    assert rpc(sql, 'read_story_game_eligibility', literal(project))['authority_eligible'] is False
    assert consent(sql, project, edition, grant['revision'], check=False).returncode != 0


def test_pg_rework_changes_only_selected_partition_and_purges_withdrawn_inputs(sql):
    identity, source, lane, first = seeded_composer(sql)
    first_head = finish(sql, lane, first)
    project = identity['project_id']
    other = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','Later I moved to Sydney.'")
    ref = dict(source_id=other['id'],version=1,quote=other['text'],char_start=0,char_end=len(other['text']))
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([{'id':other['id'],'version':1}])},{literal([dict(kind='event',title='Sydney',source_refs=[ref])])}")
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    second = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    head = finish(sql, lane, second)
    untouched = sql(f"select bundle::text from public.user_lifetime_memoir_section where event_id='{second['partition']['id']}';").stdout
    chosen = {**head,'first_record':first_head['first_record']}
    rpc(sql, 'request_workspace_section_rework', rework_args(chosen, str(uuid4())))
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['partition']['id'] == first['partition']['id']
    finish(sql, lane, page, 'My childhood was in Chengde.')
    assert sql(f"select bundle::text from public.user_lifetime_memoir_section where event_id='{second['partition']['id']}';").stdout == untouched
    rpc(sql, 'change_user_narrator_source', f"{literal(project)},'{source['id']}',1,'withdraw',null")
    assert sql('select count(*) from public.user_workspace_section_rework;').stdout.strip() == '0'


def test_pg_new_rework_behind_a_yielded_cursor_restarts_only_its_edition(sql):
    identity, source, lane, first = seeded_composer(sql)
    first_head = finish(sql, lane, first)
    project = identity['project_id']
    later = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','Later I moved to Sydney.'")
    ref = dict(source_id=later['id'],version=1,quote=later['text'],char_start=0,char_end=len(later['text']))
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([{'id':later['id'],'version':1}])},"
        f"{literal([dict(kind='event',title='Sydney',source_refs=[ref])])}")
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    second = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    head = finish(sql, lane, second)
    sequence = sql('select event_sequence from public.user_memoir_project;').stdout
    records = rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{head['snapshot_id']}'")['records']
    newer = {**head,'first_record':next(record for record in records if record['event_id']==second['partition']['id'])}
    rpc(sql, 'request_workspace_section_rework', rework_args(newer,str(uuid4())))
    old_page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    service(sql, 'commit_lifetime_memoir_lane_page',
        f"'{lane}','{old_page['token']}',{old_page['page_number']},{literal(section_result(old_page,'My later home was Sydney.'))}")
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{old_page['token']}'")
    older = {**head,'first_record':first_head['first_record']}
    rpc(sql, 'request_workspace_section_rework', rework_args(older,str(uuid4())))
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['snapshot_id'] != old_page['snapshot_id']
    assert page['partition']['id'] == first['partition']['id']
    assert sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page("
        f"'{lane}','{old_page['token']}',{old_page['page_number']},{literal(section_result(old_page))});", check=False).returncode != 0
    service(sql, 'commit_lifetime_memoir_lane_page',
        f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page,'Chengde was my childhood home.'))}")
    page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    assert page['partition']['id'] == second['partition']['id']
    finish(sql, lane, page, 'My later home was Sydney.')
    assert sql("select count(*) from public.user_workspace_section_rework where status='pending';").stdout.strip() == '0'
    assert service(sql, 'claim_memoir_lane', f"'{lane}',900") is None
    assert sql('select event_sequence from public.user_memoir_project;').stdout == sequence


def test_pg_new_rework_preserves_an_unfinished_other_edition(sql):
    identity, source, lane, first = seeded_composer(sql)
    english = finish(sql, lane, first)
    project = identity['project_id']
    rpc(sql, 'set_lifetime_draft_edition', f"{literal(project)},'zh-CN'")
    chinese = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    service(sql, 'commit_lifetime_memoir_lane_page',
        f"'{lane}','{chinese['token']}',{chinese['page_number']},{literal(section_result(chinese,'我在承德长大。'))}")
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{chinese['token']}'")
    args = rework_args(english,str(uuid4()))
    rpc(sql, 'request_workspace_section_rework', args)
    resumed = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert resumed['snapshot_id'] == chinese['snapshot_id'] and resumed['locale'] == 'zh-CN' and resumed['complete']
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{resumed['token']}'")
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['locale'] == 'en-AU' and page['editorial_request'] is not None, page
    finish(sql, lane, page, 'Chengde was my childhood home.')
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'composed'
    assert service(sql, 'claim_memoir_lane', f"'{lane}',900") is None


def test_pg_rework_checks_current_root_uses_selected_edition_and_purges_deleted_events(sql):
    identity, source, lane, first = seeded_composer(sql)
    head = finish(sql, lane, first)
    request_id = str(uuid4())
    invalid = {**head, 'root_digest':'f'*64}
    assert rpc(sql, 'request_workspace_section_rework', rework_args(invalid, request_id), check=False).returncode != 0
    sql(f"update public.user_memoir_lane set locale='zh-CN' where id='{lane}';")
    rpc(sql, 'request_workspace_section_rework', rework_args(head, request_id))
    assert sql(f"select locale from public.user_memoir_lane where id='{lane}';").stdout.strip() == head['locale']
    sql(f"delete from public.user_memory_event where user_id='{OWNER}' and project_id={literal(identity['project_id'])} and id={literal(first['partition']['id'])};")
    assert sql('select count(*) from public.user_workspace_section_rework;').stdout.strip() == '0'


@pytest.mark.parametrize('interrupted',[False,True])
def test_pg_rewrites_for_both_editions_finish_without_stranding_the_first_request(sql,interrupted):
    identity, source, lane, first = seeded_composer(sql)
    english = finish(sql, lane, first)
    project = identity['project_id']
    rpc(sql, 'set_lifetime_draft_edition', f"{literal(project)},'zh-CN'")
    chinese_page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    finish(sql, lane, chinese_page, '我在承德长大。')
    chinese = rpc(sql, 'read_lifetime_private_draft_head', f"{literal(project)},'zh-CN'")
    requests = [(english,str(uuid4())),(chinese,str(uuid4()))]
    for head, request_id in requests:
        assert rpc(sql, 'request_workspace_section_rework', rework_args(head,request_id))['status'] == 'pending'
    if interrupted:
        page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
        revised = f"Revised {page['locale']} section."
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page,revised))}")
        assert sql("select count(*) from public.user_workspace_section_rework where status='pending';").stdout.strip() == '2'
        service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
        rpc(sql, 'request_workspace_section_rework', rework_args(*requests[0]))
        assert sql(f"select locale from public.user_memoir_lane where id='{lane}';").stdout.strip() == page['locale']
        resumed = service(sql, 'claim_memoir_lane', f"'{lane}',900")
        assert resumed['snapshot_id'] == page['snapshot_id'] and resumed['complete']
        service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{resumed['token']}'")
    for _ in range(3):
        page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
        if not page: break
        compose_rework(sql, page, f"Revised {page['locale']} section.")
    for head, request_id in requests:
        replay = rpc(sql, 'request_workspace_section_rework', rework_args(head,request_id))
        assert replay['status'] == 'composed', f"{head['locale']} remained pending: {replay}"
        current = rpc(sql, 'read_lifetime_private_draft_head', f"{literal(project)},{literal(head['locale'])}")
        assert current['proposed_preview']['text'] == f"Revised {head['locale']} section."
        assert current['preview']['text'] == head['preview']['text']


def test_pg_pending_rewrite_retry_recovers_its_edition_without_interrupting_live_lease(sql):
    identity, source, lane, first = seeded_composer(sql)
    head = finish(sql, lane, first)
    args = rework_args(head,str(uuid4()))
    rpc(sql, 'request_workspace_section_rework', args)
    sequence = sql('select event_sequence from public.user_memoir_project;').stdout
    # Reproduce an idle lane left on the wrong edition by an earlier run.
    sql(f"update public.user_memoir_lane set locale='zh-CN',pending=false,attempts=3,error='MEMOIR_UNAVAILABLE' where id='{lane}';")
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'pending'
    assert sql(f"select locale||':'||pending||':'||attempts from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'en-AU:true:0'
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    active = sql(f"select token||':'||locale||':'||lease_until||':'||run_deadline||':'||attempts from public.user_memoir_lane where id='{lane}';").stdout
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'pending'
    assert sql(f"select token||':'||locale||':'||lease_until||':'||run_deadline||':'||attempts from public.user_memoir_lane where id='{lane}';").stdout == active
    finish(sql, lane, page, 'Revised English prose.')
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'composed'
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f'
    assert sql('select event_sequence from public.user_memoir_project;').stdout == sequence


def attach_first_photo(sql, identity, source, event_id, *, provenance='narrator_metadata'):
    from test_agent_commit_postgres import OLD, as_user
    project = identity['project_id']
    metadata = dict(content_type='image/png',byte_size=8,width=2,height=2)
    photo = rpc(sql, 'begin_user_interview_photo', f"{literal(project)},{literal(metadata)}")
    sql(f"insert into storage.objects(bucket_id,name) values('memoir-private-photos',{literal(photo['object_path'])});")
    rpc(sql, 'finish_user_interview_photo', f"{literal(project)},'{photo['id']}'")
    turn = '00000000-0000-4000-8000-000000000001'
    rpc(sql, 'accept_user_interview_turn', f"{literal(project)},'{turn}',{literal(source['text'])},'narrator_chat','en-AU',{literal([photo['id']])}")
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    plan = dict(candidates=[],chosen_id=None,active_event_id=event_id)
    association = dict(photo_id='upload:'+photo['id'],event_id=event_id,source_id=source['id'],source_version=1,
        quote=source['text'],description='The storyteller selected this childhood photo.',provenance=provenance)
    result = rpc(sql, 'save_user_interview_plan', f"{literal(project)},'{turn}',{literal(plan)},{literal([association])},'{OLD}'")
    link = result['photo_associations'][0]
    assert link['event_id'] == event_id and link['status'] == 'confirmed'
    return link


@pytest.mark.parametrize('stage',['queued','yielded','legacy_pending'])
def test_pg_attaching_first_photo_after_queuing_rewrite_does_not_requeue_empty_drafts(sql,stage):
    identity, source, lane, first = seeded_composer(sql)
    project = identity['project_id']
    head = finish(sql, lane, first)
    request_id = str(uuid4())
    args = rework_args(head, request_id)
    rpc(sql, 'request_workspace_section_rework', args)
    if stage == 'yielded':
        interrupted = service(sql, 'claim_memoir_lane', f"'{lane}',900")
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{interrupted['token']}',{interrupted['page_number']},{literal(section_result(interrupted,'Source-only rewrite.'))}")
        assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'pending'
        service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{interrupted['token']}'")
    original = sql(f"select row_to_json(s) from public.user_lifetime_memoir_section s where snapshot_id='{head['snapshot_id']}';").stdout
    if stage == 'legacy_pending':
        # Simulate a request stranded by the previous migration so the
        # completion guard is exercised independently of the new trigger.
        sql('alter table public.user_interview_photo_link disable trigger workspace_rework_photo_invalidation;')
    try:
        link = attach_first_photo(sql, identity, source, first['partition']['id'])
    finally:
        if stage == 'legacy_pending':
            sql('alter table public.user_interview_photo_link enable trigger workspace_rework_photo_invalidation;')
    assert sql(f"select row_to_json(s) from public.user_lifetime_memoir_section s where snapshot_id='{head['snapshot_id']}';").stdout == original
    assert sql(f"select count(*) from public.user_workspace_section_rework where request_id='{request_id}';").stdout.strip() == ('1' if stage == 'legacy_pending' else '0')
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['partition_key'].endswith(':'+link['id'])
    assert page['partition_key'] != head['first_record']['id']
    while not page['complete']:
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f', 'first photo attachment queued another empty draft'
    assert service(sql, 'claim_memoir_lane', f"'{lane}',900") is None
    assert sql(f"select count(*) from public.user_workspace_section_rework where request_id='{request_id}';").stdout.strip() == '0'
    assert rpc(sql, 'request_workspace_section_rework', args, check=False).returncode != 0
    current = rpc(sql, 'read_lifetime_private_draft_head', literal(project))
    obsolete = {**current,'first_record':head['first_record']}
    assert rpc(sql, 'request_workspace_section_rework', rework_args(obsolete,str(uuid4())), check=False).returncode != 0
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f'


def test_pg_photo_attachment_preserves_rewrites_for_other_evidence_and_sibling_photos(sql):
    from test_lifetime_review_repairs import add_photo_link
    identity, source, lane, first = seeded_composer(sql)
    project = identity['project_id']
    event_id = first['partition']['id']
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    other = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','Our home had a garden.'")
    refs = [dict(source_id=s['id'],version=1,quote=s['text'],char_start=0,char_end=len(s['text'])) for s in (source,other)]
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([{'id':s['id'],'version':1} for s in (source,other)])},{literal([dict(existing_id=event_id,expected_revision=1,kind='event',title='Childhood',source_refs=refs)])}")
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    partitions = {}
    while not page['complete']:
        assert page['partition']['id'] == event_id
        partitions[page['source']['id']] = page['partition_key']
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert len(partitions) == 2
    head = rpc(sql, 'read_lifetime_private_draft_head', literal(project))
    for partition in partitions.values():
        rpc(sql, 'request_workspace_section_rework', rework_args({**head,'first_record':{'id':partition}},str(uuid4())))
    preserved = sql(f"select row_to_json(r) from public.user_workspace_section_rework r where source_id='{other['id']}';").stdout
    attach_first_photo(sql, identity, source, event_id)
    assert sql(f"select count(*) from public.user_workspace_section_rework where source_id='{source['id']}';").stdout.strip() == '0'
    assert sql(f"select row_to_json(r) from public.user_workspace_section_rework r where source_id='{other['id']}';").stdout == preserved
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    photo_partition = None
    while not page['complete']:
        if page['source']['id'] == source['id']:
            photo_partition = page['partition_key']
        else:
            assert page['editorial_request'] is not None
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert photo_partition and photo_partition != partitions[source['id']]
    head = rpc(sql, 'read_lifetime_private_draft_head', literal(project))
    rpc(sql, 'request_workspace_section_rework', rework_args({**head,'first_record':{'id':photo_partition}},str(uuid4())))
    preserved = sql("select row_to_json(r) from public.user_workspace_section_rework r order by partition_key;").stdout
    # Adding a second photo creates a sibling instead of replacing this key.
    add_photo_link(sql, identity, source, first)
    assert sql("select row_to_json(r) from public.user_workspace_section_rework r order by partition_key;").stdout == preserved
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    edited = []
    while not page['complete']:
        if page['editorial_request'] is not None:
            edited.append(page['partition_key'])
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert edited == [photo_partition]
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f'


def test_pg_photo_outside_composer_partition_preserves_source_only_rewrite(sql):
    identity, source, lane, first = seeded_composer(sql)
    head = finish(sql, lane, first)
    args = rework_args(head,str(uuid4()))
    rpc(sql, 'request_workspace_section_rework', args)
    before = sql('select row_to_json(r) from public.user_workspace_section_rework r;').stdout
    attach_first_photo(sql, identity, source, first['partition']['id'],provenance='narrator')
    assert sql('select row_to_json(r) from public.user_workspace_section_rework r;').stdout == before
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['partition_key'] == head['first_record']['id'] and page['editorial_request'] is not None
    finish(sql, lane, page)
    assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'composed'
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f'


@pytest.mark.parametrize('yielded',[False,True])
def test_pg_unlinking_photo_after_queuing_rewrite_does_not_requeue_empty_drafts(sql,yielded):
    from test_lifetime_review_repairs import add_photo_link
    identity, source, lane, first = seeded_composer(sql)
    project = identity['project_id']
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    link = add_photo_link(sql, identity, source, first)
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    while not page['complete']:
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    head = rpc(sql, 'read_lifetime_private_draft_head', literal(project))
    partition = sql(f"select partition_key from public.user_lifetime_memoir_section where right(partition_key,37)=':{link}';").stdout.strip()
    assert partition
    request_id = str(uuid4())
    args = rework_args({**head,'first_record':{'id':partition}},request_id)
    rpc(sql, 'request_workspace_section_rework', args)
    if yielded:
        interrupted = service(sql, 'claim_memoir_lane', f"'{lane}',900")
        assert interrupted['partition_key'] == partition
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{interrupted['token']}',{interrupted['page_number']},{literal(section_result(interrupted,'Photo-dependent rewrite.'))}")
        assert rpc(sql, 'request_workspace_section_rework', args)['status'] == 'pending'
        service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{interrupted['token']}'")
    rpc(sql, 'unlink_user_interview_photo', f"{literal(project)},'{link}'")
    # Drain the legitimate policy-refresh run. The retired partition cannot
    # receive an editorial page and must not schedule another empty snapshot.
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    while not page['complete']:
        assert page['partition_key'] != partition
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f', 'unlinked photo rewrite queued another empty draft'
    assert service(sql, 'claim_memoir_lane', f"'{lane}',900") is None
    assert sql(f"select count(*) from public.user_workspace_section_rework where request_id='{request_id}';").stdout.strip() == '0'
    assert rpc(sql, 'request_workspace_section_rework', args, check=False).returncode != 0
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f'


@pytest.mark.parametrize('action',['unlink','delete_photo','edit_link','delete_link'])
def test_pg_photo_changes_retire_only_dependent_rewrites_and_preserve_other_tasks(sql,action):
    from test_lifetime_review_repairs import add_photo_link
    identity, source, lane, first = seeded_composer(sql)
    project = identity['project_id']
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{first['token']}'")
    link = add_photo_link(sql, identity, source, first)
    sibling = add_photo_link(sql, identity, source, first)
    other = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','Later I moved to Sydney.'")
    ref = dict(source_id=other['id'],version=1,quote=other['text'],char_start=0,char_end=len(other['text']))
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([{'id':other['id'],'version':1}])},{literal([dict(kind='event',title='Sydney',source_refs=[ref])])}")
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    partitions = []
    while not page['complete']:
        partitions.append(page['partition_key'])
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert len(partitions) == 3
    head = rpc(sql, 'read_lifetime_private_draft_head', literal(project))
    for partition in partitions:
        rpc(sql, 'request_workspace_section_rework', rework_args({**head,'first_record':{'id':partition}},str(uuid4())))
    # A no-op link update must not discard any queued instruction.
    before = sql('select row_to_json(r) from public.user_workspace_section_rework r order by partition_key;').stdout
    sql(f"update public.user_interview_photo_link set description=description where id='{link}';")
    assert sql('select row_to_json(r) from public.user_workspace_section_rework r order by partition_key;').stdout == before
    unaffected = sql(f"select row_to_json(r) from public.user_workspace_section_rework r where right(partition_key,37)<>':{link}' order by partition_key;").stdout
    if action == 'unlink':
        assert rpc(sql, 'unlink_user_interview_photo', f"{literal(project)},'{link}'", owner=OTHER, check=False).returncode != 0
        assert sql('select row_to_json(r) from public.user_workspace_section_rework r order by partition_key;').stdout == before
        rpc(sql, 'unlink_user_interview_photo', f"{literal(project)},'{link}'")
        rpc(sql, 'unlink_user_interview_photo', f"{literal(project)},'{link}'")
    elif action == 'delete_photo':
        photo = sql(f"select substr(photo_id,8) from public.user_interview_photo_link where id='{link}';").stdout.strip()
        rpc(sql, 'delete_user_interview_photo', f"{literal(project)},'{photo}'")
    elif action == 'edit_link':
        sql(f"update public.user_interview_photo_link set description='Corrected photo description' where id='{link}';")
    else:
        sql(f"delete from public.user_interview_photo_link where id='{link}';")
    assert sql(f"select count(*) from public.user_workspace_section_rework where right(partition_key,37)=':{link}';").stdout.strip() == '0'
    assert sql(f"select row_to_json(r) from public.user_workspace_section_rework r where right(partition_key,37)<>':{link}' order by partition_key;").stdout == unaffected
    assert sql(f"select count(*) from public.user_workspace_section_rework where right(partition_key,37)=':{sibling}';").stdout.strip() == '1'
    # Surviving instructions still reach real composer pages and completion.
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    composed = set()
    while not page['complete']:
        if page['editorial_request'] is not None:
            composed.add(page['partition_key'])
        service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert composed == {partition for partition in partitions if not partition.endswith(':'+link)}
    assert sql("select count(*) from public.user_workspace_section_rework where status='composed';").stdout.strip() == '2'
    assert sql(f"select pending from public.user_memoir_lane where id='{lane}';").stdout.strip() == 'f'


def test_pg_focused_narration_keeps_literal_source_and_recovers_saved_reply_after_event_changes(sql, tmp_path, monkeypatch):
    import json
    import httpx
    from fastapi.testclient import TestClient
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from memoir_postgres_workflow import PostgresRest
    from test_name_only_opening import proposal
    identity, _, _, first = seeded_composer(sql)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')
    dsn=sql.publication_dsn
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',dsn)
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_MODEL','gpt-5.6-luna-pooled')
    monkeypatch.setenv('MEMORY_SPARK_FREE_RECALL_ROUNDS','999')
    calls=[]
    focus={'kind':'explore_memory','event_id':first['partition']['id'],'event_revision':first['partition']['revision']}
    def provider(request):
        body=json.loads(request.content);calls.append(body)
        assert body['interview_context']['workspace_focus']==focus
        assert body['interview_context']['events'][0]['id']==focus['event_id']
        assert json.loads(body['governed']['packet'])['interview_context']['workspace_focus']==focus
        response=proposal(name=None,question='What do you remember about the garden?')
        response['acknowledgement']='You remember roses in the garden.'
        return worker_reply(request,{'reply':json.dumps(response),'thread_id':'synthetic','artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path/'homes',worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    payload={'project_id':identity['project_id'],'client_turn_id':str(uuid4()),'text':'There were roses in the garden.','workspace_focus':focus}
    with TestClient(create_app(MemoryStore())) as client:
        response=client.post('/v1/agent/turn',json=payload)
        assert response.status_code==200,response.text
        assert response.json()['conversation_saved']
        sql(f"update public.user_memory_event set revision=revision+1 where id={literal(focus['event_id'])};")
        replay=client.post('/v1/agent/turn',json=payload)
        assert replay.status_code==200 and replay.json()['cached'],replay.text
        before=sql('select count(*) from public.user_narrator_source;').stdout
        stale=client.post('/v1/agent/turn',json={**payload,'client_turn_id':str(uuid4())})
        assert stale.status_code==409,stale.text
        assert sql('select count(*) from public.user_narrator_source;').stdout==before
    assert len(calls)==1
    assert sql(f"select text from public.user_narrator_source where client_turn_id='{payload['client_turn_id']}';").stdout.strip()==payload['text']


def test_progressive_editorial_commit_rejects_siblings_and_replays_exact_result(sql):
    identity,source,lane,first=seeded_composer(sql)
    head=finish(sql,lane,first)
    rpc(sql,'request_workspace_section_rework',rework_args(head,str(uuid4())))
    page=service(sql,'claim_memoir_lane',f"'{lane}',900")
    result=section_result(page,'Chengde was my childhood home.')
    forged=deepcopy(result)
    forged['sections'].append({**deepcopy(result['sections'][0]),'id':'unrequested-sibling'})
    before=sql('select row_to_json(s) from public.user_lifetime_memoir_section s;').stdout
    with pytest.raises(AssertionError,match='only the selected writing'):
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{page['token']}',{page['page_number']},{literal(forged)}")
    assert sql('select row_to_json(s) from public.user_lifetime_memoir_section s;').stdout==before
    args=f"'{lane}','{page['token']}',{page['page_number']},{literal(result)}"
    committed=service(sql,'commit_lifetime_memoir_lane_page',args)
    assert committed['status']=='page_saved'
    import json
    replay=json.loads(sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page({args},{literal(page['page_digest'])});").stdout.strip())
    assert replay['replayed'] is True
    saved=sql('select row_to_json(s) from public.user_lifetime_memoir_section s order by snapshot_id;').stdout
    changed=deepcopy(result);changed['sections'][0]['block']['text']='Changed after delivery'
    with pytest.raises(AssertionError,match='replay conflict'):
        sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane}','{page['token']}',{page['page_number']},{literal(changed)},{literal(page['page_digest'])});")
    assert sql('select row_to_json(s) from public.user_lifetime_memoir_section s order by snapshot_id;').stdout==saved
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{page['token']}'")
    current=rpc(sql,'read_lifetime_private_draft_head',literal(identity['project_id']))
    assert current['first_record']['id']==head['first_record']['id']
    assert current['first_record']['preview']['text']==source['text']
    assert current['first_record']['proposed_preview']['text']=='Chengde was my childhood home.'


def test_photo_attachment_policy_change_refuses_stale_rework_without_rewriting_prose(sql):
    identity,source,lane,first=seeded_composer(sql)
    head=finish(sql,lane,first)
    request_id=str(uuid4())
    args=rework_args(head,request_id)
    rpc(sql,'request_workspace_section_rework',args)
    original=sql(f"select bundle::text from public.user_lifetime_memoir_section where snapshot_id='{head['snapshot_id']}';").stdout
    rounds=sql('select count(*) from public.user_completed_round;').stdout
    sequence=sql('select event_sequence from public.user_memoir_project;').stdout
    attach_first_photo(sql,identity,source,first['partition']['id'])
    # The authenticated photo-plan RPC advances policy authority. Preserve
    # stored original bytes while refusing the now-stale root and its request.
    assert sql('select count(*) from public.user_workspace_section_rework;').stdout.strip()=='0'
    with pytest.raises(AssertionError,match='section root changed'):
        rpc(sql,'request_workspace_section_rework',args)
    assert sql(f"select bundle::text from public.user_lifetime_memoir_section where snapshot_id='{head['snapshot_id']}';").stdout==original
    assert sql('select text from public.user_narrator_source;').stdout.strip()==source['text']
    assert sql('select count(*) from public.user_completed_round;').stdout==rounds
    assert sql('select event_sequence from public.user_memoir_project;').stdout==sequence


def test_stranded_progressive_rework_is_retired_after_policy_change_before_dispatch(sql):
    identity,source,lane,first=seeded_composer(sql)
    head=finish(sql,lane,first)
    request_id=str(uuid4())
    rpc(sql,'request_workspace_section_rework',rework_args(head,request_id))
    original=sql(f"select row_to_json(s) from public.user_lifetime_memoir_section s where snapshot_id='{head['snapshot_id']}';").stdout
    rounds=sql('select count(*) from public.user_completed_round;').stdout
    sql('alter table public.user_interview_photo_link disable trigger workspace_rework_photo_invalidation;')
    try:
        attach_first_photo(sql,identity,source,first['partition']['id'])
    finally:
        sql('alter table public.user_interview_photo_link enable trigger workspace_rework_photo_invalidation;')
    assert sql(f"select count(*) from public.user_workspace_section_rework where request_id='{request_id}';").stdout.strip()=='1'
    page=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert page['editorial_request'] is None
    assert sql(f"select count(*) from public.user_workspace_section_rework where request_id='{request_id}';").stdout.strip()=='0'
    for _ in range(4):
        if page['complete']:break
        assert page['editorial_request'] is None
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
        page=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{page['token']}'")
    assert page['complete']
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{page['token']}'")
    assert service(sql,'claim_memoir_lane',f"'{lane}',900") is None
    assert sql(f"select row_to_json(s) from public.user_lifetime_memoir_section s where snapshot_id='{head['snapshot_id']}';").stdout==original
    assert sql('select count(*) from public.user_completed_round;').stdout==rounds


def test_secondary_event_change_retires_exact_edition_request_despite_other_edition(sql):
    from test_progressive_photo_invalidation import block, validated_result
    identity, source_a, lane, initial = seeded_composer(sql)
    project = identity['project_id']
    service(sql, 'yield_lifetime_memoir_lane', f"'{lane}','{initial['token']}'")
    source_b = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','Later I moved to Sydney.'")
    ref_b = dict(source_id=source_b['id'], version=1, quote=source_b['text'], char_start=0, char_end=len(source_b['text']))
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([{'id':source_b['id'],'version':1}])},{literal([dict(kind='event',title='Sydney',source_refs=[ref_b])])}")
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    event_a = initial['partition']['id']
    event_b = next(event['id'] for event in page['batch']['events'] if event['id'] != event_a)
    shared = block('shared', source_a)
    shared['source_refs'].extend(block('b', source_b)['source_refs'])
    shared['text'] += ' ' + source_b['text']
    english_result = validated_result(page, [shared, block('unrelated', source_a)], event_ids=[event_a, event_b])
    # The second passage depends only on A. Validate that exact chapter separately
    # before combining its independent stored writing with the A+B passage.
    independent = validated_result(page, [block('unrelated', source_a)], event_ids=[event_a])
    english_result['sections'] = [item for item in english_result['sections'] if item['id'].endswith('__shared')]
    english_result['sections'] += independent['sections']
    english_result['review'] = controlled_section_review(page, english_result['sections'])
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{page['token']}',{page['page_number']},{literal(english_result)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    english = rpc(sql, 'read_lifetime_private_draft_head', literal(project))
    records = rpc(sql, 'read_lifetime_private_draft_page', f"{literal(project)},'{english['snapshot_id']}'")['records']
    selected = next(item for item in records if item['id'].endswith('__shared'))
    unrelated = next(item for item in records if item['id'].endswith('__unrelated'))
    rpc(sql, 'set_lifetime_draft_edition', f"{literal(project)},'zh-CN'")
    chinese = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    result = validated_result(chinese, [block('shared', source_a)], event_ids=[event_a])
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{chinese['token']}',{chinese['page_number']},{literal(result)}")
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{chinese['token']}'")
    stale_id, valid_id = str(uuid4()), str(uuid4())
    rpc(sql, 'request_workspace_section_rework', rework_args({**english,'first_record':selected}, stale_id))
    rpc(sql, 'request_workspace_section_rework', rework_args({**english,'first_record':unrelated}, valid_id))
    before = sql(f"select bundle::text from public.user_lifetime_memoir_section where snapshot_id='{english['snapshot_id']}' and partition_key={literal(selected['id'])};").stdout
    epoch = sql('select policy_epoch from public.user_memoir_project;').stdout
    changed_source = rpc(sql, 'accept_user_narrator_source', f"{literal(project)},'{uuid4()}','My Sydney home had a blue front door.'")
    changed_ref = dict(source_id=changed_source['id'], version=1, quote=changed_source['text'], char_start=0, char_end=len(changed_source['text']))
    update = dict(existing_id=event_b, expected_revision=1, kind='event', title='My later Sydney home', source_refs=[changed_ref])
    rpc(sql, 'apply_user_memory_events', f"{literal(project)},{literal([{'id':changed_source['id'],'version':1}])},{literal([update])}")
    assert sql('select policy_epoch from public.user_memoir_project;').stdout == epoch
    assert sql(f"select revision from public.user_memory_event where id={literal(event_b)};").stdout.strip() == '2'
    assert sql(f"select public.workspace_progressive_section_current(s) from public.user_lifetime_memoir_section s where snapshot_id='{english['snapshot_id']}' and partition_key={literal(selected['id'])};").stdout.strip() == 'f'
    assert sql(f"select public.workspace_rework_partition_current('{OWNER}',{literal(project)},{literal(event_a)},{literal(selected['id'])});").stdout.strip() == 't'
    assert sql(f"select count(*) from public.user_workspace_section_rework where request_id='{stale_id}';").stdout.strip() == '1'
    page = service(sql, 'claim_memoir_lane', f"'{lane}',900")
    assert page['locale'] == 'en-AU' and page['editorial_request']['request_id'] == valid_id
    assert sql(f"select count(*) from public.user_workspace_section_rework where request_id='{stale_id}';").stdout.strip() == '0'
    assert page['partition_key'] == unrelated['id']
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
    for _ in range(4):
        page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane}','{page['token']}'")
        if page['complete']:
            break
        assert page['editorial_request'] is None
        service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane}','{page['token']}',{page['page_number']},{literal(section_result(page))}")
    assert page['complete']
    service(sql, 'complete_lifetime_memoir_lane', f"'{lane}','{page['token']}'")
    assert service(sql, 'claim_memoir_lane', f"'{lane}',900") is None
    assert sql(f"select status from public.user_workspace_section_rework where request_id='{valid_id}';").stdout.strip() == 'composed'
    assert sql(f"select bundle::text from public.user_lifetime_memoir_section where snapshot_id='{english['snapshot_id']}' and partition_key={literal(selected['id'])};").stdout == before
