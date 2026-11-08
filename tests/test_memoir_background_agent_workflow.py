"""Accepted conversation → background Codex tools → real canonical domain commits."""
import asyncio
import json
from pathlib import Path
import subprocess
import threading

import pytest

from fastapi import FastAPI
import httpx

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput
from apps.api.memory_event_worker import MemoryEventWorker
from controlled_skill_harness import ControlledSkillConnection, empty_document, install_document_provider
from test_background_profile_workflow import database, Broker
from test_conversation_attribution import Conversation, empty
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_memoir_background_agent_postgres import service
from test_agent_commit_postgres import OWNER


@pytest.mark.parametrize('text,preference,locale',[
    ('我于1983年4月出生在承德。',None,'zh-CN'),
    ('我于1983年4月出生在承德。','en-AU','en-AU'),
    ('I was born in Chengde in April 1983.','zh-CN','zh-CN'),
    ('I was born in Chengde in April 1983.',None,'en-AU'),
])
def test_resolved_language_reaches_background_skills_and_map_cards(sql,tmp_path,monkeypatch,text,preference,locale):
    from test_conversation_attribution import episode
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    phases=[]
    title='1983年4月出生在承德' if locale=='zh-CN' else 'Born in Chengde in April 1983'
    description='故事讲述者于1983年4月在承德出生。' if locale=='zh-CN' else 'The storyteller was born in Chengde in April 1983.'
    class LocalizedConnection(ControlledSkillConnection):
        async def turn(self,thread_id,prompt,**options):
            task=json.loads(prompt)['task']
            assert task['lane']=='B' and task['locale']==locale, 'Resolve context before selecting any source skills.'
            return await super().turn(thread_id,prompt,**options)
    def respond(body):
        task=json.loads(body['input'])
        fields=body['text']['format']['schema']['properties']
        phase='profile' if 'profile_patch' in fields else 'reconcile' if 'decisions' in fields else 'extract'
        phases.append(phase)
        assert task['lane_context']['preferences']['language']==locale
        language='Simplified Chinese' if locale=='zh-CN' else 'Australian English'
        if phase != 'reconcile':
            assert f'Write in {language}; preserve original quoted source language.' in body['instructions']
        output=empty_document(body)
        if phase=='extract':
            packet=task['payload']
            output['events']=[{**episode(packet,packet['sources'][0]['text'],title=title), 'description':description}]
        return output
    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',LocalizedConnection)
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty)
    native=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))
    with conversation.client:
        conversation.say(text,**({'language':preference} if preference else {}))
        conversation.deliver_receipts()
        run,=service(sql,'pending_memoir_background_agents')
        result=asyncio.run(worker.execute_background_agent(run))
        assert result['status']=='finished',result
        assert phases==['profile','extract','reconcile']
        profile=conversation.client.get('/v1/agent/profile').json()
        assert profile['preferred_language']==locale
        response=conversation.client.get('/v1/story/atlas-events',params={'view':'map','project_id':conversation.project})
        assert response.status_code==200,response.text
        assert [event['title'] for event in response.json()['events']]==[title]
        timeline=conversation.client.get('/v1/story/events',params={'project_id':conversation.project})
        assert timeline.status_code==200,timeline.text
        assert timeline.json()['events'][0]['description']==description
        replay=subprocess.run(['node',str(Path(__file__).parent/'js/helpers/replay-background-locale.mjs')],
            input=json.dumps(dict(project_id=conversation.project,feed=response.json(),timeline=timeline.json(),
                profile=profile,locale=locale,title=title,description=description)),
            text=True,capture_output=True,timeout=10)
        assert replay.returncode==0,replay.stdout+replay.stderr


