"""Bounded canonical lanes: fake provider plus isolated PostgreSQL only."""
import asyncio
import copy
import json
from types import SimpleNamespace
from contextlib import asynccontextmanager

import httpx
import pytest

from apps.api.lifetime_memory_composer import (
    lane_model_budget, validate_page, extraction_events, execute_lifetime_lane,
)


@pytest.fixture(autouse=True)
def enable_synthetic_lanes(monkeypatch):
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY','true')


def page(skill='timeline', index=0, text='我在承德长大。'):
    return dict(protocol='lifetime_composer_pages', schema_version=1, lane_id='00000000-0000-4000-8000-000000000014', token='00000000-0000-4000-8000-000000000015',
        snapshot_id='00000000-0000-4000-8000-000000000011', user_id='00000000-0000-4000-8000-000000000012', project_id='project', conversation_id='00000000-0000-4000-8000-000000000013',
        skill=skill, locale='zh-CN', policy_epoch=1, preference_revision=2,
        source_high_water=10000, event_high_water=10000, page_number=index,
        root_digest='0'*64, page_digest='1'*64, input_digest='2'*64, complete=False, coverage_round=10000, base_revision=0,
        preferences={'schema_version':1,'language':'zh-CN','chosen_name':None,'conversation_phase':None,
            'preference_revision':2,'privacy_complete':True,'known_continuity':[],
            'known_continuity_complete':True,'continuity_retrieval':'read_lifetime_continuity',
            'active_question':None,'unresolved_references':[],'paused_topics':[],'excluded_topics':[]},
        source=dict(id='source', project_id='project', version=1, sequence=1, text=text, char_start=index*2048,
            char_end=index*2048+len(text), original_length=index*2048+len(text),
            kind='narrator_chat', language='zh-CN', status='active', author_role='storyteller'),
        events=[], partition=None, previous=None)


class Publisher:
    @asynccontextmanager
    async def guard(self,fence):
        yield


def test_bound_includes_instructions_schema_and_output_headroom():
    budget=lane_model_budget()
    assert budget.input_budget+budget.output_headroom+budget.framing_headroom <= budget.context_window
    validate_page(page())
    with pytest.raises(ValueError, match='bounded'):
        validate_page({**page(), 'source':{**page()['source'],'text':'中'*100000}})


def test_chunk_evidence_is_exact_absolute_original_span():
    current=page(index=4)
    proposed={'events':[dict(kind='event',title='Childhood',source_refs=[
        dict(source_id='source',version=1,quote=current['source']['text'],char_start=0,char_end=7)])]}
    saved=extraction_events(proposed,current)
    assert saved[0]['source_refs'][0]['char_start']==8192
    assert saved[0]['source_refs'][0]['char_end']==8199
    assert saved[0]['source_refs'][0]['quote']=='我在承德长大。'
    assert proposed['events'][0]['source_refs'][0]['char_start']==0


def test_ambiguous_unpositioned_quote_is_rejected():
    current=page(text='home home')
    with pytest.raises(ValueError,match='ambiguous'):
        extraction_events({'events':[dict(kind='event',title='Home',source_refs=[
            dict(source_id='source',version=1,quote='home')])]},current)


def test_bounded_worker_never_uses_legacy_finish_and_resumes_after_quantum():
    seen=[]
    class Broker:
        index=0
        async def rpc(self,name,**payload):
            seen.append(name)
            if name=='read_lifetime_memoir_lane_page': return page(index=self.index)
            if name=='read_lifetime_lane_policy_source':
                source=page(index=self.index)['source']
                return {**source,'text':'x'*source['char_start']+source['text']}
            if name=='commit_lifetime_memoir_lane_page':
                self.index+=1
                return {'status':'page_saved'}
            if name=='yield_lifetime_memoir_lane': return {'status':'pending','pages':self.index}
            raise AssertionError(name)
    def model(request):
        packet=json.loads(request.content)
        assert packet['agent_role']=='author_timeline'
        return httpx.Response(200,json={'reply':'{"events":[]}'})
    broker=Broker()
    worker=SimpleNamespace(broker=broker,worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model),lane_publisher=Publisher())
    result=asyncio.run(execute_lifetime_lane(page(),worker,page_quantum=3))
    assert result=={'status':'pending','pages':3}
    assert seen.count('commit_lifetime_memoir_lane_page')==3
    assert 'finish_memoir_timeline' not in seen


def test_invalid_extraction_retries_the_same_bounded_source_before_commit():
    from apps.api.lifetime_memory_composer import _extract
    current=page();requests=[]
    class Broker:
        async def rpc(self,name,**payload):
            assert name=='read_lifetime_lane_policy_source'
            return copy.deepcopy(current['source'])
    def model(request):
        requests.append(json.loads(request.content)['bounded_lane'])
        reply='invalid structured output' if len(requests)==1 else '{"events":[]}'
        return httpx.Response(200,json={'reply':reply})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',
        worker_transport=httpx.MockTransport(model),lane_publisher=Publisher())
    assert asyncio.run(_extract(current,worker))=={'events':[]}
    assert len(requests)==2 and requests[0]==requests[1]


def test_10000_mixed_language_packets_have_constant_declared_bound():
    maximum=0
    for index in range(10000):
        current=page(text='我在承德长大。' if index%2 else 'I grew up in Chengde.')
        current['page_number']=index
        current['source'].update(id=f'00000000-0000-4000-8000-{index:012d}',sequence=index+1)
        validate_page(current)
        maximum=max(maximum,len(json.dumps(current,ensure_ascii=False).encode()))
        from apps.api.lifetime_memory_lane_engine import LaneFence,build_bounded_lane_input,lane_extraction_packet,lane_request_tokens
        fence=LaneFence.model_validate({key:current[key] for key in LaneFence.model_fields if key in current})
        bounded=build_bounded_lane_input(current,phase='extract',packet=lane_extraction_packet(fence),budget=lane_model_budget())
        assert lane_request_tokens(bounded)<=bounded.budget.input_budget
    assert maximum<3000

# Same isolated PostgreSQL fixture as the canonical mutation/lease suites.
from test_agent_commit_postgres import database, as_user, OWNER, OTHER
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, rpc, literal
from test_lifetime_memory_postgres import sql, resolve


def service(sql,name,args):
    # Keep the last observed page digest, never recapture over an old result.
    pages=getattr(sql,'lifetime_observed_pages',{})
    if name=='commit_lifetime_memoir_lane_page':
        import re
        lane,token=re.findall(r"'([^']*)'",args)[:2]
        args+=','+literal(pages[(lane,token)]['page_digest'])
    value=json.loads(sql(f'set role service_role; select coalesce(public.{name}({args}),\'null\'::jsonb);').stdout.splitlines()[-1])
    if isinstance(value,dict) and value.get('protocol')=='lifetime_composer_pages':
        pages[(value['lane_id'],value['token'])]=copy.deepcopy(value)
        sql.lifetime_observed_pages=pages
    return value


