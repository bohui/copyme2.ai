"""Shared logical B through real authenticated callers and canonical workers."""
import pytest
import asyncio
from uuid import uuid4

from test_conversation_attribution import Conversation, empty, episode
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import event_database, private_database, attachment_database
from test_shared_memory_events_postgres import sql
from test_place_photo_browser import fake_crawler


@pytest.fixture(autouse=True)
def reset_strategy(sql):
    sql('update public.lifetime_two_lane_rollout set strategy_enabled=false,strategy_shadow=false;')


def progress(conversation):
    response=conversation.client.get('/v1/story/readiness',params={'project_id':conversation.project})
    assert response.status_code==200,response.text
    return response.json()


@pytest.mark.parametrize('strategy', [None, 'shadow', 'explore'])
def test_lane_b_confirmation_preempts_the_next_question_and_is_consumed_once(sql,tmp_path,monkeypatch,strategy):
    from test_shared_memory_events_postgres import rpc, literal
    question = {'question': '您说的大石庙是承德双桥区的大石庙镇吗？',
                'topic': '大石庙位置', 'quote': '大石庙', 'requires_confirmation': True}
    def extract(packet):
        return {**empty(packet), 'prepared_questions': [question] if '大石庙' in packet['sources'][0]['text'] else []}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract,strategy='explore' if strategy == 'explore' else None)
    if strategy == 'shadow':
        sql('update public.lifetime_two_lane_rollout set strategy_enabled=true,strategy_shadow=true;')
    with conversation.client:
        conversation.say('小时候我住在大石庙，后来搬到了双桥区。')
        conversation.drain()
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(conversation.project))
        queue = lambda: rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
        pending = queue()
        assert pending[0]['requires_confirmation'] is True
        if strategy == 'explore':
            conversation.say('Please stop.')
            conversation.drain()
            assert queue()[0]['id'] == pending[0]['id'], 'A pause and a newer strategy plan must preserve the confirmation'
        turn = str(uuid4())
        response = conversation.say('放假的时候我会坐爸爸的通勤车回去。', turn=turn)
        assert response['reply'].endswith(question['question'])
        assert queue() == []
        replay = conversation.say('放假的时候我会坐爸爸的通勤车回去。', turn=turn)
        assert replay['cached'] and replay['reply_id'] == response['reply_id']
        assert queue() == []


@pytest.mark.parametrize('text,reason,question', [
    ('Actually, it was Perth, not Hobart.', 'current_correction', 'What do you remember about Perth?'),
    ("I'd prefer to tell you about my sister.", 'user_redirect', 'What would you like to remember about your sister?'),
])
@pytest.mark.parametrize('mode', ['active', 'legacy', 'shadow'])
def test_model_recognized_control_overrides_a_saved_lane_b_confirmation(sql,tmp_path,monkeypatch,text,reason,question,mode):
    import json
    from test_background_profile_workflow import worker_response
    from test_interview_strategy import wire
    from test_name_only_opening import proposal
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    from test_shared_memory_events_postgres import rpc, literal
    original = 'I grew up in Hobart and walked by the river.'
    confirmation = {'question': 'Did you mean Hobart in Tasmania?', 'topic': 'Hobart',
                    'quote': 'Hobart', 'requires_confirmation': True}
    def extract(packet):
        return {**empty(packet), 'prepared_questions': [confirmation] if packet['sources'][0]['text'] == original else []}
    async def boundary(request, provider):
        body = json.loads(request.content)
        if not body.get('bounded_lane') and body['interview_context']['source']['text'] == text:
            assert 'selection_reason' in governed_collector_schema(body['interview_context'])['required']
            output = wire(question=question, selection_reason=reason) if mode == 'active' else {
                **proposal(mode='extract', name=None, question=question), 'selection_reason': reason}
            return worker_response(request, output)
        return await provider(request)
    conversation = Conversation(sql,tmp_path,monkeypatch,extract,
        strategy='explore' if mode == 'active' else None,external_boundary=boundary)
    if mode == 'shadow':
        sql('update public.lifetime_two_lane_rollout set strategy_enabled=true,strategy_shadow=true;')
    with conversation.client:
        conversation.say(original)
        conversation.drain()
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(conversation.project))
        queue = lambda: rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
        pending = queue()
        assert pending[0]['question'] == confirmation['question']
        response = conversation.say(text)
        assert response['reply'].endswith(question)
        assert confirmation['question'] not in response['reply']
        assert queue()[0]['id'] == pending[0]['id'], 'The old question was not delivered or consumed'
        if mode == 'active':
            outcome = json.loads(sql('select to_jsonb(o) from public.user_lifetime_strategy_outcome o order by source_sequence desc limit 1;').stdout)
            assert outcome['selection_reason'] == reason
            assert outcome['question_delivered'] == question and outcome['selected_candidate_id'] is None


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