def test_timeline_reconciles_and_revises_a_city_period(sql,tmp_path,monkeypatch):
    from uuid import uuid4
    from test_conversation_attribution import episode, reference
    from test_shared_memory_events_postgres import literal, rpc

    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    porto = 'I began living in Porto in 1999.'
    hobart = 'After that I settled in Hobart.'
    first = f'{porto} {hobart}'
    departure = 'I left Porto in 2010.'
    detail = 'That was the period when I worked at the library.'
    extraction_calls = []
    reconciliation_calls = []
    message_ids = []

    class TimelineConnection(ControlledSkillConnection):
        source_choices = ('memoir-author-timeline',)

        async def turn(self, thread_id, prompt, **options):
            source_work = json.loads(prompt)['task'].get('source_work')
            if source_work:
                assert 'memoir-place-journey' not in source_work['available_skills']
            return await super().turn(thread_id, prompt, **options)

    def respond(body):
        schema = body['text']['format']['schema']
        packet = json.loads(body['input'])['payload']
        if 'decisions' in schema['properties']:
            reconciliation_calls.append(packet)
            assert packet['message_id'] == message_ids[-1]
            assert all('existing_id' not in draft for draft in packet['drafts'])
            assert len(packet['drafts']) == (3 if len(message_ids) == 1 else 2)
            output = empty_document(body)
            if len(message_ids) == 1:
                assert packet['published_events'] == []
                assert sql('select count(*) from public.user_memory_event;').stdout.strip() == '0'
            else:
                saved = next(event for event in packet['published_events'] if event['title'] == 'Porto')
                assert (saved['start_year'],saved['end_year']) == (1999,2016)
                assert saved['description'] == porto
                assert saved['location']['place'] == 'Porto'
                target = saved['id']
                if 'retry_reason' not in packet:
                    target = 'event-outside-reconciliation-scope'
                for decision in output['decisions']:
                    decision.update(action='update',event_id=target)
            return output
        assert 'place_journeys' not in schema['properties']
        assert 'DraftEventRelation' in schema['$defs']
        assert schema['$defs']['EventProposal']['properties']['existing_id'] == {'type':'null'}
        text = packet['sources'][0]['text']
        extraction_calls.append((text, packet.get('retry_reason')))

        def period(quote, city, country, draft_id, years):
            ref = reference(packet, quote)
            return {**episode(packet, quote, title=city), 'kind':'period', 'id':draft_id,
                'location':{'place':city,'hierarchy':['Earth',country,city],'granularity':'city'},
                'location_basis':[ref], 'locationConfidenceScore':1.0,
                'temporal_estimate':dict(year_start=years[0], year_end=years[1], confidence=.45,
                    rationale='A provisional residence span around the narrated move.', basis=[reference(packet, first)])}

        if text == first:
            earlier = period(porto, 'Porto', 'Portugal', 'draft-1', (1999, 2016))
            earlier['temporal'] = dict(expression='1999', precision='year', year_start=1999,
                basis=[reference(packet, porto)])
            earlier['relations'] = [dict(kind='before', draft_id='draft-2', source_refs=[reference(packet, first)])]
            later = period(hobart, 'Hobart', 'Australia', 'draft-2', (1998, 2020))
            output = [later, earlier, {**later, 'id':'draft-3'}]
        else:
            assert text == f'{departure} {detail}'
            update = {**episode(packet, departure, title='Porto'), 'kind':'period',
                'temporal':dict(expression='2010', precision='year', year_end=2010, basis=[reference(packet, departure)])}
            if 'retry_reason' not in packet:
                prior = packet['conversation_history'][-1]['source']
                update['source_refs'].append(dict(source_id=prior['id'], version=prior['version'], quote=porto))
            additional = {**episode(packet, detail, title='Porto'), 'kind':'period',
                'temporal_estimate':None, 'location':None, 'location_basis':[], 'locationConfidenceScore':0.0,
                'yearConfidenceScore':0.0, 'relations':[]}
            output = [update, additional]
        return {**empty_document(body), 'events':output}

    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',TimelineConnection)
    conversation = Conversation(sql,tmp_path / 'conversation',monkeypatch,empty)
    native = CodexWorker(home_root=tmp_path / 'worker', command=['controlled'],
        base_url='http://synthetic.invalid', api_key='synthetic')
    app = FastAPI()

    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)

    worker = MemoryEventWorker(Broker(sql), worker_url='http://controlled.invalid', worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))

    def publish(text, end):
        message_ids.append(str(uuid4()))
        conversation.say(text, turn=message_ids[-1])
        conversation.deliver_receipts()
        sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
        run, = service(sql,'pending_memoir_background_agents')
        result = asyncio.run(worker.execute_background_agent(run))
        assert result['status'] == 'finished', result
        project = conversation.project
        feed = conversation.client.get('/v1/story/atlas-events', params={'view':'map','project_id':project}).json()
        assert feed['map_source'] == 'published_events'
        assert sorted(event['title'] for event in feed['events']) == ['Hobart','Porto']
        by_title = {event['title']:event for event in feed['events']}
        earlier, later = by_title['Porto'], by_title['Hobart']
        locations = {}
        for event in feed['events']:
            path = f'/v1/story/atlas-events/{project}/{event["id"]}'
            locations[event['id']] = conversation.client.get(f'{path}/places').json()
        assert earlier['relations'] == [{'kind':'before','event_id':later['id']}]
        replay = subprocess.run(['node',str(Path(__file__).parent/'js/helpers/replay-event-group.mjs')],
            input=json.dumps(dict(project=project,feed=feed,locations=locations,end=end)),
            text=True,capture_output=True,timeout=20)
        assert replay.returncode == 0, replay.stdout+replay.stderr
        return earlier

    with conversation.client:
        original = publish(first, 'About 2016')
        revised = publish(f'{departure} {detail}', '2010')
        assert (revised['id'], revised['revision']) == (original['id'], original['revision'] + 1)
        assert (revised['temporal']['year_start'], revised['temporal']['year_end']) == (1999, 2010)
        assert sql("""select count(*) from public.user_memory_event_source s join public.user_memory_event e
            on (s.user_id,s.project_id,s.event_id)=(e.user_id,e.project_id,e.id)
            where e.data->>'title'='Porto' and s.stage_progress_role='primary';""").stdout.strip() == '3'
        assert sql("""select count(*) from public.user_background_skill_work
            where skill='memoir-author-timeline' and phase='reconcile' and execution='model'
              and status='saved';""").stdout.strip() == '2'
        record = next(event for event in rpc(sql,'read_user_memory_events',literal(conversation.project))['events']
                      if event['id'] == revised['id'])
        assert record['message_ids'] == message_ids
        follow_up = f'{departure} {detail}'
        assert extraction_calls == [(first, None), (follow_up, None), (follow_up, 'PRIMARY_SOURCE_SCOPE')]
        assert len(reconciliation_calls) == 3 and reconciliation_calls[-1]['retry_reason'] == 'INVALID_RECONCILIATION'


