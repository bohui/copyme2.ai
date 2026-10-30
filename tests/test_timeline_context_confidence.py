"""Prior conversation and event context produce sourced placement confidence."""
from copy import deepcopy
import json
from uuid import UUID

import pytest
from pydantic import ValidationError

from apps.api.memory_events import EventProposal, extraction_schema
from apps.api.timeline_context import placement_links
from test_conversation_attribution import Conversation, empty, episode, reference
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database  # noqa: F401
from test_shared_memory_events_postgres import literal, rpc
from test_agent_commit_postgres import OWNER


CHENGDE = dict(place='Chengde', hierarchy=['Earth','China','Hebei','Chengde'], granularity='city')


def prior_ref(source, quote):
    return dict(source_id=source['id'], version=source['version'], quote=quote,
                char_start=None, char_end=None)


def drain(conversation):
    outcome=conversation.drain()
    assert outcome.get('status') not in {'retry','retry_required'}, conversation.last_db_error
    pending=conversation.sql(f"select count(*) from public.user_narrator_source where project_id={literal(conversation.project)} and processing_status<>'succeeded';").stdout.strip()
    if pending!='0':
        pytest.fail(conversation.last_db_error)
    return outcome


@pytest.mark.parametrize('field', ['locationConfidenceScore','yearConfidenceScore'])
@pytest.mark.parametrize('score', [-0.01,1.01,True,float('nan'),None,'0.9'])
def test_confidence_scores_are_bounded_numbers(field, score):
    with pytest.raises(ValidationError):
        EventProposal(kind='event',title='A memory',source_refs=[dict(source_id='source',version=1,quote='A memory')],
                      **{field:score})


def test_model_schema_requires_both_numeric_confidence_scores():
    proposal = extraction_schema()['$defs']['EventProposal']
    for field in ('locationConfidenceScore','yearConfidenceScore'):
        assert field in proposal['required']
        assert proposal['properties'][field] == dict(type='number',minimum=0,maximum=1)


def test_low_confidence_location_does_not_create_a_map_link():
    event=dict(location=CHENGDE,locationConfidenceScore=0.6,
               location_basis=[dict(source_id='source',version=1,quote='I was born in Chengde.')])
    assert placement_links([event]) == []
    assert len(placement_links([{**event,'locationConfidenceScore':0.95}])) == 1
    assert placement_links([{**event,'locationConfidenceScore':0.99,'candidate_ids':['first','second']}]) == []


def test_twenty_multilingual_rounds_and_last_event_fit_the_model_budget():
    from apps.api.lifetime_memory_composer import lane_model_budget, validate_page
    from apps.api.lifetime_memory_context import serialize_packet
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input, lane_extraction_packet, lane_request_tokens
    from test_lifetime_memory_lane_engine import page, fence_for
    current=page()
    current['source']['sequence']=22
    history=[]
    for index in range(20):
        source={**current['source'],'id':str(UUID(int=100+index)),'sequence':index+1,
                'text':'往'*320,'char_start':0,'char_end':320,'original_length':320}
        history.append(dict(sequence=index+1,source=source,source_complete=True,
            assistant=dict(role='assistant',personal_testimony=False,text='问'*96,complete=False)))
    last={**history[0]['source'],'text':'忆'*500,'char_end':500,'original_length':500}
    current['timeline_context']=dict(conversation_history=history,last_event=dict(id='last-saved',revision=1,
        title='事'*300,uncertainty='待'*2000,original_passages=[last,{**last,'id':str(UUID(int=999))}]))
    assert len(serialize_packet(current['timeline_context']).encode('utf-8'))>40000
    validate_page(current)
    bounded=build_bounded_lane_input(current,phase='extract',
        packet=lane_extraction_packet(fence_for(current)),budget=lane_model_budget(timeline_context=True))
    assert lane_request_tokens(bounded)<=bounded.budget.input_budget


