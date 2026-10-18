"""Shared logical B through real authenticated callers and canonical workers."""
import pytest
import asyncio
from uuid import uuid4

from test_conversation_attribution import Conversation, empty, episode
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import event_database, private_database, attachment_database
from test_shared_memory_events_postgres import sql


@pytest.fixture(autouse=True)
def reset_strategy(sql):
    sql('update public.lifetime_two_lane_rollout set strategy_enabled=false,strategy_shadow=false;')


def progress(conversation):
    response=conversation.client.get('/v1/story/readiness',params={'project_id':conversation.project})
    assert response.status_code==200,response.text
    return response.json()


def test_readiness_reports_saved_skill_with_actual_turn_and_source_coverage(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    conversation = Conversation(sql,tmp_path,monkeypatch,
        lambda packet: {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])]})
    with conversation.client:
        turn = str(uuid4())
        saved = conversation.say('I had a bicycle accident in Chengde.',turn=turn)
        conversation.drain()
        response = conversation.client.get('/v1/story/readiness',params={'project_id':conversation.project})
        assert response.status_code == 200,response.text
        steps = response.json()['skill_progress']['items']
        timeline = next(item for item in steps if item['skill'] == 'memoir-author-timeline')
        assert timeline['status'] == 'saved' and timeline['lane'] == 'B'
        assert timeline['execution'] == 'model' and timeline['model_invoked'] is True
        assert timeline['source_id'] == saved['accepted_source_id']
        assert timeline['client_turn_id'] == turn
        assert timeline['coverage_start'] == timeline['coverage_end'] == 1
        assert 'Chengde' not in str(steps)