def create_lane(sql,identity,skill='timeline',rounds=5):
    project=identity['project_id']
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,target_milestone) values('{OWNER}',{literal(project)},'{skill}',{rounds if skill=='composer' else 0});")
    if skill=='composer':
        sql(f"insert into public.user_completed_round(user_id,project_id,turn_id,ordinal) select '{OWNER}',{literal(project)},gen_random_uuid(),g from generate_series(1,{rounds}) g;")
    return sql(f"select id from public.user_memoir_lane where user_id='{OWNER}' and skill='{skill}';").stdout.strip()


def test_pg_timeline_claim_chunks_original_and_resumes_without_full_history(sql):
    identity=resolve(sql);project=identity['project_id']
    source=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001',{literal('中'*5000)}")
    lane=create_lane(sql,identity)
    claim=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert claim['protocol']=='lifetime_composer_pages' and len(claim['source']['text'])==2048
    assert 'context_sources' not in claim and 'source_manifest' not in claim and claim['preferences']['privacy_complete']
    with pytest.raises(Exception):service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    result=service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,'{{\"events\":[]}}'")
    assert result['status']=='page_saved'
    assert sql('select processing_status from public.user_narrator_source;').stdout.strip()=='pending'
    replay=service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,'{{\"events\":[]}}'")
    assert replay['replayed']
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    resumed=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert resumed['snapshot_id']==claim['snapshot_id'] and resumed['page_number']==1
    assert resumed['source']['char_start']==1792 and resumed['core_start']==2048
    for number in (1,2):
        current=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{resumed['token']}'")
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{resumed['token']}',{number},'{{\"events\":[]}}'")
    assert service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{resumed['token']}'")['complete']
    done=service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{resumed['token']}'")
    assert done['retrieval_complete'] and done['pages']==3
    assert sql('select processing_status from public.user_narrator_source;').stdout.strip()=='succeeded'


def test_pg_lane_policy_preferences_and_cross_owner_fences(sql):
    identity=resolve(sql);project=identity['project_id']
    source=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001','Original memory'")
    lane=create_lane(sql,identity)
    claim=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert sql(as_user(f"select public.read_lifetime_memoir_lane_page('{lane}','{claim['token']}');",OTHER),check=False).returncode!=0
    fields=('schema_version','protocol','lane_id','token','snapshot_id','user_id','project_id','conversation_id','skill','locale','policy_epoch','preference_revision','source_high_water','event_high_water','page_number','root_digest','page_digest','input_digest','preferences','source','partition','events','coverage_round')
    fence={key:claim[key] for key in fields};fence['prior_outputs']=[]
    assert float(sql(f"set role service_role;set request.jwt.claim.sub = '{OWNER}';select public.lock_lifetime_memoir_lane_publication({literal(fence)});").stdout.strip())>0
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"name\":\"Changed\"}}') on conflict(user_id) do update set profile=excluded.profile;")
    assert sql(f"set role service_role;set request.jwt.claim.sub = '{OWNER}';select public.lock_lifetime_memoir_lane_publication({literal(fence)});",check=False).returncode!=0
    assert sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane}','{claim['token']}',0,'{{\"events\":[]}}','{claim['page_digest']}');",check=False).returncode!=0


def test_pg_composer_10000_dispositions_have_bounded_complete_root(sql):
    identity=resolve(sql);project=identity['project_id']
    sql(f"insert into public.user_memory_event(user_id,project_id,id,kind,status,data,change_sequence) select '{OWNER}',{literal(project)},'event-'||lpad(g::text,5,'0'),'event','unresolved','{{\"title\":\"Unresolved original claim\"}}',g from generate_series(1,10000) g;update public.user_memoir_project set event_sequence=10000 where user_id='{OWNER}' and project_id={literal(project)};")
    lane=create_lane(sql,identity,'composer')
    claim=service(sql,'claim_memoir_lane',f"'{lane}',1800")
    assert claim['partition']['id']=='event-00001' and len(json.dumps(claim).encode())<6000
    # All 10,000 authoritative positions must receive a durable disposition.
    # No live provider or fabricated source testimony participates.
    sql(f"""do $$ declare p jsonb; r jsonb; count integer:=0; begin
      loop
        p:=public.read_lifetime_memoir_lane_page('{lane}','{claim['token']}');
        exit when (p->>'complete')::boolean;
        if octet_length(p::text)>6000 then raise exception 'unbounded page';end if;
        r:=public.commit_lifetime_memoir_lane_page('{lane}','{claim['token']}',(p->>'page_number')::bigint,'{{"status":"no_authorized_evidence"}}',p->>'page_digest');
        count:=count+1;
        if count%100=0 then perform public.heartbeat_memoir_lane('{lane}','{claim['token']}');end if;
      end loop;
      if count<>10000 then raise exception 'coverage gap';end if;
      perform public.complete_lifetime_memoir_lane('{lane}','{claim['token']}');
    end $$;""")
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip()=='10000'
    assert sql('select state from public.user_lifetime_lane_snapshot;').stdout.strip()=='completed'
    head=rpc(sql,'read_lifetime_private_draft_head',literal(project))
    assert head['retrieval_complete'] and head['status']=='insufficient_context'


def test_composer_partition_retains_absolute_original_span_and_current_identity():
    from apps.api.lifetime_memory_composer import _compose
    from test_canonical_composer_provenance import controlled_draft
    current=page('composer',index=4)
    current['source']['project_id']='project'
    current['source']['id']='original'
    current['partition']=dict(id='canonical-home',revision=9,kind='event',life_stage='unplaced',
        status='active',title='童年',source_refs=[dict(source_id='original',version=1,
            quote=current['source']['text'],char_start=8192,char_end=8199)])
    calls=[]
    class Broker:
        async def rpc(self,name,**payload):
            if name=='read_lifetime_memoir_lane_page':return current
            if name=='read_memoir_checkpoint':return None
            if name=='save_memoir_checkpoint':return True
            if name=='record_lifetime_lane_output':return True
            raise AssertionError(name)
    def model(request):
        incoming=json.loads(request.content);packet=json.loads(incoming['bounded_lane']['packet'])['payload'];phase=incoming['composer_phase'];calls.append(phase)
        if phase=='prepare': result=dict(event_id='canonical-home',context='童年',source_refs=current['partition']['source_refs'])
        elif phase=='draft':
            assert packet['request']['context']['lifetime_page']['snapshot_complete'] is False
            assert packet['request']['events'][0]['id']=='canonical-home'
            assert packet['request']['sources'][0]['text']==current['source']['text']
            result=controlled_draft(packet,current['source']['text'],'童年')
        else:result=dict(ready_for_user_review=True,publication_approved=False,findings=[])
        return httpx.Response(200,json={'reply':json.dumps(result,ensure_ascii=False)})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model),lane_publisher=Publisher())
    result=asyncio.run(_compose(current,worker))
    assert calls==['prepare','draft','review']
    assert result['status']=='ready' and result['sections'][0]['event_ids']==['canonical-home']
    assert result['sections'][0]['source_refs'][0]['char_start']==8192