@pytest.mark.parametrize('case', ['short-answer', 'year-only', 'explicit-correction', 'place', 'stage', 'wording'])
def test_chat_correction_revises_the_published_event(sql, tmp_path, monkeypatch, case):
    from test_conversation_attribution import episode, reference
    from test_conversation_reply import proposal
    from test_shared_memory_events_postgres import literal, rpc

    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP', '1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'tasks.sqlite'))
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    date_case = case in {'short-answer', 'year-only', 'explicit-correction'}
    if date_case:
        original_event = '1912年的时候才来的悉尼'
        unrelated = '16岁才去上海学习工作'
        first = f'对的,我是在成德长大,一直到{unrelated},{original_event}'
        original_title = updated_title = '来到悉尼'
        question = '你刚才说“1912年”来到悉尼，是指2012年，还是另一个年份？'
        correction = {'short-answer': '2012 年来的悉尼', 'year-only': '2012',
                      'explicit-correction': '其实是2012 年来的悉尼'}[case]
        confirmed = '明白了，你是2012年来到悉尼的。'
        clarification = correction
    else:
        original_event = 'I repaired a bicycle with Leo in Hobart as a teenager.'
        unrelated = 'I kept a dog called Pip.'
        first = f'{original_event} {unrelated}'
        original_title = 'Bicycle repair with Leo'
        updated_title = 'Bicycle repair with Maya' if case == 'wording' else original_title
        question, correction, confirmed = {
            'place': ('Was the bicycle repair in Hobart or Launceston?', 'Launceston.', 'It happened in Launceston.'),
            'stage': ('Were you a teenager then?', 'I was in my twenties then.', 'You were in your twenties.'),
            'wording': ('Who helped you with the bicycle?', 'My sister Maya helped with the bicycle.', 'Maya helped.'),
        }[case]
        clarification = f'{correction} Thanks for checking.' if case == 'wording' else correction

    def reply(context):
        return {**proposal(), 'acknowledgement': confirmed if context['source']['text'] == clarification else original_event,
            'question': question if context['source']['text'] == first else None,
            'reason': 'current_correction' if context['source']['text'] == clarification else 'latest_story'}

    def respond(body):
        packet = json.loads(body['input'])['payload']
        output = empty_document(body)
        if 'decisions' in output:
            if packet['published_events']:
                saved = next(event for event in packet['published_events'] if event['title'] == original_title)
                exchange, = packet['recent_dialogue']
                assert exchange['question']['text'] == question and exchange['question']['personal_testimony'] is False
                assert exchange['response']['text'] == clarification
                output['decisions'][0].update(action='update', event_id=saved['id'], correction=True)
            return output
        if 'events' not in output:
            return output
        initial = packet['sources'][0]['text'] == first
        quote = original_event if initial else correction
        ref = reference(packet, quote)
        event = {**episode(packet, quote, title=original_title if initial else updated_title),
            'life_stage': 'unplaced', 'stage_evidence': [], 'location': None, 'location_basis': [],
            'locationConfidenceScore': 0.0, 'yearConfidenceScore': 0.0}
        if date_case:
            year = 1912 if initial else 2012
            event.update(temporal=dict(expression=str(year), precision='year', year_start=year, year_end=year, basis=[ref]),
                yearConfidenceScore=1.0)
        elif initial or case == 'stage':
            event.update(life_stage='adolescence' if initial else 'young_adulthood', stage_evidence=[ref])
        if initial or case == 'wording':
            event['description'] = quote
        if initial or case == 'place':
            city = '悉尼' if date_case else 'Hobart' if initial else 'Launceston'
            country = '澳大利亚' if date_case else 'Australia'
            event.update(location=dict(place=city, hierarchy=['Earth', country, city], granularity='city'),
                location_basis=[ref], locationConfidenceScore=1.0)
        output['events'] = [event]
        if initial:
            output['events'].append(episode(packet, unrelated, title=unrelated))
        return output

    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection', ControlledSkillConnection)
    conversation = Conversation(sql, tmp_path / 'conversation', monkeypatch, empty, reply=reply)
    native = CodexWorker(home_root=tmp_path / 'worker', command=['controlled'],
        base_url='http://synthetic.invalid', api_key='synthetic')
    app = FastAPI()

    @app.post('/internal/codex/turn')
    async def turn(payload: WorkerTurnInput):
        return await native.turn(payload)

    worker = MemoryEventWorker(Broker(sql), worker_url='http://controlled.invalid', worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))

    def publish():
        conversation.deliver_receipts()
        sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
        run, = service(sql, 'pending_memoir_background_agents')
        asyncio.run(worker.execute_background_agent(run))
        response = conversation.client.get('/v1/story/atlas-events',
            params={'view': 'map', 'project_id': conversation.project})
        assert response.status_code == 200, response.text
        return response.json()

    with conversation.client:
        original = conversation.say(first)
        before = publish()
        saved = next(event for event in before['events'] if event['title'] == original_title)
        response = conversation.say(clarification)
        assert confirmed in response['reply']
        if case == 'year-only':
            source = dict(id=response['accepted_source_id'], version=1)
            ref = dict(source_id=source['id'], version=1, quote=correction)
            unscoped = dict(kind='event', title=original_title, existing_id=saved['id'], expected_revision=saved['revision'],
                temporal=dict(expression='2012', precision='year', year_start=2012, year_end=2012, basis=[ref]),
                correction=ref, source_refs=[ref])
            rejected = rpc(sql, 'apply_user_memory_events',
                f"{literal(conversation.project)},{literal([source])},{literal([unscoped])}", check=False)
            assert 'chat correction requires explicit current original testimony' in rejected.stderr
        after = publish()
        updated = next(event for event in after['events'] if event['id'] == saved['id'])
        assert updated['title'] == updated_title
        assert updated['revision'] > saved['revision']
        assert after['event_revision'] > before['event_revision']
        assert updated['locationConfidenceScore'] == 1
        if case == 'place':
            assert [link['place']['place'] for link in updated['places']] == ['Launceston']
        else:
            assert updated['location'] == saved['location']
        assert [event for event in after['events'] if event['id'] != saved['id']] == [
            event for event in before['events'] if event['id'] != saved['id']]
        view = rpc(sql, 'read_user_memory_events', literal(conversation.project))
        record = next(event for event in view['events'] if event['id'] == saved['id'])
        assert record['message_ids'] == [original['client_turn_id'], response['client_turn_id']]
        assert sql(f"select count(*) from public.user_memory_event_revision where event_id={literal(saved['id'])} "
            f"and origin='chat' and actor={literal(OWNER)};").stdout.strip() == '1'
        if case == 'wording':
            assert record['description'] == correction
        if case == 'stage':
            assert updated['life_stage'] == 'young_adulthood'
            assert record['user_overrides']['life_stage']['origin'] == 'chat'
        else:
            assert updated['life_stage'] == saved['life_stage']
        if date_case:
            assert view['sources'][-1]['language'] == 'zh-CN'
            assert saved['temporal']['year_start'] == 1912
            assert (updated['temporal']['year_start'], updated['temporal']['year_end']) == (2012, 2012)
            assert record['user_overrides']['temporal']['source_id'] == response['accepted_source_id']
            assert record['user_overrides']['temporal']['origin'] == 'chat'
            replay = subprocess.run(['node', str(Path(__file__).parent / 'js/helpers/replay-map-year-clarification.mjs')],
                input=json.dumps(dict(project=conversation.project, event_id=saved['id'], feeds=[before, after])),
                text=True, capture_output=True, timeout=10)
            assert replay.returncode == 0, replay.stdout + replay.stderr