def test_restored_chengde_period_drives_both_photo_and_news_research(sql,tmp_path,monkeypatch,request,fake_crawler):
    import json
    from pathlib import Path
    import subprocess
    import httpx
    from apps.api import agent_routes, place_geocoding, place_photos, place_photo_browser, supabase_routes
    from apps.api.historical_news import HistoricalResearch
    from test_place_workspace import photo_page
    from test_place_photo_browser import cse_html, photo_html
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS', '1')
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL', raising=False)
    for key in ('SERPAPI_KEY','GOOGLE_CSE_API_KEY','GOOGLE_CSE_ID','GOOGLE_CSE_URL','MEMORY_SPARK_PHOTO_WEB_SEARCH'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setenv('SERPAPI_KEY','fixture-serpapi')
    monkeypatch.setenv('GOOGLE_CSE_ID','fixture-cse')
    monkeypatch.setenv('MEMOIR_PHOTO_EXPANSION','0')
    monkeypatch.setenv('FLICKR_API_KEY','fixture')
    monkeypatch.setenv('GOOGLE_MAPS_GEOCODING_API_KEY','fixture')
    monkeypatch.setenv('MEMOIR_GEO_PROVIDER','google')
    monkeypatch.setattr('apps.api.place_photo_fingerprints.image_fingerprint',lambda _: {})
    place_geocoding.search_place.cache_clear()
    request.addfinalizer(place_geocoding.search_place.cache_clear)
    queries = []
    monkeypatch.setattr(place_photos,'_google_serpapi',
        lambda place,period,**kwargs: queries.append(('serpapi',place,period)) or [])
    pages, browser_calls, _ = fake_crawler
    cse_sources=[f'https://archive.example/chengde/{index}' for index in range(1,11)]
    pages[place_photo_browser._search_url('google','承德市','1980s')]=cse_html(cse_sources)
    pages[place_photo_browser._search_url('google','悉尼','')]='<div class="gs-no-results-result">No results</div>'
    for index,source in enumerate(cse_sources,1):
        pages[source]=photo_html(index, date=f'{1979+index}-10-01')
        if index in (1,3,4):
            record = {'@type':'Photograph','name':'Main Street' if index == 1 else 'Chengde street',
                      'caption':{3:'Beijing Summer Palace',4:'Taken in 1983'}.get(index,''),
                      'dateTaken':f'{1979+index}-10-01','license':'https://creativecommons.org/licenses/by/4.0/',
                      'contentLocation':{'name':'Chengde','geo':{'latitude':40.98,'longitude':117.94}},
                      'contentUrl':f'https://live.staticflickr.com/1/{index}.jpg'}
            pages[source] = ('<title>Chengde archive</title><script type="application/ld+json">'
                             + json.dumps(record) + '</script>')
        if index == 2:
            local = {'@type':['ImageObject','Photograph'], 'name':'Willow trees',
                     'dateTaken':f'{1979+index}-10-01', 'license':'https://creativecommons.org/licenses/by/4.0/',
                     'creator':{'name':'Alice Example'},
                     'contentLocation':{'name':'Chengde','geo':{'latitude':40.98,'longitude':117.94}},
                     'contentUrl':f'https://live.staticflickr.com/1/{index}.jpg'}
            wrong_city = {**local, 'name':'Beijing street', 'dateTaken':'1983-10-01',
                          'contentLocation':{'name':'Beijing'},
                          'contentUrl':'https://live.staticflickr.com/1/beijing.jpg'}
            wrong_landmarks = [{**wrong_city,'name':name,'contentLocation':{'name':city},
                               'contentUrl':f'https://live.staticflickr.com/1/{slug}.jpg'}
                              for name,city,slug in (('Beijing Summer Palace','Beijing','beijing-palace'),
                                                     ('Sydney Opera House','Sydney','sydney-opera'))]
            pages[source] = ('<title>Chengde photo gallery</title><script type="application/ld+json">'
                             + json.dumps({'@type':'ImageGallery','itemListElement':[
                                 {'item':record} for record in [wrong_city,*wrong_landmarks,local]]}) + '</script>')
    landmark = {'place':'Chengde Mountain Resort','hierarchy':['Earth','China','Hebei','Chengde','Mountain Resort'],
                'granularity':'landmark','latitude':40.98,'longitude':117.94,
                'research_period':'1980s','research_year':1983}
    landmark_source = 'https://archive.example/chengde/resort'
    pages[place_photo_browser._search_url('google',landmark['place'],'1980s')] = (
        cse_html([landmark_source]).replace('Chengde','Chengde Mountain Resort'))
    resort_photo = {**local,'name':'Mountain Resort','dateTaken':'1983-10-01',
                    'contentUrl':'https://live.staticflickr.com/1/resort.jpg'}
    pages[landmark_source] = ('<title>Chengde Mountain Resort gallery</title><script type="application/ld+json">'
                             + json.dumps({'@type':'ImageGallery','itemListElement':[
                                 {'item':wrong_city},{'item':resort_photo}]}) + '</script>')
    containing_places, containing_titles = [], {}
    for name,city,hierarchy,granularity,location in (
            ('China','Beijing',['Earth','China'],'country',
             {'name':'China','address':{'addressLocality':'Beijing','addressCountry':'China'}}),
            ('Hebei','Chengde',['Earth','China','Hebei'],'region',
             {'name':'Hebei','address':{'addressLocality':'Chengde','addressRegion':'Hebei','addressCountry':'China'}}),
            ('Australia','Sydney',['Earth','Australia'],'country',
             {'name':'Australia','address':{'addressLocality':'Sydney','addressCountry':'Australia'}}),
            ('Norway','Bergen',['Earth','Norway'],'country',
             {'name':'Norway','address':{'addressLocality':'Bergen','addressCountry':'Norway'}}),
            ('Firstshire','Firstville',['Earth','Firstland','Firstshire'],'region',
             {'name':'Firstville','containedInPlace':{'@type':'AdministrativeArea','name':'Firstshire'}}),
            ('Japan','長野市',['Earth','Japan'],'country',
             {'@type':'Country','name':'日本','alternateName':'Japan','address':{'addressLocality':'長野市'}}),
            ('Brighton and Hove','Brighton and Hove',['Earth','United Kingdom','Brighton and Hove'],'city',
             {'@type':'Place','name':'Brighton and Hove'})):
        containing_places.append({'place':name,'hierarchy':hierarchy,'granularity':granularity,
                                  'research_period':'1980s','research_year':1983})
        containing_titles[name] = f'{city} street'
        slug = name.lower().replace(' ','-')
        source = f'https://archive.example/containing/{slug}'
        pages[place_photo_browser._search_url('google',name,'1980s')] = cse_html([source]).replace('Chengde',name)
        record = {**resort_photo,'name':f'{city} street','contentLocation':location,
                  'contentUrl':f'https://live.staticflickr.com/1/{slug}.jpg'}
        pages[source] = (f'<title>{name} archive</title><script type="application/ld+json">'
                         + json.dumps(record) + '</script>')
    rejected_city_places = []
    for name,wrong_city in (('Perth','Sydney'),('Hobart','Sydney'),('Canberra','Sydney'),('Northbridge','Southport')):
        rejected_city_places.append({'place':name,'hierarchy':['Earth',name],
                                     'granularity':'city','research_period':'1980s','research_year':1983})
        source = f'https://archive.example/city/{name.lower()}'
        pages[place_photo_browser._search_url('google',name,'1980s')] = cse_html([source]).replace('Chengde',name)
        pages[place_photo_browser._search_url('google',name,place_photos.ANY_PHOTO_DATE)] = (
            pages[place_photo_browser._search_url('google',name,'1980s')])
        record = {key:value for key,value in resort_photo.items() if key != 'contentLocation'}
        record.update(name=f'{wrong_city} city centre in {name}',
                      contentUrl=f'https://live.staticflickr.com/1/{wrong_city.lower()}.jpg')
        pages[source] = (f'<title>{name} archive</title><script type="application/ld+json">'
                         + json.dumps(record) + '</script>')
    places = [
        {'place':'承德市','hierarchy':['Earth','中国','河北省','承德市'],'granularity':'city','latitude':40.97,'longitude':117.93},
        {'place':'悉尼','hierarchy':['Earth','澳大利亚','悉尼'],'granularity':'city','latitude':-33.86,'longitude':151.2},
    ]
    parramatta = {'place':'Parramatta','hierarchy':[*places[1]['hierarchy'],'Parramatta'],
                  'granularity':'suburb','latitude':-33.815,'longitude':151.002}
    def extract(packet):
        source=packet['sources'][0]
        quoted=source['text']
        model_places=[{**place} for place in reversed(places)]
        model_places[1]['research']=dict(year_start=1980,year_end=1989,anchor_year=1983,basis='birth_decade',
            quote=quoted,char_start=0,char_end=len(quoted)+3)
        # Replay the live failure: both derived proposals preserve the words but miscount the span.
        question=dict(question='关于承德的这段经历，您还记得什么？',topic='承德回忆',
            quote=quoted,char_start=0,char_end=len(quoted)+3)
        return {**empty(packet), 'place_journeys': model_places, 'prepared_questions':[question]}
    def external_get(url,**kwargs):
        params=kwargs['params']
        if 'maps.googleapis.com' in url:
            chinese=params.get('language')=='zh-CN'
            chengde='承德' in params['address']
            name,region,country=(('承德市','河北省','中国') if chengde else ('悉尼','新南威尔士州','澳大利亚')) if chinese else (
                ('Chengde','Hebei','China') if chengde else ('Sydney','New South Wales','Australia'))
            place=places[0 if chengde else 1]
            if 'Parramatta' in params['address']:
                name,region,country='Parramatta','New South Wales','Australia'
                place=parramatta
            result={'status':'OK','results':[{'geometry':{'location':{'lat':place['latitude'],'lng':place['longitude']}},
                'address_components':[{'long_name':value,'types':[kind]} for value,kind in (
                    (name,'locality'),(region,'administrative_area_level_1'),(country,'country'))]}]}
        elif 'commons.wikimedia.org' in url:
            query=params['gsrsearch']
            queries.append(('photo',query))
            chengde='Chengde' in query
            pages=[]
            if chengde or 'Sydney' in query:
                current=place_photos.datetime.now(place_photos.ZoneInfo('Australia/Sydney')).date().isoformat()
                for index in range(1,11):
                    identifier=index+(0 if chengde else 10)
                    # Modern Commons photos must not displace dated CSE originals.
                    page=photo_page(identifier,date='2008-06-18' if chengde else current,
                        title=f'{"Chengde" if chengde else "Sydney"} street {identifier}.jpg')
                    info=page['imageinfo'][0]
                    filename=f'{"Chengde" if chengde else "Sydney"}_street_{identifier}.jpg'
                    info['thumburl']=f'https://thumb.wikimedia.org/wikipedia/commons/thumb/a/ab/{filename}/640px-{filename}'
                    info['extmetadata'].update(GPSLatitude={'value':str(places[0 if chengde else 1]['latitude'])},
                        GPSLongitude={'value':str(places[0 if chengde else 1]['longitude'])})
                    pages.append(page)
            result={'query':{'pages':{str(page['pageid']):page for page in pages}}}
        elif 'flickr.com' in url:
            result={'stat':'ok','photos':{'photo':[]}}
        elif 'loc.gov' in url:
            result={}
        else:
            pytest.fail(f'Unexpected external request: {url.split("?")[0]}')
        return httpx.Response(200,json=result,request=httpx.Request('GET',url))
    monkeypatch.setattr(httpx,'get',external_get)
    class Provider:
        identity = 'synthetic-place-news'
        async def discover(self, query, **kwargs):
            queries.append(('news',query))
            return {'receipt':{'status':'completed','response_id':'r','tool_call_id':'w','urls':[]},'events':[]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract)
    monkeypatch.setattr(supabase_routes, 'storage', agent_routes.authenticated_storage)
    agent_routes.runtime._news_engine = HistoricalResearch(Provider())
    with conversation.client:
        conversation.say('我现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院')
        pending=progress(conversation)
        assert pending['pending'] and pending['derived_workspace']['places']==[]
        conversation.drain()
        assert [phase for phase,_ in conversation.admissions].count('extract') == 1
        ready=progress(conversation)
        response=conversation.client.get(f'/v1/user/projects/{conversation.project}/history')
        assert response.status_code==200,response.text
        history=response.json()
        saved = ready['derived_workspace']['places']
        assert [place['place'] for place in saved] == ['悉尼', '承德市']
        assert {p['place']:p['research_period'] for p in saved} == {'悉尼':'','承德市':'1980s'}
        assert {p['place']:p['research_year'] for p in saved} == {'悉尼':None,'承德市':1983}
        photos={}
        for place in saved:
            response = conversation.client.get(f'/v1/agent/places/{conversation.project}/photos',
                params={'place':place['place'],'latitude':place['latitude'],'longitude':place['longitude']},
                headers={'Accept':'application/x-ndjson'})
            assert response.status_code == 200,response.text
            photos[place['place']]=response.text
            final=json.loads(response.text.splitlines()[-1])
            assert final['status']=='READY',final
            assert len(final['items'])==10
            assert not final.get('failures')
            if place['place']=='承德市':
                assert all(item['providers']==['google','cse'] for item in final['items'])
                assert not any('beijing' in item['image_url'] or 'sydney-opera' in item['image_url']
                               for item in final['items'])
                assert next(item for item in final['items'] if item['image_url'].endswith('/1.jpg'))['title'] == 'Main Street'
                assert any(item['image_url'].endswith('/3.jpg') for item in final['items'])
                assert next(item for item in final['items'] if item['image_url'].endswith('/4.jpg'))['date_expression'] == '1983-10-01'
                credited=next(item for item in final['items'] if item['image_url'].endswith('/2.jpg'))
                assert credited['title']=='Willow trees'
                assert credited['attribution']=='Alice Example'
                assert final['items'][0]['date_expression']=='1983-10-01'
                gaps=[abs(int(item['date_expression'][:4])-1983) for item in final['items']]
                assert gaps==sorted(gaps)
        assert any(q[0]=='serpapi' and q[1:] == ('承德市','1980s') for q in queries)
        assert any(url==place_photo_browser._search_url('google','承德市','1980s') for url,_ in browser_calls)
        assert any(q[0]=='photo' and 'Chengde' in q[1] and '1980' in q[1] and '1989' in q[1] for q in queries)
        assert any(q[0]=='photo' and 'Sydney' in q[1] for q in queries)
        assert any(q[0]=='news' and q[1].startswith('承德, 中国 1980–1989') for q in queries)
        steps = progress(conversation)['skill_progress']['items']
        assert any(s['skill']=='memoir-historical-news-research' and s['status']=='saved' for s in steps)
        assert any(s['skill']=='memoir-place-photo-research' and s['status']=='completed' for s in steps)
        response = conversation.client.get(f'/v1/agent/places/{conversation.project}/photos',
            params={'place':landmark['place'],'period':'1980s','context_year':1983,
                    'latitude':landmark['latitude'],'longitude':landmark['longitude']},
            headers={'Accept':'application/x-ndjson'})
        assert response.status_code == 200,response.text
        photos[landmark['place']] = response.text
        final = json.loads(response.text.splitlines()[-1])
        assert final['status'] == 'PARTIAL',final
        assert not final.get('failures')
        assert [item['title'] for item in final['items']] == ['Mountain Resort']
        assert final['items'][0]['date_expression'] == '1983-10-01'
        for parent in containing_places:
            response = conversation.client.get(f'/v1/agent/places/{conversation.project}/photos',
                params={'place':parent['place'],'period':'1980s','context_year':1983},
                headers={'Accept':'application/x-ndjson'})
            assert response.status_code == 200,response.text
            photos[parent['place']] = response.text
            final = json.loads(response.text.splitlines()[-1])
            assert final['status'] == 'PARTIAL',final
            assert not final.get('failures')
            assert [item['title'] for item in final['items']] == [containing_titles[parent['place']]]
            assert final['items'][0]['date_expression'] == '1983-10-01'
        for city in rejected_city_places:
            response = conversation.client.get(f'/v1/agent/places/{conversation.project}/photos',
                params={'place':city['place'],'period':'1980s','context_year':1983},
                headers={'Accept':'application/x-ndjson'})
            assert response.status_code == 200,response.text
            photos[city['place']] = response.text
            final = json.loads(response.text.splitlines()[-1])
            assert final['status'] == 'NO_MATCH',final
            assert final['items'] == [] and not final.get('failures')
        groups=[]
        public=[{key:place[key] for key in ('place','hierarchy','granularity','latitude','longitude')} for place in saved]
        for language in ('zh-CN','en-AU'):
            for ordered in (public,list(reversed(public))):
                request={'places':ordered,'language':language}
                response=conversation.client.post(f'/v1/agent/places/{conversation.project}/groups',json=request)
                assert response.status_code==200,response.text
                expected=['承德市','悉尼'] if language=='zh-CN' else ['Chengde','Sydney']
                assert {item['city']['place'] for item in response.json()['places']}==set(expected)
                groups.append({'request':request,'response':response.json()})
        provider_places=[next(place for place in public if place['place']=='悉尼'),parramatta]
        request={'places':list(reversed(provider_places)),'language':'en-AU'}
        response=conversation.client.post(f'/v1/agent/places/{conversation.project}/groups',json=request)
        assert response.status_code==200,response.text
        assert {item['city']['place'] for item in response.json()['places']}=={'Sydney','Parramatta'}
        groups.append({'request':request,'response':response.json()})
        ready=progress(conversation)
        response=conversation.client.get('/v1/story/private-draft',params={'project_id':conversation.project})
        assert response.status_code==200,response.text
        private_draft=response.json()
        assert private_draft['error']
        packet={'pending':pending,'ready':ready,'history':history,'photos':photos,'groups':groups,
                'private_draft':private_draft,
                'provider_places':provider_places,'landmark':landmark,'containing_places':containing_places,
                'containing_titles':containing_titles,'rejected_city_places':rejected_city_places}
        (tmp_path/'place-research-replay.json').write_text(json.dumps(packet,ensure_ascii=False))
        replay=Path(__file__).parent/'js/helpers/replay-place-research.mjs'
        result=subprocess.run(['node',str(replay)],input=json.dumps(packet),text=True,capture_output=True,timeout=20)
        assert result.returncode==0,result.stdout+result.stderr


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
        response=conversation.client.get('/v1/story/private-draft',params={'project_id':conversation.project})
        assert response.status_code==200,response.text
        draft=response.json()
        assert draft['preview']
        turn=sql(f"select client_turn_id from public.user_narrator_source where sequence={int(draft['source_revision'])};").stdout.strip()
        assert any(item['skill']=='memoir-composer' and item['coverage_end']==draft['source_revision']
            and item['client_turn_id']==turn for item in draft['skill_progress']['items'])