def test_privacy_overflow_is_durable_pending_without_provider_call():
    current=page();current['preferences']['privacy_complete']=False
    class Broker:
        async def rpc(self,name,**payload):
            assert name=='defer_lifetime_memoir_lane'
            assert payload['p_reason']=='LIFETIME_PRIVACY_MAINTENANCE_REQUIRED'
            return dict(status='pending',error=payload['p_reason'])
    assert asyncio.run(execute_lifetime_lane(current,SimpleNamespace(broker=Broker())))['status']=='pending'


def seeded_composer(sql,*,size=1):
    identity=resolve(sql);project=identity['project_id']
    source=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001','I grew up in Chengde.'")
    ref=dict(source_id=source['id'],version=1,quote=source['text'],char_start=0,char_end=len(source['text']))
    proposal=dict(kind='event',title='Childhood',source_refs=[ref])
    rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal([{'id':source['id'],'version':1}])},{literal([proposal])}")
    lane=create_lane(sql,identity,'composer')
    claim=service(sql,'claim_memoir_lane',f"'{lane}',900")
    return identity,source,lane,claim


def section_result(claim,text='I grew up in Chengde.'):
    ref={key:claim['partition']['source_refs'][0][key] for key in ('source_id','version','char_start','char_end')}
    return dict(status='ready',validation={'ok':True},review={'ready_for_user_review':True,'publication_approved':False,'findings':[]},
        sections=[dict(id='part',event_ids=[claim['partition']['id']],source_refs=[ref],content=text)],
        preview={'id':'preview','kind':'sample_chapter','title':'Childhood','text':text,'outline':[],'source_memory_ids':[ref['source_id']],'locale':claim['locale']})


def test_pg_composer_root_readback_never_exposes_unfinished_or_forged_sections(sql):
    identity,source,lane,claim=seeded_composer(sql)
    project=identity['project_id'];result=section_result(claim)
    bad=copy.deepcopy(result);bad['sections'][0]['source_refs'][0]['char_end']-=1
    assert sql(f"set role service_role; select public.commit_lifetime_memoir_lane_page('{lane}','{claim['token']}',0,{literal(bad)},'{claim['page_digest']}');",check=False).returncode!=0
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,{literal(result)}")
    assert rpc(sql,'read_lifetime_private_draft_head',literal(project))['preview'] is None
    root=service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    head=rpc(sql,'read_lifetime_private_draft_head',literal(project))
    assert head['status']=='ready' and head['preview']['text']==result['preview']['text']
    assert head['root_digest']==root['root_digest']
    full=rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{root['snapshot_id']}'")
    assert full['complete'] and full['records'][0]['event_id']==claim['partition']['id']
    assert rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{root['snapshot_id']}'",owner=OTHER,check=False).returncode!=0
    assert rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{root['snapshot_id']}','forged-cursor'",check=False).returncode!=0
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{source['id']}',1,'withdraw',null")
    assert rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{root['snapshot_id']}'",check=False).returncode!=0
    assert sql('select count(*) from public.user_lifetime_memoir_section;').stdout.strip()=='0'


def test_pg_stale_snapshot_invalidation_keeps_committed_chunk_cursor(sql):
    identity=resolve(sql);project=identity['project_id']
    rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001',{literal('中'*5000)}")
    lane=create_lane(sql,identity);first=service(sql,'claim_memoir_lane',f"'{lane}',900")
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,'{{\"events\":[]}}'")
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"preferred_language\":\"zh-CN\"}}') on conflict(user_id) do update set profile=excluded.profile;")
    assert sql('select state from public.user_lifetime_lane_snapshot;').stdout.strip()=='stale'
    second=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert second['snapshot_id']!=first['snapshot_id'] and second['core_start']==2048


def test_whole_source_recording_veto_after_window_is_preserved():
    text='I grew up in Chengde.'
    current=page(text=text)
    original={**current['source'],'text':text+' filler '*500+' Please do not add anything to my timeline.'}
    proposal={'events':[dict(kind='event',title='Childhood',source_refs=[dict(source_id='source',version=1,quote=text,char_start=0,char_end=len(text))])]}
    assert extraction_events(proposal,current,original)==[]


def test_pg_unrelated_approved_prose_survives_incremental_changes_and_withdrawal(sql):
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id']
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,{literal(section_result(first))}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    sql('update public.user_lifetime_memoir_section set approved=true,human_locked=true;')
    before=sql('select bundle::text from public.user_lifetime_memoir_section;').stdout.strip()
    new=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000002','Later I moved to Sydney.'")
    ref=dict(source_id=new['id'],version=1,quote=new['text'],char_start=0,char_end=len(new['text']))
    rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal([{'id':new['id'],'version':1}])},{literal([dict(kind='event',title='Sydney',source_refs=[ref])])}")
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    second=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert second['partition']['id']!=first['partition']['id']
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{second['token']}',0,{literal(section_result(second,new['text']))}")
    assert service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{second['token']}'")['complete']
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{second['token']}'")
    assert sql('select bundle::text from public.user_lifetime_memoir_section where approved;').stdout.strip()==before
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{new['id']}',1,'withdraw',null")
    assert sql('select count(*) from public.user_lifetime_memoir_section;').stdout.strip()=='1'
    assert sql('select bundle::text from public.user_lifetime_memoir_section;').stdout.strip()==before