@pytest.mark.parametrize('profile_first',[False,True])
def test_foreground_keeps_replying_while_background_finishes_then_batches_queued_narrations(sql,tmp_path,monkeypatch,profile_first):
    from test_conversation_reply import proposal
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    entered, release = asyncio.Event(), asyncio.Event()
    batches, originals = [], []
    class SlowConnection(ControlledSkillConnection):
        source_choices = ('memoir-author-timeline',)
        async def turn(self,thread_id,prompt,**options):
            task = json.loads(prompt)['task']
            assert task['lane']=='B'
            batches.append(task['source_work']['sources'])
            if profile_first and len(batches)==1:
                self.source_choices=('memoir-memory-context','memoir-author-timeline')
            return await super().turn(thread_id,prompt,**options)
    async def respond(body):
        task=json.loads(body['input'])
        is_profile='profile_patch' in body['text']['format']['schema']['properties']
        source=task['payload']['source'] if is_profile else task['payload']['sources'][0]
        if not is_profile:
            originals.append(source)
        if not entered.is_set():
            entered.set()
            await release.wait()
        output=empty_document(body)
        if is_profile:
            output['profile_patch']=[{'field':'birth_place','value':'Hobart','source_refs':[{
                'source_id':source['id'],'version':source['version'],'quote':source['text'],
                'char_start':0,'char_end':len(source['text'])}]}]
        return output
    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',SlowConnection)
    def reply(context):
        return {**proposal(), 'quote':context['source']['text'],
            'question':'What else do you remember about ' + context['source']['text']}
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty,reply=reply)
    native=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))
    with conversation.client:
        first=conversation.say('I was born in Hobart.')
        conversation.deliver_receipts()
        run,=service(sql,'pending_memoir_background_agents')
        async def scenario():
            running=asyncio.create_task(worker.execute_background_agent(run))
            try:
                async with asyncio.timeout(20):
                    await entered.wait()
                later=[]
                for text in ['We played in the school housing.','Our favourite game was hide-and-seek.']:
                    async with asyncio.timeout(20):
                        reply=await asyncio.to_thread(conversation.say,text)
                    assert reply['conversation_saved'] and reply['reply']
                    later.append(reply)
                    await asyncio.to_thread(conversation.deliver_receipts)
                assert not running.done(), 'Both foreground replies must finish while the first B model is held.'
                assert service(sql,'pending_memoir_background_agents')==[]
                assert len(batches)==1 and len(originals)==(0 if profile_first else 1)
            finally:
                release.set()
                result=await running
            assert result['pending']
            assert sql("select count(*) from public.user_narrator_source where processing_status='succeeded';").stdout.strip()=='1'
            sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
            assert (await worker.execute_background_agent(run))['status']=='finished'
            return later
        later=asyncio.run(scenario())
        assert [[s['text'] for s in group] for group in batches]==[
            ['I was born in Hobart.'],['We played in the school housing.','Our favourite game was hide-and-seek.']]
        assert [s['id'] for s in originals]==[first['accepted_source_id'],*[r['accepted_source_id'] for r in later]]
        last_turn=sql('select client_turn_id from public.user_narrator_source where sequence=3;').stdout.strip()
        response=conversation.client.get('/v1/story/atlas-events',params={'project_id':conversation.project})
        progress=response.json()['skill_progress']['items']
        steps=[s for s in progress if s['phase']=='extract' and s['status']=='saved']
        grouped=[s for s in steps if s['coverage_start']==2 and s['coverage_end']==3]
        assert len(grouped)==2 and len({s['batch_id'] for s in grouped})==1
        assert all(s['client_turn_id']==last_turn and s['started_at']<=s['finished_at'] for s in grouped)
        assert not any(s['skill']=='memoir-memory-context' and s.get('source_id') in {r['accepted_source_id'] for r in later} for s in progress)
        turns=json.loads(sql('select jsonb_agg(client_turn_id order by sequence) from public.user_narrator_source;').stdout)
        replay=subprocess.run(['node',str(Path(__file__).parent/'js/helpers/replay-background-batch.mjs')],
            input=json.dumps({'progress':response.json()['skill_progress'],'turns':turns}),
            text=True,capture_output=True,timeout=20)
        assert replay.returncode==0,replay.stderr