def test_ambiguous_historical_quote_repair_keeps_its_original_coordinates():
    from apps.api.lifetime_memory_composer import extraction_events, lane_model_budget
    from apps.api.lifetime_memory_lane_engine import build_bounded_lane_input, lane_contract, lane_extraction_packet
    from test_lifetime_memory_lane_engine import page, fence_for
    current=page()
    current['source'].update(text='I worked there.',sequence=2,char_end=15,original_length=15)
    text='x'*198+'. '+'Chengde. Chengde.'
    prior={**current['source'],'id':str(UUID(int=100)),'sequence':1,'text':text,
           'char_start':2048,'char_end':2048+len(text),'original_length':2048+len(text)}
    current['timeline_context']=dict(conversation_history=[dict(sequence=1,source=prior)],last_event=None)
    packet=lane_extraction_packet(fence_for(current))
    packet['retry_reason']='PAGE_AMBIGUOUS'
    bounded=build_bounded_lane_input(current,phase='extract',packet=packet,budget=lane_model_budget(timeline_context=True))
    _,schema=lane_contract('extract',current['locale'],fence=bounded.fence,retry_reason='PAGE_AMBIGUOUS')
    evidence=schema['$defs']['EvidenceRef']['properties']
    assert evidence['char_start']['maximum']>=text.rindex('Chengde.')
    catalog=json.loads(bounded.packet)['payload']['context_quote_occurrences'][0]
    selected=next(item for item in catalog['quotes'] if item['quote']=='Chengde.')['spans'][1]
    event=dict(kind='event',title='Work',source_refs=[prior_ref(current['source'],'I worked there.')],
        location=CHENGDE,locationConfidenceScore=0.95,yearConfidenceScore=0,
        location_basis=[{**prior_ref(prior,'Chengde.'),**selected}])
    saved=extraction_events(dict(events=[event]),current)[0]
    ref=saved['location_basis'][0]
    assert ref['char_start']==2048+text.rindex('Chengde.')
    assert prior['text'][ref['char_start']-2048:ref['char_end']-2048]=='Chengde.'
    event['source_refs']=[prior_ref(prior,'Chengde.')]
    with pytest.raises(ValueError,match='current source|ambiguous'):
        extraction_events(dict(events=[event]),current)


def test_multiple_excerpts_select_exact_relative_spans_and_reject_ambiguity():
    from apps.api.lifetime_memory_composer import extraction_events
    from test_lifetime_memory_lane_engine import page
    current=page()
    current['source']['sequence']=2
    prior={**current['source'],'id':str(UUID(int=100)),'sequence':1,
        'text':'Chengde.'+'x'*312,'char_start':0,'char_end':320,'original_length':1000}
    later={**prior,'text':'x'*100+'Chengde.'+'x'*392,'char_start':500,'char_end':1000}
    current['timeline_context']=dict(conversation_history=[dict(sequence=1,source=prior)],
                                   last_event=dict(original_passages=[later]))
    ref={**prior_ref(prior,'Chengde.'),'char_start':100,'char_end':108}
    event=dict(kind='event',title='Work',source_refs=[prior_ref(current['source'],current['source']['text'])],
        location=CHENGDE,locationConfidenceScore=0.95,yearConfidenceScore=0,location_basis=[ref])
    assert extraction_events(dict(events=[event]),current)[0]['location_basis'][0]['char_start']==600
    ref.update(char_start=None,char_end=None)
    with pytest.raises(ValueError,match='ambiguous'):
        extraction_events(dict(events=[event]),current)
    ref.update(char_start=100,char_end=108)
    prior['text']='x'*100+'Chengde.'+'x'*212
    with pytest.raises(ValueError,match='ambiguous'):
        extraction_events(dict(events=[event]),current)