def test_pg_exact_engine_envelope_holds_real_publication_fence(sql):
    import psycopg
    from apps.api.lifetime_memory_lane_engine import LaneFence,LanePublication,lane_extraction_packet,build_bounded_lane_input
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    identity=resolve(sql);project=identity['project_id']
    source=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001','I grew up in Chengde.'")
    data={'text':source['text'],'assertion':'asserted','source_refs':[{'source_id':source['id'],'version':1,'char_start':0,'char_end':len(source['text']),'quote':source['text']}]}
    sql(f"insert into public.user_lifetime_continuity(user_id,conversation_id,record_id,kind,revision,policy_epoch,data,last_source_sequence) values('{OWNER}','{identity['conversation_id']}','fixture','unresolved_reference',1,1,{literal(data)},1);")
    lane=create_lane(sql,identity);claim=service(sql,'claim_memoir_lane',f"'{lane}',900")
    fence=LaneFence.model_validate({key:claim[key] for key in LaneFence.model_fields if key in claim})
    bounded=build_bounded_lane_input(claim,phase='extract',packet=lane_extraction_packet(fence),budget=lane_model_budget())
    actual=bounded.model_dump(mode='json')['fence']
    assert actual['schema_version']==1 and actual['source']['text']==source['text']
    command=sql.command
    dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    async def scenario():
        publisher=LanePublication(dsn,authenticated_owner=OWNER)
        async with publisher.guard(actual):pass
        with pytest.raises(PublicationUnavailable):
            async with publisher.guard({**actual,'input_digest':'f'*64}):pass
        wrong=copy.deepcopy(actual);wrong['source']['text']='Other owner private bytes'
        with pytest.raises(PublicationUnavailable):
            async with publisher.guard(wrong):pass
        with pytest.raises(PublicationUnavailable):
            async with LanePublication(dsn,authenticated_owner=OTHER).guard(actual):pass
        editor=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        try:
            await editor.execute('set role authenticated')
            await editor.execute("select set_config('request.jwt.claim.sub',%s,false)",(OWNER,))
            async with publisher.guard(actual):
                changing=asyncio.create_task(editor.execute("select public.change_user_narrator_source(%s,%s,1,'withdraw',null)",(project,source['id'])))
                async with asyncio.timeout(1):
                    while True:
                        blockers=await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(editor.info.backend_pid,))).fetchone()
                        if blockers[0]:break
                        assert not changing.done()
            await changing
            with pytest.raises(PublicationUnavailable):
                async with publisher.guard(actual):pass
        finally:
            await editor.close();await observer.close()
    asyncio.run(scenario())


def test_pg_prior_output_marker_cannot_be_replayed_on_another_page(sql):
    from apps.api.lifetime_memory_lane_engine import LaneFence,lane_artifact_digest
    identity=resolve(sql);project=identity['project_id']
    rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000001',{literal('中'*5000)}")
    lane=create_lane(sql,identity);claim=service(sql,'claim_memoir_lane',f"'{lane}',900")
    digest=lane_artifact_digest('prepare',{'event_id':'synthetic','context':'Synthetic preparation','source_refs':[]})
    assert sql(f"set role service_role; select public.record_lifetime_lane_output('{lane}','{claim['token']}',0,'prepare','{digest}','{claim['page_digest']}');").stdout.strip()=='t'
    fence=LaneFence.model_validate({key:claim[key] for key in LaneFence.model_fields if key in claim}).model_dump(mode='json')
    fence['prior_outputs']=[{'schema_version':1,'phase':'prepare','digest':digest}]
    assert rpc(sql,'lock_lifetime_memoir_lane_publication',literal(fence))>0
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,'{{\"events\":[]}}'")
    current=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}'")
    second=LaneFence.model_validate({key:current[key] for key in LaneFence.model_fields if key in current}).model_dump(mode='json')
    second['prior_outputs']=fence['prior_outputs']
    assert rpc(sql,'lock_lifetime_memoir_lane_publication',literal(second),check=False).returncode!=0


@pytest.mark.parametrize('privacy_changed',[False,True])
@pytest.mark.parametrize('protection',['section','manuscript'])
def test_pg_protected_section_survives_preference_snapshot_and_exposes_only_safe_proposal(sql,privacy_changed,protection):
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id']
    original=section_result(first)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,{literal(original)}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    if protection=='section':sql('update public.user_lifetime_memoir_section set approved=true;')
    else:sql('update public.user_memoir_manuscript set human_locked=true;')
    before=sql('select bundle::text from public.user_lifetime_memoir_section;').stdout.strip()
    if privacy_changed:
        sql(f"insert into public.user_profile(user_id,profile) values('{OWNER}','{{\"memory_preferences\":{{\"excluded_topics\":[\"childhood\"]}}}}') on conflict(user_id) do update set profile=excluded.profile;")
    else:
        sql(f"update public.user_lifetime_conversation set preference_revision=preference_revision+1 where user_id='{OWNER}';")
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    second=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert not second['reuse']
    candidate=section_result(second,'A revised supported draft, awaiting approval.')
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{second['token']}',0,{literal(candidate)}")
    outcome=service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{second['token']}'")
    assert outcome['status']=='proposed'
    assert sql(f"select bundle::text from public.user_lifetime_memoir_section where snapshot_id='{first['snapshot_id']}';").stdout.strip()==before
    head=rpc(sql,'read_lifetime_private_draft_head',literal(project))
    assert head['snapshot_state']=='proposed' and head['approval_required'] is True and head['publication_approved'] is False
    assert head['proposed_preview']['text']==candidate['preview']['text']
    assert head['original_withheld'] is privacy_changed
    if privacy_changed:assert head['preview'] is None
    else:assert head['preview']==original['preview']
    assert sql(f"select revision from public.user_memoir_manuscript where user_id='{OWNER}';").stdout.strip()=='1'


def test_pg_legacy_protected_manuscript_requires_explicit_migration(sql):
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id']
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    sql(f"insert into public.user_memoir_manuscript(user_id,project_id,locale,revision,human_locked,bundle) values('{OWNER}',{literal(project)},'en-AU',4,true,'{{\"preview\":{{\"text\":\"Protected original prose\"}}}}');")
    assert service(sql,'claim_memoir_lane',f"'{lane}',900") is None
    head=rpc(sql,'read_lifetime_private_draft_head',literal(project))
    assert head['error']=='LIFETIME_LEGACY_MANUSCRIPT_MIGRATION_REQUIRED'
    assert head['retrieval_complete'] is False and head['preview'] is None
    assert sql(f"select bundle->'preview'->>'text' from public.user_memoir_manuscript where user_id='{OWNER}';").stdout.strip()=='Protected original prose'


def test_pg_timeline_candidates_keep_old_active_interview_identity_bounded(sql):
    identity=resolve(sql);project=identity['project_id'];turn='00000000-0000-4000-8000-000000000001'
    source=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{turn}','We often went there with my parents.'")
    sql(f"""insert into public.user_memory_event(user_id,project_id,id,kind,status,data,change_sequence)
      select '{OWNER}',{literal(project)},'event-'||lpad(g::text,5,'0'),'event','active','{{"title":"Canonical identity","temporal":{{"expression":"unknown","precision":"unknown","basis":[]}}}}',g from generate_series(1,100) g;
      update public.user_memoir_project set event_sequence=100 where user_id='{OWNER}' and project_id={literal(project)};
      insert into public.user_interview_turn(user_id,project_id,client_turn_id,sequence,source_id,source_version,source_sequence,input_hash,kind,policy_epoch)
      values('{OWNER}',{literal(project)},'{turn}',1,'{source['id']}',1,1,'synthetic','narrator_chat',1);
      insert into public.user_interview_plan(user_id,project_id,client_turn_id,sequence,plan)
      values('{OWNER}',{literal(project)},'{turn}',1,'{{"active_event_id":"event-00001"}}');""")
    lane=create_lane(sql,identity);claim=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert len(claim['events'])==8
    assert claim['events'][0]['id']=='event-00001'
    assert claim['events'][0]['active_interview_context'] is True
    ref=dict(source_id=source['id'],version=1,quote=source['text'],char_start=0,char_end=len(source['text']))
    event=dict(existing_id='event-00001',expected_revision=1,kind='event',title='Canonical identity',source_refs=[ref])
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,{literal({'events':[event]})}")
    assert sql(f"select revision from public.user_memory_event where user_id='{OWNER}' and id='event-00001';").stdout.strip()=='2'
    assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='100'