@pytest.mark.parametrize('phase',['profile','extract'])
@pytest.mark.parametrize('restricted',[False,True])
def test_finished_background_output_waits_for_foreground_policy_without_another_model_call(
        sql,tmp_path,monkeypatch,fixed_policy_controls,phase,restricted):
    from apps.api import policy_review
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    entered,release,returned=asyncio.Event(),asyncio.Event(),asyncio.Event()
    reviewing,review_release=threading.Event(),threading.Event()
    calls=[]
    class Connection(ControlledSkillConnection):
        source_choices=('memoir-memory-context',) if phase=='profile' else ('memoir-author-timeline',)
    async def respond(body):
        task=json.loads(body['input'])['payload']
        calls.append(task)
        entered.set()
        await release.wait()
        output=empty_document(body)
        if phase=='profile':
            source=task['source']
            output['profile_patch']=[{'field':'birth_place','value':'Hobart','source_refs':[{
                'source_id':source['id'],'version':source['version'],'quote':source['text'],
                'char_start':0,'char_end':len(source['text'])}]}]
        returned.set()
        return output
    install_document_provider(monkeypatch,respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',Connection)
    complete=policy_review.complete_json
    async def review(name,payload,schema,**options):
        reviewing.set()
        assert await asyncio.to_thread(review_release.wait,10), 'Foreground policy review was not released.'
        return await complete(name,payload,schema,**options)
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty)
    native=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app=FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
        worker_transport=httpx.ASGITransport(app=app))
    with conversation.client:
        first=conversation.say('I was born in Hobart.')
        conversation.deliver_receipts()
        run,=service(sql,'pending_memoir_background_agents')
        monkeypatch.setattr(policy_review,'complete_json',review)
        later_text='Please leave my birthplace out.' if restricted else 'We played in the garden.'
        if restricted:
            fixed_policy_controls.append(('excluded_topic',later_text))
        async def scenario():
            running=asyncio.create_task(worker.execute_background_agent(run))
            foreground=None
            try:
                async with asyncio.timeout(15):
                    await entered.wait()
                    foreground=asyncio.create_task(asyncio.to_thread(conversation.say,later_text))
                    assert await asyncio.to_thread(reviewing.wait,10)
                    release.set()
                    await returned.wait()
                    await asyncio.sleep(.5)
                    assert not running.done(), 'A pending foreground review must hold the result, not abort the batch.'
                    assert len(calls)==1
                    assert sql('select count(*) from public.user_lifetime_profile_receipt;').stdout.strip()=='0'
                    review_release.set()
                    assert (await foreground)['conversation_saved']
                    return await running
            finally:
                release.set()
                review_release.set()
                if foreground is not None:
                    await foreground
                await running
        result=asyncio.run(scenario())
        assert len(calls)==1, 'A reviewed result must not require another model call.'
        first_state=sql(f"select processing_status from public.user_narrator_source where id='{first['accepted_source_id']}';").stdout.strip()
        if restricted:
            assert first_state!='succeeded'
            assert conversation.client.get('/v1/agent/profile').json().get('birth_place') is None
        else:
            assert first_state=='succeeded',result
            if phase=='profile':
                assert conversation.client.get('/v1/agent/profile').json()['birth_place']=='Hobart'