def test_childhood_location_candidates_reach_lane_a_and_confirmation_updates_the_same_event(sql,tmp_path,monkeypatch):
    birth = 'I was born in Chengde in 1991.'
    childhood = 'When I was little, I played in the staff compound at my father\'s school.'
    confirmation = 'The compound was in Chengde in 1997.'
    packets = []

    def extract(packet):
        text = packet['sources'][0]['text']
        packets.append(packet)
        event=episode(packet,text,title='Birth' if text==birth else 'Playing in the school staff compound')
        event.update(location=CHENGDE,locationConfidenceScore=1.0,yearConfidenceScore=1.0,
                     location_basis=[reference(packet,text)])
        if text==birth:
            event.update(life_stage='baby',stage_evidence=[reference(packet,text)],
                temporal=dict(expression='1991',precision='year',year_start=1991,year_end=1991,basis=[reference(packet,text)]))
        elif text==childhood:
            previous=packet['conversation_history'][-1]['source']
            assert previous['text']==birth
            assert packet['last_event']['title']=='Birth'
            assert packet['last_event']['places'][0]['place']['place']=='Chengde'
            event.update(kind='period',life_stage='childhood',stage_evidence=[reference(packet,'When I was little')],
                temporal=None,locationConfidenceScore=0.55,yearConfidenceScore=0.0,
                location_basis=[prior_ref(previous,birth)],uncertainty='Childhood city is not stated; Chengde is only a candidate.')
        elif text==confirmation:
            saved=packet['last_event']
            event.update(existing_id=saved['id'],expected_revision=saved['revision'],kind='period',
                temporal=dict(expression='1997',precision='year',year_start=1997,year_end=1997,basis=[reference(packet,text)]),
                uncertainty='')
        else:
            return empty(packet)
        return {**empty(packet),'events':[event]}

    conversation=Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    with conversation.client:
        conversation.say(birth);drain(conversation)
        conversation.say(childhood);drain(conversation)
        feed=conversation.client.get('/v1/story/map-events',params={'project_id':conversation.project}).json()
        saved=next(event for event in feed['events'] if event['kind']=='period')
        places=conversation.client.get(f'/v1/story/map-events/{conversation.project}/{saved["id"]}/places').json()
        assert places['items']==[], 'A low-confidence candidate must not become a map location'
        conversation.say('I remember the playground clearly.')
        context=conversation.foreground[-1]
        pending=next(event for event in context['events'] if event['id']==saved['id'])
        assert pending['locationConfidenceScore']==0.55 and pending['yearConfidenceScore']==0
        assert pending['location']['place']=='Chengde'
        assert pending['needs_confirmation']==dict(location=True,year=True)
        drain(conversation)
        conversation.say(confirmation);drain(conversation)
        feed=conversation.client.get('/v1/story/map-events',params={'project_id':conversation.project}).json()
        updated=next(event for event in feed['events'] if event['id']==saved['id'])
        assert updated['temporal']['year_start']==1997
        places=conversation.client.get(f'/v1/story/map-events/{conversation.project}/{saved["id"]}/places').json()
        assert [item['place']['place'] for item in places['items']]==['Chengde']