def test_pg_saved_editions_are_selected_without_mutating_conversation_language(sql):
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id']
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,{literal(section_result(first))}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    assert rpc(sql,'set_lifetime_draft_edition',f"{literal(project)},'zh-CN'")['status']=='pending'
    second=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert second['locale']=='zh-CN' and second['preferences']['language']=='en-AU'
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{second['token']}',0,{literal(section_result(second,'我在承德长大。'))}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{second['token']}'")
    assert rpc(sql,'read_lifetime_private_draft_head',literal(project))['locale']=='en-AU'
    chinese=rpc(sql,'read_lifetime_private_draft_head',f"{literal(project)},'zh-CN'")
    assert chinese['locale']=='zh-CN' and chinese['preview']['text']=='我在承德长大。'
    assert rpc(sql,'read_lifetime_pinned',f"'{identity['conversation_id']}'")['language']=='en-AU'


@pytest.mark.parametrize('accept',[False,True])
def test_pg_proposal_decision_is_current_root_cas_and_never_grants_publication(sql,accept):
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id'];original=section_result(first)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,{literal(original)}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    sql('update public.user_lifetime_memoir_section set approved=true,human_locked=true;')
    sql(f"update public.user_lifetime_conversation set preference_revision=preference_revision+1 where user_id='{OWNER}';update public.user_memoir_lane set pending=true where id='{lane}';")
    second=service(sql,'claim_memoir_lane',f"'{lane}',900");candidate=section_result(second,'A supported proposal awaiting owner approval.')
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{second['token']}',0,{literal(candidate)}")
    root=service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{second['token']}'")
    view=rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{root['snapshot_id']}'")
    row=view['records'][0]
    args=f"{literal(project)},'{root['snapshot_id']}','{root['root_digest']}',{literal(row['id'])},'{row['proposal_digest']}',{'true' if accept else 'false'}"
    assert rpc(sql,'set_lifetime_private_draft_proposal',args,owner=OTHER,check=False).returncode!=0
    assert rpc(sql,'set_lifetime_private_draft_proposal',args.replace(root['root_digest'],'0'*64),check=False).returncode!=0
    saved=rpc(sql,'set_lifetime_private_draft_proposal',args)
    assert saved['status']==('accepted' if accept else 'rejected') and saved['approval_required'] is False
    assert saved['root_digest']!=root['root_digest'] and saved['publication_approved'] is False
    assert rpc(sql,'set_lifetime_private_draft_proposal',args,check=False).returncode!=0
    head=rpc(sql,'read_lifetime_private_draft_head',literal(project))
    assert head['snapshot_state']=='completed' and head['revision']==2 and head['proposed_preview'] is None
    assert head['preview']==(candidate if accept else original)['preview']
    stored=json.loads(sql(f"select json_build_object('approved',approved,'human_locked',human_locked,'proposal',proposal) from public.user_lifetime_memoir_section where snapshot_id='{second['snapshot_id']}';").stdout.strip())
    assert stored==dict(approved=True,human_locked=True,proposal=None)
    assert json.loads(sql(f"select bundle from public.user_lifetime_memoir_section where snapshot_id='{first['snapshot_id']}';").stdout.strip())==original


def test_pg_edition_selection_cannot_create_eligibility_or_interrupt_active_lease(sql):
    identity=resolve(sql);project=identity['project_id']
    result=rpc(sql,'set_lifetime_draft_edition',f"{literal(project)},'zh-CN'")
    assert result['error']=='LIFETIME_DRAFT_NOT_ELIGIBLE'
    assert sql('select count(*) from public.user_memoir_lane;').stdout.strip()=='0'
    lane=create_lane(sql,identity,'composer')
    before=sql(f"select json_build_object('target_source',target_source,'target_event',target_event,'target_milestone',target_milestone) from public.user_memoir_lane where id='{lane}';").stdout.strip()
    claim=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert rpc(sql,'set_lifetime_draft_edition',f"{literal(project)},'zh-CN'",check=False).returncode!=0
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    assert rpc(sql,'set_lifetime_draft_edition',f"{literal(project)},'zh-CN'",owner=OTHER,check=False).returncode!=0
    assert rpc(sql,'set_lifetime_draft_edition',f"{literal(project)},'zh-CN'")['status']=='pending'
    assert sql(f"select json_build_object('target_source',target_source,'target_event',target_event,'target_milestone',target_milestone) from public.user_memoir_lane where id='{lane}';").stdout.strip()==before
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='5'
    assert rpc(sql,'read_lifetime_pinned',f"'{identity['conversation_id']}'")['language']=='en-AU'


def test_pg_normal_event_evidence_addition_cannot_replace_approved_prose(sql):
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id'];original=section_result(first)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,{literal(original)}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    sql('update public.user_lifetime_memoir_section set approved=true;')
    new=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000002','My parents often took me there.'")
    ref=dict(source_id=new['id'],version=1,quote=new['text'],char_start=0,char_end=len(new['text']))
    event=dict(existing_id=first['partition']['id'],expected_revision=1,kind='event',title='Childhood',source_refs=[ref])
    rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal([{'id':new['id'],'version':1}])},{literal([event])}")
    assert json.loads(sql('select bundle from public.user_lifetime_memoir_section;').stdout.strip())==original
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    current=service(sql,'claim_memoir_lane',f"'{lane}',900");snapshot=current['snapshot_id'];token=current['token']
    while not current['complete']:
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{token}',{current['page_number']},{literal(section_result(current,'A revised supported description.'))}")
        current=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{token}'")
    assert service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{token}'")['status']=='proposed'
    saved=json.loads(sql(f"select json_build_object('bundle',bundle,'proposal',proposal,'approved',approved,'event_revision',event_revision) from public.user_lifetime_memoir_section where snapshot_id='{snapshot}' and source_id='{source['id']}';").stdout.strip())
    assert saved['bundle']==original and saved['proposal']['preview']['text']=='A revised supported description.'
    assert saved['approved'] is True and saved['event_revision']==2
    first_page=rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{snapshot}',null,1")
    assert not first_page['complete']
    full=rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{snapshot}'")
    actionable=next(row for row in full['records'] if row['proposal_digest'])
    rpc(sql,'set_lifetime_private_draft_proposal',f"{literal(project)},'{snapshot}','{full['root_digest']}',{literal(actionable['id'])},'{actionable['proposal_digest']}',false")
    assert rpc(sql,'read_lifetime_private_draft_page',f"{literal(project)},'{snapshot}',{literal(first_page['next_cursor'])},1",check=False).returncode!=0