def test_reply_only_is_skipped_not_model_applied_and_hidden_when_thinking_off(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    conversation=Conversation(sql,tmp_path,monkeypatch,empty,work='reply_only')
    with conversation.client:
        conversation.say('Thank you.')
        assert any(step['status']=='queued' for step in progress(conversation)['skill_progress']['items'])
        conversation.drain()
        steps=progress(conversation)['skill_progress']['items']
        assert all(step['status']=='skipped' and not step['model_invoked'] for step in steps)
        assert conversation.admissions==[]
        monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','0')
        assert 'skill_progress' not in progress(conversation)


@pytest.mark.parametrize('mode',['comfort','explore','shape'])
def test_game_uses_delivered_A_not_B_plan_and_stays_unavailable(sql,tmp_path,monkeypatch,mode):
    conversation=Conversation(sql,tmp_path,monkeypatch,empty,strategy=mode)
    with conversation.client:
        conversation.say('In Chengde I repaired a bicycle.')
        assert progress(conversation)['current_mode']['mode']==mode
        conversation.drain()
        assert [phase for phase,_ in conversation.admissions]==['profile','extract']
        # A newer background plan cannot rewrite the delivered reply's mode.
        sql("update public.user_lifetime_interview_strategy set data=jsonb_set(data,'{strategy}','\"shape\"');")
        assert progress(conversation)['current_mode']['mode']==mode
        result=conversation.client.post('/v1/story/game',json={'project_id':conversation.project})
        assert result.status_code==200,result.text
        assert result.json()['reason']==('integration_unavailable' if mode=='shape' else 'shape_required')
        assert result.json()['available'] is False
        assert conversation.client.post('/v1/story/game',json={'project_id':conversation.project,'mode':'shape'}).status_code==422
        sql('update public.user_lifetime_strategy_outcome set delivered=false;')
        assert progress(conversation)['current_mode'] is None
        assert conversation.client.post('/v1/story/game',json={'project_id':conversation.project}).json()['reason']=='current_decision_required'
        sql('update public.user_lifetime_strategy_outcome set delivered=true; update public.lifetime_two_lane_rollout set strategy_enabled=false;')
        assert progress(conversation)['current_mode'] is None
        sql('update public.lifetime_two_lane_rollout set strategy_enabled=true;')
        assert progress(conversation)['current_mode']['mode']==mode
        sql('update public.user_lifetime_conversation set preference_revision=preference_revision+1;')
        assert progress(conversation)['current_mode'] is None


def test_blocked_B_progress_is_late_correlated_and_does_not_block_A(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    entered=None
    release=None
    async def extract(packet):
        entered.set()
        await release.wait()
        return {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        saved=conversation.say('I had a bicycle accident.')
        async def run():
            nonlocal entered,release
            entered,release=asyncio.Event(),asyncio.Event()
            lane=sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
            task=asyncio.create_task(conversation.worker.execute_lane(lane))
            try:
                await asyncio.wait_for(entered.wait(),10)
                live=await asyncio.to_thread(progress,conversation)
                step=next(item for item in live['skill_progress']['items'] if item['skill']=='memoir-author-timeline')
                assert step['status']=='running' and not step['model_invoked']
                place=next(item for item in live['skill_progress']['items'] if item['skill']=='memoir-place-journey')
                assert place['status']=='running' and place['execution']=='embedded'
                # A accepts/delivers another useful reply while B's provider is held.
                reply=await asyncio.to_thread(conversation.say,'I later repaired that bicycle.')
                assert reply['conversation_saved'] and reply['reply']
            finally:
                release.set()
                await task
        asyncio.run(run())
        conversation.drain()
        steps=progress(conversation)['skill_progress']['items']
        assert any(step['source_id']==saved['accepted_source_id'] and step['status']=='saved' for step in steps)


def test_slow_photo_runner_cannot_hold_A_or_memory_and_cache_is_not_a_new_call(sql,tmp_path,monkeypatch):
    import threading
    from apps.api import place_photo_pages
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL',raising=False)
    entered,release=threading.Event(),threading.Event()
    calls=[]
    def search(place,period,**unused):
        calls.append((place,period))
        entered.set()
        assert release.wait(20)
        return []
    monkeypatch.setattr(place_photo_pages,'search_place_photos',search)
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    with conversation.client:
        saved=conversation.say('In Hobart I repaired a bicycle.')
        turn=sql('select client_turn_id from public.user_narrator_source limit 1;').stdout.strip()
        path=f'/v1/agent/places/{conversation.project}/photos'
        params={'place':'Hobart','period':'1980s'}
        headers={'X-Memoir-Progress-Turn':turn}
        async def run():
            task=asyncio.create_task(asyncio.to_thread(conversation.client.get,path,params=params,headers=headers))
            try:
                assert await asyncio.to_thread(entered.wait,10)
                await asyncio.to_thread(conversation.say,'I painted the shed blue.')
                await asyncio.to_thread(conversation.drain)
                steps=(await asyncio.to_thread(progress,conversation))['skill_progress']['items']
                assert any(step['skill']=='memoir-author-timeline' and step['status']=='saved' for step in steps)
                assert not task.done()
            finally:
                release.set()
                response=await task
            assert response.status_code==200,response.text
            assert response.json()['skill_progress']['execution']=='provider'
        asyncio.run(run())
        count=len(calls)
        cached=conversation.client.get(path,params=params,headers=headers)
        assert cached.status_code==200,cached.text
        assert len(calls)==count
        assert cached.json()['skill_progress']['status']=='cached'
        steps=progress(conversation)['skill_progress']['items']
        photo=next(step for step in steps if step['skill']=='memoir-place-photo-research')
        assert photo['execution']=='cache' and not photo['model_invoked']
        assert photo['source_id']==saved['accepted_source_id']
        groups=conversation.client.post(f'/v1/agent/places/{conversation.project}/groups',json={
            'client_turn_id':turn,'places':[{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],
                'granularity':'city','latitude':-42.88,'longitude':147.33}]})
        assert groups.status_code==200,groups.text
        assert groups.json()['skill_progress']['execution']=='deterministic'
        assert len(conversation.admissions)==3 # two timeline sources + first profile, no enrichment model


@pytest.mark.parametrize('service',['photos','grouping'])
def test_completed_optional_services_do_not_keep_readiness_pending(sql,tmp_path,monkeypatch,service):
    from apps.api import place_photo_pages
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL',raising=False)
    monkeypatch.setattr(place_photo_pages,'search_place_photos',lambda *args,**kwargs:[])
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    with conversation.client:
        conversation.say('In Hobart I repaired a bicycle.')
        conversation.drain()
        assert progress(conversation)['pending'] is False
        if service=='photos':
            response=conversation.client.get(f'/v1/agent/places/{conversation.project}/photos',
                params={'place':'Hobart','period':'1980s'})
        else:
            response=conversation.client.post(f'/v1/agent/places/{conversation.project}/groups',json={
                'places':[{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],
                    'granularity':'city','latitude':-42.88,'longitude':147.33}]})
        assert response.status_code==200,response.text
        assert response.json()['skill_progress']['status']=='completed'
        view=progress(conversation)
        assert any(item['phase']==service and item['status']=='completed' for item in view['skill_progress']['items'])
        assert view['skill_progress']['pending'] is False
        assert view['pending'] is False
        conversation.say('I later painted the shed blue.')
        assert progress(conversation)['pending'] is True
        conversation.drain()
        assert progress(conversation)['pending'] is False


def test_completed_optional_service_receipts_do_not_expire(sql,tmp_path,monkeypatch):
    from apps.api import place_photo_pages
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL',raising=False)
    monkeypatch.setattr(place_photo_pages,'search_place_photos',lambda *args,**kwargs:[])
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    with conversation.client:
        conversation.say('In Hobart I repaired a bicycle.')
        turn=sql('select client_turn_id from public.user_narrator_source limit 1;').stdout.strip()
        photo=conversation.client.get(f'/v1/agent/places/{conversation.project}/photos',
            params={'place':'Hobart','period':'1980s'},headers={'X-Memoir-Progress-Turn':turn})
        groups=conversation.client.post(f'/v1/agent/places/{conversation.project}/groups',json={
            'client_turn_id':turn,'places':[{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],
                'granularity':'city','latitude':-42.88,'longitude':147.33}]})
        assert photo.status_code==groups.status_code==200
        assert photo.json()['skill_progress']['status']==groups.json()['skill_progress']['status']=='completed'
        sql("update public.user_background_skill_work set updated_at=clock_timestamp()-interval '6 minutes';")
        steps=[item for item in progress(conversation)['skill_progress']['items'] if item['phase'] in {'photos','grouping'}]
        assert len(steps)==2
        assert all(item['status']=='completed' for item in steps),steps
        # Only genuinely unfinished optional work is an interrupted operation.
        sql("update public.user_background_skill_work set status='running' where phase='grouping';")
        interrupted=next(item for item in progress(conversation)['skill_progress']['items'] if item['phase']=='grouping')
        assert interrupted['status']=='failed' and interrupted['reason']=='interrupted'