def test_an_explicit_previous_city_and_year_can_ground_the_current_event(sql,tmp_path,monkeypatch):
    first='In 1997 I lived in Chengde.'
    second='That same year I started working there.'
    def extract(packet):
        text=packet['sources'][0]['text']
        event=episode(packet,text,title='Living in Chengde' if text==first else 'Starting work')
        basis=[reference(packet,text)]
        if text==second:
            basis.append(prior_ref(packet['conversation_history'][-1]['source'],first))
            assert packet['last_event']['title']=='Living in Chengde'
        event.update(location=CHENGDE,location_basis=basis,locationConfidenceScore=0.96,yearConfidenceScore=0.96,
            temporal=dict(expression='1997' if text==first else 'That same year',precision='year',
                          year_start=1997,year_end=1997,basis=basis))
        return {**empty(packet),'events':[event]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    with conversation.client:
        conversation.say(first);drain(conversation)
        conversation.say(second);drain(conversation)
        feed=conversation.client.get('/v1/story/map-events',params={'project_id':conversation.project}).json()
        saved=next(event for event in feed['events'] if event['title']=='Starting work')
        assert saved['temporal']['year_start']==1997
        places=conversation.client.get(f'/v1/story/map-events/{conversation.project}/{saved["id"]}/places').json()
        assert [item['place']['place'] for item in places['items']]==['Chengde']


def test_explicit_year_correction_also_saves_current_confidence_metadata(sql,tmp_path,monkeypatch):
    first='I worked in Chengde in 1997.'
    correction='Actually, I worked in Chengde in 1998.'
    def extract(packet):
        text=packet['sources'][0]['text']
        event=episode(packet,text,title='Work')
        year=1997 if text==first else 1998
        event.update(location=CHENGDE,location_basis=[reference(packet,text)],
            locationConfidenceScore=1 if text==first else 0.95,yearConfidenceScore=1,
            temporal=dict(expression=str(year),precision='year',year_start=year,year_end=year,basis=[reference(packet,text)]))
        if text!=first:
            previous=packet['last_event']
            event.update(existing_id=previous['id'],expected_revision=previous['revision'],correction=reference(packet,text))
        return {**empty(packet),'events':[event]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    with conversation.client:
        conversation.say(first);drain(conversation)
        conversation.say(correction);drain(conversation)
        saved=conversation.client.get('/v1/story/map-events',params={'project_id':conversation.project}).json()['events'][0]
        assert saved['temporal']['year_start']==1998
        assert saved['yearConfidenceScore']==1 and saved['locationConfidenceScore']==0.95


def test_location_correction_clears_the_candidate_and_old_map_link(sql,tmp_path,monkeypatch):
    first='I played in Chengde.'
    correction='Actually, I cannot remember which city that was.'
    def extract(packet):
        text=packet['sources'][0]['text']
        event=episode(packet,text,title='Playing outdoors')
        if text==first:
            event.update(location=CHENGDE,location_basis=[reference(packet,text)],
                         locationConfidenceScore=1,yearConfidenceScore=0)
        elif text==correction:
            previous=packet['last_event']
            event.update(existing_id=previous['id'],expected_revision=previous['revision'],
                location=None,location_basis=None,locationConfidenceScore=0,yearConfidenceScore=0,
                correction=reference(packet,text),uncertainty='The narrator withdrew the city attribution.')
        else:
            previous=packet['last_event']
            event.update(existing_id=previous['id'],expected_revision=previous['revision'],
                location=dict(place='Hobart',hierarchy=['Earth','Australia','Tasmania','Hobart'],granularity='city'),
                location_basis=[reference(packet,text)],locationConfidenceScore=1,yearConfidenceScore=0)
        return {**empty(packet),'events':[event]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    with conversation.client:
        conversation.say(first);drain(conversation)
        saved=conversation.client.get('/v1/story/map-events',params={'project_id':conversation.project}).json()['events'][0]
        path=f'/v1/story/map-events/{conversation.project}/{saved["id"]}/places'
        assert len(conversation.client.get(path).json()['items'])==1
        conversation.say(correction);drain(conversation)
        assert conversation.client.get(path).json()['items']==[]
        stored=json.loads(sql(f"select data from public.user_memory_event where id={literal(saved['id'])};").stdout)
        assert stored['location'] is None and stored['locationConfidenceScore']==0
        conversation.say('Now I remember: it was Hobart.');drain(conversation)
        assert [item['place']['place'] for item in conversation.client.get(path).json()['items']]==['Hobart']


@pytest.mark.parametrize('candidate_is_city',[True,False])
def test_a_supported_suburb_refines_its_containing_city_on_the_map(sql,tmp_path,monkeypatch,candidate_is_city):
    suburb=dict(place='Shuangqiao',hierarchy=[*CHENGDE['hierarchy'],'Shuangqiao'],granularity='suburb')
    text='I went to school in Shuangqiao, Chengde.'
    def extract(packet):
        event=episode(packet,text,title='School')
        event.update(location=CHENGDE if candidate_is_city else suburb,location_basis=[reference(packet,text)],
                     locationConfidenceScore=1,yearConfidenceScore=0)
        return {**empty(packet),'events':[event],'event_places':[dict(event_index=0,role='setting',
            place=suburb if candidate_is_city else CHENGDE,source_ref=reference(packet,text))]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    with conversation.client:
        conversation.say(text);drain(conversation)
        saved=conversation.client.get('/v1/story/map-events',params={'project_id':conversation.project}).json()['events'][0]
        places=conversation.client.get(f'/v1/story/map-events/{conversation.project}/{saved["id"]}/places').json()
        assert [item['place']['place'] for item in places['items']]==['Shuangqiao']


def test_history_has_twenty_prior_rounds_and_a_last_event_outside_that_window(sql):
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    project=identity['project_id']
    sources=[]
    for index in range(22):
        sources.append(rpc(sql,'accept_user_narrator_source',
            f"{literal(project)}, '00000000-0000-4000-8000-{index+1:012d}', {literal('Original round '+str(index+1))}"))
    ref=dict(source_id=sources[0]['id'],version=1,quote='Original round 1',char_start=0,char_end=16)
    sql(f"insert into public.user_memory_event(user_id,project_id,id,kind,life_stage,data,change_sequence) values('{OWNER}',{literal(project)},'last-saved','event','unplaced','{{\"title\":\"Earlier event\"}}',1);")
    sql(f"insert into public.user_memory_event_source(user_id,project_id,event_id,source_id,source_version,evidence_hash,evidence) values('{OWNER}',{literal(project)},'last-saved','{sources[0]['id']}',1,'one',{literal(ref)}::jsonb);")
    result=sql(f"select public.lifetime_timeline_context('{OWNER}',{literal(project)},'{sources[-1]['id']}');")
    context=json.loads(result.stdout)
    assert [item['sequence'] for item in context['conversation_history']]==list(range(2,22))
    assert context['last_event']['id']=='last-saved'
    assert context['last_event']['original_passages'][0]['id']==sources[0]['id']
    assert rpc(sql,'lifetime_timeline_context',f"'{OWNER}',{literal(project)},'{sources[-1]['id']}'",check=False).returncode
    sql(f"insert into public.user_memory_attribution_window(user_id,project_id,source_id,source_version,char_start,char_end,policy_epoch,disposition,reason) values('{OWNER}',{literal(project)},'{sources[0]['id']}',1,0,16,1,'withheld','privacy_withheld');")
    masked=json.loads(sql(f"select public.lifetime_timeline_context('{OWNER}',{literal(project)},'{sources[-1]['id']}');").stdout)
    assert masked['last_event'] is None
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{sources[1]['id']}',1,'withdraw',null")
    withdrawn=json.loads(sql(f"select public.lifetime_timeline_context('{OWNER}',{literal(project)},'{sources[-1]['id']}');").stdout)
    assert sources[1]['id'] not in [item['source']['id'] for item in withdrawn['conversation_history'] if item['source']]
    assert all(item['source'] is None or item['source']['text']!='Original round 1'
               for item in withdrawn['conversation_history'])


def test_publication_rejects_changed_history_with_copied_page_digests(sql,tmp_path,monkeypatch):
    observed=[]
    async def boundary(request,provider):
        bounded=json.loads(request.content).get('bounded_lane')
        if bounded and bounded['phase']=='extract':
            fence=bounded['fence']
            for field in ('conversation_history','last_event'):
                altered=deepcopy(fence)
                altered['timeline_context'][field]=[] if field=='last_event' else [dict(source=None,sequence=999)]
                result=sql(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{OWNER}',true);select public.lock_lifetime_memoir_lane_publication({literal(altered)}::jsonb);rollback;",check=False)
                assert result.returncode and 'timeline context changed' in result.stderr
                observed.append(field)
        return await provider(request)
    conversation=Conversation(sql,tmp_path,monkeypatch,empty,external_boundary=boundary)
    with conversation.client:
        conversation.say('I remember planting a tree.');drain(conversation)
    assert set(observed)=={'conversation_history','last_event'}


def test_twenty_rounds_eight_candidates_and_current_window_fit_every_boundary(sql):
    from apps.api.lifetime_memory_composer import lane_model_budget, validate_page
    from apps.api.lifetime_memory_lane_engine import LaneFence, build_bounded_lane_input, lane_extraction_packet, lane_request_tokens
    from test_lifetime_composer_capacity import create_lane, service
    sql('update public.lifetime_two_lane_rollout set enabled=true;')
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    project=identity['project_id']
    sources=[]
    for index in range(21):
        text='往'*320 if index<20 else '忆'*2304
        sources.append(rpc(sql,'accept_user_narrator_source',
            f"{literal(project)},'00000000-0000-4000-8000-{index+1:012d}',{literal(text)}"))
    sql(f"update public.user_narrator_source set processing_status='succeeded' where project_id={literal(project)} and sequence<21;")
    for index in range(8):
        event=dict(title='事'*299+str(index),uncertainty='待'*2000)
        sql(f"insert into public.user_memory_event(user_id,project_id,id,kind,life_stage,data,change_sequence) values('{OWNER}',{literal(project)},'event-{index}','event','unplaced',{literal(event)}::jsonb,{index+1});")
        ref=dict(source_id=sources[index]['id'],version=1,quote='往'*320,char_start=0,char_end=320)
        sql(f"insert into public.user_memory_event_source(user_id,project_id,event_id,source_id,source_version,evidence_hash,evidence) values('{OWNER}',{literal(project)},'event-{index}','{sources[index]['id']}',1,'one',{literal(ref)}::jsonb);")
    sql(f"update public.user_memoir_project set event_sequence=8 where project_id={literal(project)};")
    sql(f"insert into public.user_lifetime_two_lane_source(user_id,project_id,source_id) values('{OWNER}',{literal(project)},'{sources[-1]['id']}');")
    lane=create_lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert page.get('timeline_context') is not None, page.keys()
    assert len(page['events'])==8
    assert len(page['timeline_context']['conversation_history'])==20
    assert page['timeline_context']['last_event']['id']=='event-7'
    assert page['events'][0]['title_complete'] is False
    fence=LaneFence.model_validate({key:page[key] for key in LaneFence.model_fields if key in page}).model_dump(mode='json')
    validate_page(page)
    bounded=build_bounded_lane_input(page,phase='extract',packet=lane_extraction_packet(LaneFence.model_validate(fence)),
                                   budget=lane_model_budget(timeline_context=True))
    assert lane_request_tokens(bounded)<=bounded.budget.input_budget
    size=int(sql(f"select octet_length({literal(fence)}::jsonb::text);").stdout)
    assert size<=98304, size
    result=sql(f"begin;set local role authenticated;select set_config('request.jwt.claim.sub','{OWNER}',true);select public.lock_lifetime_memoir_lane_publication({literal(fence)}::jsonb);rollback;",check=False)
    assert result.returncode==0,result.stderr