def test_pg_actual_outer_send_fences_proposal_decisions_without_policy_churn(sql):
    import psycopg
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from apps.api.lifetime_memory_reads import ReadSnapshot,ReadJSONResponse,ReadPublication
    from apps.api.lifetime_memory_publication import PublicationUnavailable
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id'];original=section_result(first)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,{literal(original)}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    sql('update public.user_lifetime_memoir_section set approved=true;')
    sql(f"update public.user_lifetime_conversation set preference_revision=preference_revision+1 where user_id='{OWNER}';update public.user_memoir_lane set pending=true where id='{lane}';")
    second=service(sql,'claim_memoir_lane',f"'{lane}',900");candidate=section_result(second,'Pending proposal sentinel')
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{second['token']}',0,{literal(candidate)}")
    root=service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{second['token']}'")
    fence=rpc(sql,'capture_lifetime_read_fence',literal(project))
    body=rpc(sql,'read_lifetime_private_draft_head',literal(project));row=body['first_record']
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    app=create_app(MemoryStore());snapshot=ReadSnapshot(body,fence)
    @app.get('/proposal-publication-boundary')
    async def route():return ReadJSONResponse(snapshot,publisher=ReadPublication(dsn,authenticated_owner=OWNER))
    async def scenario():
        entered=asyncio.Event();release=asyncio.Event();messages=[]
        async def receive():await asyncio.Event().wait()
        async def send(message):
            if b'Pending proposal sentinel' in message.get('body',b''):
                entered.set();await release.wait()
            messages.append(message)
        scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1','method':'GET','scheme':'http',
            'path':'/proposal-publication-boundary','raw_path':b'/proposal-publication-boundary','query_string':b'',
            'headers':[(b'x-request-id',b'proposal-fence')],'client':('127.0.0.1',1234),'server':('test',80)}
        sending=asyncio.create_task(app(scope,receive,send))
        async with asyncio.timeout(3):await entered.wait()
        editor=await psycopg.AsyncConnection.connect(dsn,autocommit=True);observer=await psycopg.AsyncConnection.connect(dsn,autocommit=True)
        try:
            await editor.execute('set role authenticated');await editor.execute("select set_config('request.jwt.claim.sub',%s,false)",(OWNER,))
            deciding=asyncio.create_task(editor.execute('select public.set_lifetime_private_draft_proposal(%s,%s,%s,%s,%s,false)',
                (project,root['snapshot_id'],root['root_digest'],row['id'],row['proposal_digest'])))
            async with asyncio.timeout(1):
                while True:
                    blocked=await (await observer.execute('select cardinality(pg_blocking_pids(%s))',(editor.info.backend_pid,))).fetchone()
                    if blocked[0]:break
                    assert not deciding.done()
            release.set();await sending;await deciding
            messages.clear()
            with pytest.raises(PublicationUnavailable):await app(scope,receive,send)
            assert not any(b'Pending proposal sentinel' in message.get('body',b'') for message in messages)
        finally:
            release.set();sending.cancel();await asyncio.gather(sending,return_exceptions=True)
            await editor.close();await observer.close()
    asyncio.run(scenario())
    after=rpc(sql,'capture_lifetime_read_fence',literal(project))
    assert after['policy_epoch']==fence['policy_epoch'] and after['source_revision']==fence['source_revision']
    assert after['draft_revision']>fence['draft_revision']


def test_pg_cosmetic_lane_status_never_exposes_unfinished_root(sql):
    identity,source,lane,claim=seeded_composer(sql)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,{literal(section_result(claim))}")
    sql(f"update public.user_memoir_lane set pending=false,token=null,lease_until=null,run_deadline=null,error=null where id='{lane}';")
    head=rpc(sql,'read_lifetime_private_draft_head',literal(identity['project_id']))
    assert head['updating'] is False and head['status']=='pending'
    assert head['preview'] is None and head['retrieval_complete'] is False


def test_pg_actual_outer_send_rejects_event_revision_changed_after_capture(sql):
    from fastapi.testclient import TestClient
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from apps.api.lifetime_memory_reads import ReadSnapshot,ReadJSONResponse,ReadPublication
    identity,source,lane,claim=seeded_composer(sql);project=identity['project_id']
    new=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000002','My parents often took me there.'")
    fence=rpc(sql,'capture_lifetime_read_fence',literal(project))
    body=rpc(sql,'read_lifetime_collection_page',f"{literal(project)},'events'")
    assert body['events'][0]['title']=='Childhood'
    ref=dict(source_id=new['id'],version=1,quote=new['text'],char_start=0,char_end=len(new['text']))
    event=dict(existing_id=claim['partition']['id'],expected_revision=1,kind='event',title='Revised Childhood',source_refs=[ref])
    rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal([{'id':new['id'],'version':1}])},{literal([event])}")
    after=rpc(sql,'capture_lifetime_read_fence',literal(project))
    assert after['source_revision']==fence['source_revision'] and after['policy_epoch']==fence['policy_epoch']
    assert after['event_revision']>fence['event_revision']
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    app=create_app(MemoryStore());snapshot=ReadSnapshot(body,fence)
    @app.get('/event-publication-boundary')
    async def route():return ReadJSONResponse(snapshot,publisher=ReadPublication(dsn,authenticated_owner=OWNER))
    with TestClient(app,raise_server_exceptions=False) as client:
        response=client.get('/event-publication-boundary')
        assert response.status_code>=400 and 'Childhood' not in response.text


def test_pg_multisource_withdrawal_purges_exact_protected_dependency_before_epoch_bump(sql):
    identity,source,lane,first=seeded_composer(sql);project=identity['project_id']
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{first['token']}',0,{literal(section_result(first))}")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{first['token']}'")
    sql('update public.user_lifetime_memoir_section set approved=true;')
    for ordinal,text,existing in [(2,'My parents often took me there.',True),(3,'An unrelated account in Sydney.',False)]:
        new=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-{ordinal:012d}',{literal(text)}")
        ref=dict(source_id=new['id'],version=1,quote=text,char_start=0,char_end=len(text))
        event=dict(kind='event',title='Childhood' if existing else 'Sydney',source_refs=[ref])
        if existing:event.update(existing_id=first['partition']['id'],expected_revision=1)
        else:unrelated=new['id']
        rpc(sql,'apply_user_memory_events',f"{literal(project)},{literal([{'id':new['id'],'version':1}])},{literal([event])}")
    sql(f"update public.user_memoir_lane set pending=true where id='{lane}';")
    current=service(sql,'claim_memoir_lane',f"'{lane}',900");token=current['token']
    while not current['complete']:
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{token}',{current['page_number']},{literal(section_result(current,current['source']['text']))}")
        current=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{token}'")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane}','{token}'")
    sql('update public.user_lifetime_memoir_section set approved=true;')
    before=sql(f"select bundle::text from public.user_lifetime_memoir_section where source_id='{unrelated}' order by snapshot_id;").stdout
    assert before.strip()
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{source['id']}',1,'withdraw',null")
    assert sql(f"select count(*) from public.user_lifetime_memoir_section where source_id='{source['id']}';").stdout.strip()=='0'
    assert 'I grew up in Chengde.' not in sql('select bundle::text||coalesce(proposal::text,\'\') from public.user_lifetime_memoir_section;').stdout
    assert sql(f"select bundle::text from public.user_lifetime_memoir_section where source_id='{unrelated}' order by snapshot_id;").stdout==before