def test_only_existing_profile_and_composer_schedules_advance_on_round_milestones(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'receipts.sqlite3'))
    monkeypatch.setenv('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE','5')
    def extract(packet):
        if 'prior' in packet:return packet['prior']
        return empty(packet)
    conversation=Conversation(sql,tmp_path,monkeypatch,extract)
    from apps.api import agent_routes
    original_storage=agent_routes.authenticated_storage
    def paid_storage(authorization):
        storage=original_storage(authorization)
        storage.story_entitlement=lambda:{'status':'paid','plan_key':'family_memoir_v1'}
        return storage
    monkeypatch.setattr(agent_routes,'authenticated_storage',paid_storage)
    with conversation.client:
        for number in range(1,31):
            conversation.say(f'I repaired bicycle number {number} in our shed.')
            before=len(conversation.admissions)
            conversation.drain()
            new=conversation.admissions[before:]
            assert any(phase=='extract' for phase,_ in new),(number,conversation.last_db_error)
            assert any(phase=='profile' for phase,_ in new)==(number in {1,5,10,20,30})
            conversation.deliver_receipts()
            target=sql("select coalesce(max(target_milestone),0) from public.user_memoir_lane where skill='composer';").stdout.strip()
            assert int(target)==number//5*5
        profiles=[packet['profile_context']['target_round'] for phase,packet in conversation.admissions if phase=='profile']
        assert set(profiles)=={1,5,10,20,30}
        assert not any(phase in {'photos','grouping','historical','family','game'} for phase,_ in conversation.admissions)
        page=progress(conversation)['skill_progress']
        mapped=progress(conversation)['skill_execution_map']
        assert len(mapped)==9
        assert {item['name'] for item in mapped if item['trigger']=='periodic'}=={'memoir-composer','memoir-memory-context'}
        assert page['truncated'] and page['next_cursor']
        items=[]
        while True:
            items.extend(item for item in page['items'] if item['phase']!='queue')
            if not page['next_cursor']:break
            response=conversation.client.get('/v1/story/skill-progress',params={'project_id':conversation.project,'cursor':page['next_cursor']})
            assert response.status_code==200,response.text
            page=response.json()
        assert len({item['id'] for item in items})==len(items)
        assert len(items)==int(sql('select count(*) from public.user_background_skill_work;').stdout.strip())