@pytest.mark.parametrize('retry_choices',[[],['memoir-author-timeline','memoir-memory-context']])
def test_failed_extraction_retry_preserves_the_saved_source_skills(sql,tmp_path,monkeypatch,retry_choices):
    from test_conversation_attribution import episode
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    attempts = []
    fail = True
    def extract(packet):
        attempts.append(packet)
        if fail:
            raise RuntimeError('Controlled extraction transport failure')
        return {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        conversation.say('I repaired bicycles in our garden.')
        conversation.deliver_receipts()
        lane = sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
        page = service(sql,'claim_memoir_lane',p_lane_id=lane,p_run_seconds=300)
        service(sql,'yield_lifetime_memoir_lane',p_lane_id=lane,p_token=page['token'])
        sql('update public.user_memoir_lane set available_at=clock_timestamp();')
        async def execute(choices):
            return await conversation.worker.execute_lane(lane,source_work={'source':page['source'],'skills':choices})
        first = asyncio.run(execute(['memoir-author-timeline']))
        assert first['status']=='retry'
        assert len(attempts)==1
        assert sql('select processing_status from public.user_narrator_source;').stdout.strip()!='succeeded'
        fail = False
        conversation.retry()
        sql('update public.user_memoir_lane set available_at=clock_timestamp();')
        second = asyncio.run(execute(retry_choices))
        saved = json.loads(sql('select source_decision from public.user_lifetime_lane_snapshot order by created_at desc limit 1;').stdout)
        assert saved['skills']==['memoir-author-timeline']
        assert second['status']=='saved'
        assert len(attempts)==2, 'Retry must execute the previously selected extraction.'
        assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='1'
        assert sql('select processing_status from public.user_narrator_source;').stdout.strip()=='succeeded'


@pytest.mark.parametrize('legacy_skills,expected',[
    (['memoir-place-journey'], ['memoir-author-timeline']),
    (['memoir-place-journey','memoir-author-timeline','memoir-memory-context'],
     ['memoir-author-timeline','memoir-memory-context']),
])
def test_pending_place_journey_resumes_in_author_timeline(sql,tmp_path,monkeypatch,legacy_skills,expected):
    from uuid import uuid4
    from test_conversation_attribution import episode, reference
    from test_shared_memory_events_postgres import literal

    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    text = 'I lived in Hobart in 2005.'
    turn = str(uuid4())
    fenced = []

    def extract(packet):
        ref = reference(packet, text)
        return {'events':[{**episode(packet,text,title='Living in Hobart'), 'kind':'period',
            'location':{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],'granularity':'city'},
            'location_basis':[ref], 'locationConfidenceScore':1.0}]}

    async def boundary(request, provider):
        job = json.loads(request.content).get('bounded_lane')
        if job and job['phase'] in {'extract','reconcile'}:
            fenced.append(job['fence'])
        return await provider(request)

    conversation = Conversation(sql,tmp_path,monkeypatch,extract,external_boundary=boundary)
    with conversation.client:
        saved = conversation.say(text,turn=turn)
        conversation.deliver_receipts()
        lane = sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
        page = service(sql,'claim_memoir_lane',p_lane_id=lane,p_run_seconds=300)
        snapshot = page['snapshot_id']
        source = {key:page['source'][key] for key in ('id','version','char_start','char_end')}
        legacy = {**page, 'two_lane':{**page['two_lane'],'work_mode':'extract','selected_skills':legacy_skills}}
        decision = literal({'source':source,'skills':legacy_skills})
        sql(f"update public.user_lifetime_lane_snapshot set source_decision={decision} where id='{snapshot}';"
            f"select public.background_skill_receipt({literal(legacy)},'extract','memoir-place-journey','model','completed');"
            "update public.user_background_skill_work set model_invoked=true,model_attempts=1 where skill='memoir-place-journey';")
        service(sql,'yield_lifetime_memoir_lane',p_lane_id=lane,p_token=page['token'])
        sql('update public.user_memoir_lane set available_at=clock_timestamp();')

        result = asyncio.run(conversation.worker.execute_lane(lane))
        assert result['status']=='saved', (result,conversation.last_db_error)
        assert [phase for phase,_ in conversation.admissions if phase!='profile']==['extract','reconcile']
        assert all(f['snapshot_id']==snapshot and f['two_lane']['selected_skills']==expected for f in fenced)
        decision = json.loads(sql(f"select source_decision from public.user_lifetime_lane_snapshot where id='{snapshot}';").stdout)
        assert decision == {'source':source,'skills':expected}
        assert sql("select skill from public.user_background_skill_work where phase='extract' and status='saved';").stdout.strip()=='memoir-author-timeline'
        assert sql('select processing_status from public.user_narrator_source;').stdout.strip()=='succeeded'
        assert sql('select count(*) from public.user_memory_event;').stdout.strip()=='1'
        assert sql('select s.client_turn_id from public.user_memory_event_source r join public.user_narrator_source s '
                   f"on s.id=r.source_id where r.source_id='{saved['accepted_source_id']}';").stdout.strip()==turn