def test_pg_phase_checkpoints_bind_page_and_purge_with_exact_source(sql):
    identity,source,lane,claim=seeded_composer(sql);project=identity['project_id'];key='a'*64
    checkpoint=dict(event_id=claim['partition']['id'],context='Original restricted checkpoint words',source_refs=claim['partition']['source_refs'])
    assert sql(f"set role service_role;select public.save_memoir_checkpoint('{lane}','{claim['token']}','{key}','prepare',{literal(checkpoint)},'{claim['page_digest']}');").stdout.strip()=='t'
    assert service(sql,'read_memoir_checkpoint',f"'{lane}','{claim['token']}','{key}'")==checkpoint
    saved=json.loads(sql('select json_build_object(\'sources\',source_manifest,\'events\',event_manifest,\'snapshot\',lifetime_snapshot_id,\'page\',lifetime_page) from public.user_memoir_checkpoint;').stdout.strip())
    assert saved==dict(sources=[{'id':source['id'],'version':1}],events=[{'id':claim['partition']['id'],'revision':1}],snapshot=claim['snapshot_id'],page=0)
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}',0,{literal(section_result(claim))}")
    assert service(sql,'read_memoir_checkpoint',f"'{lane}','{claim['token']}','{key}'") is None
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{source['id']}',1,'withdraw',null")
    assert sql('select count(*) from public.user_memoir_checkpoint;').stdout.strip()=='0'


@pytest.mark.parametrize('restart',[False,True])
def test_pg_real_composer_chain_registers_artifacts_and_saves_bounded_checkpoint_manifests(sql,restart):
    from apps.api.lifetime_memory_lane_engine import LanePublication,BoundedLaneInput
    from test_canonical_composer_provenance import controlled_draft
    identity,source,lane,claim=seeded_composer(sql);project=identity['project_id'];phases=[];first_review=True
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    class Broker:
        async def rpc(self,name,**payload):
            args=','.join(f'{key}=>{literal(value)}' if not isinstance(value,int) else f'{key}=>{value}' for key,value in payload.items())
            return json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())
    def model(request):
        nonlocal first_review
        wire=json.loads(request.content);bounded=BoundedLaneInput.model_validate(wire['bounded_lane'])
        phase=bounded.phase;payload=json.loads(bounded.packet)['payload'];phases.append(phase)
        if phase=='prepare':result=dict(event_id=claim['partition']['id'],context='Source-grounded preparation',source_refs=claim['partition']['source_refs'])
        elif phase=='draft':result=controlled_draft(payload,source['text'],'Childhood')
        else:
            if restart and first_review:
                first_review=False
                raise asyncio.CancelledError('Synthetic worker loss after persisted draft')
            result=dict(ready_for_user_review=True,publication_approved=False,findings=[])
        return httpx.Response(200,json={'reply':json.dumps(result)})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model),
        lane_publisher=LanePublication(dsn,authenticated_owner=OWNER))
    if restart:
        with pytest.raises(asyncio.CancelledError):asyncio.run(execute_lifetime_lane(claim,worker))
        service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
        renewed=service(sql,'claim_memoir_lane',f"'{lane}',900")
        assert renewed['token']!=claim['token'] and renewed['page_digest']!=claim['page_digest']
        assert renewed['input_digest']==claim['input_digest']
        claim=renewed
    result=asyncio.run(execute_lifetime_lane(claim,worker))
    assert result['status']=='saved' and phases==['prepare','draft','review']+(['review'] if restart else [])
    assert sql('select count(*) from public.user_lifetime_lane_output;').stdout.strip()=='3'
    assert sql('select bool_and(jsonb_array_length(source_manifest)=1 and jsonb_array_length(event_manifest)=1 and lifetime_page=0) from public.user_memoir_checkpoint;').stdout.strip()=='t'
    head=rpc(sql,'read_lifetime_private_draft_head',literal(project))
    assert head['preview']['text']==source['text'] and head['retrieval_complete']
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{source['id']}',1,'withdraw',null")
    assert sql('select count(*) from public.user_memoir_checkpoint;').stdout.strip()=='0'


@pytest.mark.parametrize('change',['preference','unrelated_policy'])
def test_pg_phase_checkpoint_pinned_context_is_discarded_on_any_fence_change(sql,change):
    identity,source,lane,claim=seeded_composer(sql);project=identity['project_id'];key='b'*64
    value={'request':{'context':{'preferences':{'known_continuity':['Private source-backed context']}}}}
    assert sql(f"set role service_role;select public.save_memoir_checkpoint('{lane}','{claim['token']}','{key}','compose',{literal(value)},'{claim['page_digest']}');").stdout.strip()=='t'
    if change=='preference':
        sql(f"update public.user_lifetime_conversation set preference_revision=preference_revision+1 where user_id='{OWNER}';")
    else:
        other=rpc(sql,'accept_user_narrator_source',f"{literal(project)},'00000000-0000-4000-8000-000000000002','Other context source'")
        rpc(sql,'change_user_narrator_source',f"{literal(project)},'{other['id']}',1,'withdraw',null")
    assert sql('select count(*) from public.user_memoir_checkpoint;').stdout.strip()=='0'
    assert sql(f"select status from public.user_narrator_source where id='{source['id']}';").stdout.strip()=='active'