def test_end_users_cannot_forge_applied_skill_receipts(sql,tmp_path,monkeypatch):
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    with conversation.client:
        conversation.say('I remember our shed.')
        for function in ["record_background_service_work(auth.uid(),'p','{}')",
                "record_lifetime_skill_phase('{}','extract','completed',gen_random_uuid())"]:
            denied=sql('set role authenticated; select public.'+function+';',check=False)
            assert denied.returncode and 'permission denied' in denied.stderr


def test_shared_place_pass_is_embedded_not_a_second_model_request(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    def extract(packet):
        return {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])],
            'place_journeys':[{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],
                'granularity':'city','latitude':None,'longitude':None}]}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        conversation.say('My father and I repaired a bicycle in Hobart.')
        conversation.drain()
        steps=progress(conversation)['skill_progress']['items']
        embedded=next(item for item in steps if item['skill']=='memoir-place-journey')
        assert embedded['status']=='saved' and embedded['execution']=='embedded'
        assert not embedded['model_invoked'] and embedded['model_attempts']==0
        assert [phase for phase,_ in conversation.admissions]==['profile','extract']
        assert all(item['skill']!='memoir-family-tree' for item in steps)


def test_shared_place_pass_reports_skipped_when_no_place_was_derived(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    with conversation.client:
        conversation.say('I repaired a bicycle in our shed.')
        conversation.drain()
        steps=progress(conversation)['skill_progress']['items']
        place=next(item for item in steps if item['skill']=='memoir-place-journey')
        assert place['status']=='skipped' and place['execution']=='embedded'
        assert place['reason']=='no_place_cue' and not place['model_invoked']
        assert [phase for phase,_ in conversation.admissions]==['profile','extract']


def test_failed_commit_and_fresh_worker_retry_do_not_leave_false_success(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    original=conversation.worker.broker.rpc
    failed=False
    async def interrupted(name,**params):
        nonlocal failed
        if name=='commit_lifetime_memoir_lane_page' and not failed:
            failed=True
            raise RuntimeError('Synthetic commit unavailable')
        return await original(name,**params)
    monkeypatch.setattr(conversation.worker.broker,'rpc',interrupted)
    with conversation.client:
        conversation.say('I repaired a bicycle in our shed.')
        conversation.drain()
        steps=progress(conversation)['skill_progress']['items']
        first=next(item for item in steps if item['skill']=='memoir-author-timeline' and item['phase']=='extract')
        assert first['status']=='failed' and first['model_invoked']
        assert next(item for item in steps if item['skill']=='memoir-place-journey')['status']=='failed'
        assert conversation.client.get('/v1/story/skill-progress',params={'project_id':conversation.project},
            headers={'Authorization':'Bearer another-owner'}).status_code!=200
        conversation.retry()
        # Replace the worker object, preserving only its durable broker/config.
        from apps.api.memory_event_worker import MemoryEventWorker
        previous=conversation.worker
        conversation.worker=MemoryEventWorker(previous.broker,worker_url=previous.worker_url,
            worker_secret=previous.worker_secret,worker_transport=previous.worker_transport)
        conversation.worker.lane_publisher=previous.lane_publisher
        conversation.drain()
        steps=progress(conversation)['skill_progress']['items']
        saved=next(item for item in steps if item['skill']=='memoir-author-timeline' and item['status']=='saved')
        assert saved['client_turn_id']==first['client_turn_id'] and saved['source_version']==1
        assert saved['id']==first['id'] and saved['model_attempts']==2
        assert not any('lease_token' in item or 'page_digest' in item for item in steps)


def test_saved_writer_receipt_survives_missing_optional_invocation_telemetry(sql,tmp_path,monkeypatch):
    from apps.api import background_skills
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    async def unavailable(*args):pass
    monkeypatch.setattr(background_skills,'observe_lane',unavailable)
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    with conversation.client:
        conversation.say('I remember our shed.')
        conversation.drain()
        steps=progress(conversation)['skill_progress']['items']
        assert {item['skill'] for item in steps}=={'memoir-author-timeline','memoir-memory-context','memoir-place-journey'}
        models=[item for item in steps if item['execution']=='model']
        assert all(item['status']=='saved' and item['reason']=='invocation_receipt_unavailable' for item in models)
        assert all(item['model_invoked'] is None and item['model_attempts'] is None for item in models)
        place=next(item for item in steps if item['skill']=='memoir-place-journey')
        assert place['status']=='skipped' and place['reason']=='no_place_cue'
        assert place['model_invoked'] is False and place['model_attempts']==0


def test_committed_page_replay_cannot_save_the_next_pages_work(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    conversation=Conversation(sql,tmp_path,monkeypatch,empty)
    original=conversation.worker.broker.rpc
    first_commit=None
    replays=[]
    async def replay_before_next_commit(name,**params):
        nonlocal first_commit
        if name=='commit_lifetime_memoir_lane_page' and first_commit and params['p_page_number']!=first_commit['p_page_number']:
            replayed=await original(name,**first_commit)
            assert replayed=={'status':'page_saved','replayed':True}
            view=await asyncio.to_thread(progress,conversation)
            next_step=next(item for item in view['skill_progress']['items']
                if item['skill']=='memoir-author-timeline' and item['source_id']==second['accepted_source_id'])
            assert next_step['status']=='completed',next_step
            replays.append(replayed)
        result=await original(name,**params)
        if name=='commit_lifetime_memoir_lane_page' and first_commit is None:
            first_commit=params
        return result
    monkeypatch.setattr(conversation.worker.broker,'rpc',replay_before_next_commit)
    with conversation.client:
        first=conversation.say('I repaired a bicycle.')
        second=conversation.say('I painted the shed blue.')
        conversation.drain()
        assert len(replays)==1
        steps=[item for item in progress(conversation)['skill_progress']['items'] if item['skill']=='memoir-author-timeline']
        assert {item['source_id'] for item in steps}=={first['accepted_source_id'],second['accepted_source_id']}
        assert all(item['status']=='saved' for item in steps)


def test_composer_cached_retry_saves_without_counting_another_model_pass(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'receipts.sqlite3'))
    def extract(packet):
        return {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])] if packet['sources'][0]['sequence']==1 else []}
    conversation=Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        for number in range(1,6):
            conversation.say(f'I repaired bicycle number {number} in our shed.')
            conversation.drain()
        conversation.deliver_receipts()
        lane=sql("select id from public.user_memoir_lane where skill='composer';").stdout.strip()
        original=conversation.worker.broker.rpc
        failed=False
        async def interrupted(name,**params):
            nonlocal failed
            if name=='commit_lifetime_memoir_lane_page' and params['p_lane_id']==lane and not failed:
                failed=True
                raise RuntimeError('Synthetic commit unavailable')
            return await original(name,**params)
        monkeypatch.setattr(conversation.worker.broker,'rpc',interrupted)
        result=asyncio.run(conversation.worker.execute_lane(lane))
        assert result['status']=='retry',result
        before=[phase for phase,_ in conversation.admissions if phase in {'prepare','draft','review'}]
        assert before==['prepare','draft','review']
        failed_steps=[item for item in progress(conversation)['skill_progress']['items'] if item['skill']=='memoir-composer' and item['phase']!='queue']
        assert failed_steps and all(item['status']=='failed' for item in failed_steps)
        retry=conversation.client.post('/v1/story/private-draft/retry',json={'project_id':conversation.project})
        assert retry.status_code==200,retry.text
        result=asyncio.run(conversation.worker.execute_lane(lane))
        assert result.get('retrieval_complete'),(result,conversation.last_db_error)
        assert [phase for phase,_ in conversation.admissions if phase in {'prepare','draft','review'}]==before
        steps=[item for item in progress(conversation)['skill_progress']['items'] if item['skill']=='memoir-composer']
        models=[item for item in steps if item['execution']=='model']
        assert len(models)==3 and all(item['status']=='saved' and item['model_attempts']==1 for item in models)
        assert any(item['status']=='cached' and item['execution']=='cache' and not item['model_invoked'] for item in steps)