@pytest.mark.parametrize('choices,text,phases',[
    ((), 'Hello.', []),
    (('memoir-author-timeline',), 'I repaired bicycles in our garden.', ['events']),
    (('memoir-memory-context',), 'I was born in 1960.', ['profile_patch']),
    (('memoir-memory-context','memoir-author-timeline'), 'My name is Avery. I lived in Hobart.', ['profile_patch','events','decisions']),
])
def test_lane_b_selects_each_source_skill_or_none_independently_of_lane_a_and_rounds(
        sql,tmp_path,monkeypatch,choices,text,phases):
    from test_conversation_attribution import episode, reference
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    nested = []
    nested_metadata = []
    class ChoosingConnection(ControlledSkillConnection):
        source_choices = ()
    def respond(body):
        task=json.loads(body['input'])
        fields=body['text']['format']['schema']['properties']
        phase='profile_patch' if 'profile_patch' in fields else 'decisions' if 'decisions' in fields else 'events'
        nested.append(phase)
        nested_metadata.append(body['metadata'])
        output=empty_document(body)
        if phase=='profile_patch':
            source=task['payload']['source']
            named='memoir-author-timeline' in choices
            quote='My name is Avery.' if named else source['text']
            output['profile_patch']=[{'field':'name' if named else 'birth_year','value':'Avery' if named else 1960,'source_refs':[{
                'source_id':source['id'],'version':source['version'],'quote':quote,
                'char_start':0,'char_end':len(quote)}]}]
        elif phase == 'events' and 'Hobart' in text:
            packet=task['payload']
            ref=reference(packet, 'I lived in Hobart.')
            output['events']=[{**episode(packet, ref['quote'], title='Living in Hobart'), 'kind':'period',
                'location':{'place':'Hobart','hierarchy':['Earth','Australia','Hobart'],'granularity':'city'},
                'location_basis':[ref], 'locationConfidenceScore':1.0}]
        return output
    install_document_provider(monkeypatch, respond)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',ChoosingConnection)
    conversation = Conversation(sql,tmp_path / 'conversation',monkeypatch,empty,work='reply_only')
    native = CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
        base_url='http://synthetic.invalid',api_key='synthetic')
    app = FastAPI()
    @app.post('/internal/codex/turn')
    async def turn(payload:WorkerTurnInput):
        return await native.turn(payload)
    async def drain():
        worker = MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
            worker_transport=httpx.ASGITransport(app=app))
        for _ in range(4):
            sql('update public.user_memoir_background_agent set available_at=clock_timestamp();')
            pending = service(sql,'pending_memoir_background_agents')
            if not pending:
                return
            for run in pending:
                await worker.execute_background_agent(run)
        pytest.fail('Selected background source work did not settle')
    with conversation.client:
        conversation.say('Hello.')
        conversation.deliver_receipts()
        asyncio.run(drain())
        assert nested == [], 'Explicitly selecting no skills must not call extraction/profile models.'
        ChoosingConnection.source_choices = choices
        saved = conversation.say(text)
        conversation.deliver_receipts()
        asyncio.run(drain())
        assert nested == phases
        assert all(meta['trace_name']=='memoir-atlas' for meta in nested_metadata)
        assert [meta['generation_name'] for meta in nested_metadata]==[
            'memoir-memory-context.profile' if phase=='profile_patch' else
            'memoir-author-timeline.reconcile' if phase=='decisions' else 'memoir-author-timeline.extract'
            for phase in phases]
        assert sql('select bool_and(processing_status=\'succeeded\') from public.user_narrator_source;').stdout.strip() == 't'
        if choices == ('memoir-memory-context',):
            assert sql('select profile->>\'birth_year\' from public.user_profile;').stdout.strip() == '1960'
            assert sql('select max(ordinal) from public.user_completed_round;').stdout.strip() == '2'
        if choices == ('memoir-memory-context','memoir-author-timeline'):
            assert sql('select journeys->0->>\'place\' from public.user_lifetime_place_journey;').stdout.strip() == 'Hobart'
            assert sql('select profile->>\'name\' from public.user_profile;').stdout.strip() == 'Avery'
        if 'memoir-author-timeline' in choices:
            assert sql("select distinct skill from public.user_background_skill_work where phase='extract' and model_invoked;").stdout.strip() == 'memoir-author-timeline'
        assert saved['conversation_saved']