def test_pg_checkpoint_resume_is_token_independent_but_commit_binds_exact_current_page(sql):
    from apps.api.lifetime_memory_lane_engine import LaneFence
    identity,source,lane,claim=seeded_composer(sql);project=identity['project_id'];key='c'*64;checkpoint={'context':'Grounded preparation'}
    assert sql(f"set role service_role;select public.save_memoir_checkpoint('{lane}','{claim['token']}','{key}','prepare',{literal(checkpoint)},'{claim['page_digest']}');").stdout.strip()=='t'
    assert sql(f"set role service_role;select public.record_lifetime_lane_output('{lane}','{claim['token']}',0,'prepare','{'d'*64}','{claim['page_digest']}');").stdout.strip()=='t'
    service(sql,'yield_lifetime_memoir_lane',f"'{lane}','{claim['token']}'")
    resumed=service(sql,'claim_memoir_lane',f"'{lane}',900")
    assert resumed['token']!=claim['token']
    assert service(sql,'read_memoir_checkpoint',f"'{lane}','{resumed['token']}','{key}'")==checkpoint
    fence=LaneFence.model_validate({key:resumed[key] for key in LaneFence.model_fields if key in resumed}).model_dump(mode='json')
    fence['prior_outputs']=[{'schema_version':1,'phase':'prepare','digest':'d'*64}]
    assert rpc(sql,'lock_lifetime_memoir_lane_publication',literal(fence))>0
    fact={'text':source['text'],'assertion':'asserted','source_refs':[{'source_id':source['id'],'version':1,'quote':source['text'],'char_start':0,'char_end':len(source['text'])}]}
    sql(f"insert into public.user_lifetime_continuity(user_id,conversation_id,record_id,kind,revision,policy_epoch,data,last_source_sequence) values('{OWNER}','{identity['conversation_id']}','new-hint','commitment',1,{resumed['policy_epoch']},{literal(fact)},1);")
    current=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{resumed['token']}'")
    assert current['preference_revision']==resumed['preference_revision'] and current['page_number']==resumed['page_number']
    assert current['page_digest']!=resumed['page_digest']
    assert service(sql,'read_memoir_checkpoint',f"'{lane}','{resumed['token']}','{key}'") is None
    stale=sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane}','{resumed['token']}',0,{literal(section_result(resumed))},'{resumed['page_digest']}');",check=False)
    assert stale.returncode!=0 and 'stale canonical page digest' in stale.stderr
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip()=='0'


def add_same_page_continuity(sql,identity,source,page):
    fact={'text':source['text'],'assertion':'asserted','source_refs':[{'source_id':source['id'],'version':1,'quote':source['text'],'char_start':0,'char_end':len(source['text'])}]}
    sql(f"insert into public.user_lifetime_continuity(user_id,conversation_id,record_id,kind,revision,policy_epoch,data,last_source_sequence) values('{OWNER}','{identity['conversation_id']}','late-model-hint','commitment',1,{page['policy_epoch']},{literal(fact)},1);")


@pytest.mark.parametrize('barrier',['record_lifetime_lane_output','save_memoir_checkpoint'])
def test_pg_model_reply_cannot_register_or_checkpoint_under_changed_same_page_context(sql,barrier):
    from apps.api.lifetime_memory_lane_engine import LanePublication,BoundedLaneInput,LaneFence,lane_artifact_digest
    identity,source,lane,claim=seeded_composer(sql);phases=[];changed=False
    command=sql.command;dsn=f"host={command[command.index('-h')+1]} port={command[command.index('-p')+1]} user=postgres dbname=postgres"
    artifact=dict(event_id=claim['partition']['id'],context='Old-context prepared output',source_refs=claim['partition']['source_refs'])
    class Broker:
        async def rpc(self,name,**payload):
            nonlocal changed
            if name==barrier and not changed:
                assert phases==['prepare']
                add_same_page_continuity(sql,identity,source,claim);changed=True
            args=','.join(f'{key}=>{literal(value)}' if not isinstance(value,int) else f'{key}=>{value}' for key,value in payload.items())
            return json.loads(sql(f"set role service_role;select coalesce(to_jsonb(public.{name}({args})),'null'::jsonb);").stdout.strip())
    def model(request):
        bounded=BoundedLaneInput.model_validate(json.loads(request.content)['bounded_lane']);phases.append(bounded.phase)
        assert bounded.phase=='prepare'
        return httpx.Response(200,json={'reply':json.dumps(artifact)})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model),
        lane_publisher=LanePublication(dsn,authenticated_owner=OWNER))
    with pytest.raises(RuntimeError):
        asyncio.run(execute_lifetime_lane(claim,worker))
    assert changed and phases==['prepare']
    assert sql('select count(*) from public.user_memoir_checkpoint;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_lane_page_receipt;').stdout.strip()=='0'
    current=service(sql,'read_lifetime_memoir_lane_page',f"'{lane}','{claim['token']}'")
    assert current['page_digest']!=claim['page_digest'] and current['page_number']==claim['page_number']
    fence=LaneFence.model_validate({key:current[key] for key in LaneFence.model_fields if key in current}).model_dump(mode='json')
    fence['prior_outputs']=[{'schema_version':1,'phase':'prepare','digest':lane_artifact_digest('prepare',artifact)}]
    denied=rpc(sql,'lock_lifetime_memoir_lane_publication',literal(fence),check=False)
    assert denied.returncode!=0 and 'derived lane output belongs' in denied.stderr
    if barrier=='record_lifetime_lane_output':
        assert sql('select count(*) from public.user_lifetime_lane_output;').stdout.strip()=='0'
    else:
        assert sql('select count(*) from public.user_lifetime_lane_output;').stdout.strip()=='1'


def test_real_composer_resume_reuses_completed_phases_after_lease_token_renewal():
    from apps.api.lifetime_memory_composer import _compose
    from test_canonical_composer_provenance import controlled_draft
    current=page('composer');source=current['source'];current['input_digest']='2'*64
    current['partition']=dict(id='event-resume',revision=1,kind='event',life_stage='unplaced',status='active',title='Childhood',
        source_refs=[dict(source_id=source['id'],version=source['version'],quote=source['text'],char_start=source['char_start'],char_end=source['char_end'])])
    phases=[];checkpoints={};first_review=True
    class Broker:
        async def rpc(self,name,**payload):
            if name=='read_memoir_checkpoint':return copy.deepcopy(checkpoints.get(payload['p_key']))
            if name=='save_memoir_checkpoint':checkpoints[payload['p_key']]=copy.deepcopy(payload['p_value']);return True
            if name=='record_lifetime_lane_output':return True
            raise AssertionError(name)
    def model(request):
        nonlocal first_review
        bounded=json.loads(request.content)['bounded_lane'];phase=bounded['phase'];packet=json.loads(bounded['packet'])['payload'];phases.append(phase)
        if phase=='prepare':result=dict(event_id=current['partition']['id'],context='Prepared once',source_refs=current['partition']['source_refs'])
        elif phase=='draft':result=controlled_draft(packet,source['text'],'Childhood')
        else:
            if first_review:first_review=False;raise asyncio.CancelledError('Synthetic worker loss after draft checkpoint')
            result=dict(ready_for_user_review=True,publication_approved=False,findings=[])
        return httpx.Response(200,json={'reply':json.dumps(result)})
    worker=SimpleNamespace(broker=Broker(),worker_url='https://synthetic.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(model),lane_publisher=Publisher())
    with pytest.raises(asyncio.CancelledError):asyncio.run(_compose(current,worker))
    assert phases==['prepare','draft','review']
    resumed={**copy.deepcopy(current),'token':'00000000-0000-4000-8000-000000000016','page_digest':'3'*64}
    result=asyncio.run(_compose(resumed,worker))
    assert result['status']=='ready' and phases==['prepare','draft','review','review']