def test_background_agent_selects_skills_and_persists_results_after_the_reply(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_DISABLE_PRIVDROP','1')
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path / 'tasks.sqlite'))
    monkeypatch.delenv('MEMORY_SPARK_HISTORICAL_NEWS',raising=False)
    monkeypatch.setattr('apps.api.codex_worker_service.CodexConnection',ControlledSkillConnection)
    install_document_provider(monkeypatch)
    ControlledSkillConnection.instances=[]
    ControlledSkillConnection.selected=[]
    conversation=Conversation(sql,tmp_path / 'conversation',monkeypatch,empty)
    with conversation.client:
        delivered=conversation.say('I repaired bicycles in our garden.')
        assert delivered['conversation_saved']
        conversation.deliver_receipts()
        run_id,=service(sql,'pending_memoir_background_agents')
        native_worker=CodexWorker(home_root=tmp_path / 'worker',command=['controlled'],
            base_url='http://synthetic.invalid',api_key='synthetic')
        app=FastAPI()
        @app.post('/internal/codex/turn')
        async def turn(payload:WorkerTurnInput):
            return await native_worker.turn(payload)
        async def scenario():
            worker=MemoryEventWorker(Broker(sql),worker_url='http://controlled.invalid',worker_secret='synthetic',
                worker_transport=httpx.ASGITransport(app=app))
            result=await worker.execute_background_agent(run_id)
            assert result['status']=='finished',result
        asyncio.run(scenario())
        assert 'memoir-author-timeline' in ControlledSkillConnection.selected
        assert 'memoir-interview-guidance' not in ControlledSkillConnection.selected
        assert sql("select count(*) from public.user_memoir_lane where skill='guidance';").stdout.strip()=='0'
        assert sql('select bool_and(processing_status=\'succeeded\') from public.user_narrator_source;').stdout.strip()=='t'
        assert sql('select token is null from public.user_memoir_background_agent;').stdout.strip()=='t'
        assert conversation.admissions==[], 'The old fixed worker request path must not execute the B work.'
        next_reply=conversation.say('What happens to my memories?')
        assert next_reply['conversation_saved']
