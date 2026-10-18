"""Conversation → real Lane B → authorized attribution, on disposable PostgreSQL."""
import asyncio
import inspect
import json
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes
from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.memory_event_worker import MemoryEventWorker, MemoirLaneBroker
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_background_profile_workflow import Broker, FixturePublication, worker_response, database
from test_lifetime_memory_postgres import event_database, private_database, attachment_database
from test_agent_commit_postgres import OWNER, OTHER
from test_name_only_opening import proposal
from test_shared_memory_events_postgres import literal, rpc, sql


class Conversation:
    def __init__(self, sql, tmp_path, monkeypatch, extract, *, work='extract', name=None, family=True, strategy=None):
        self.sql, self.extract, self.project = sql, extract, None
        self.admissions = []
        self.fail_immediate = False
        self.last_db_error = ''
        sql('update public.lifetime_two_lane_rollout set enabled=true;')
        monkeypatch.setenv('MEMOIR_TWO_LANES', '1')
        monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
        if strategy:
            monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY','1')
            monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','two-lane-v1')
            sql('update public.lifetime_two_lane_rollout set strategy_enabled=true,strategy_shadow=false;')
        monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
        async def provider(request):
            body = json.loads(request.content)
            bounded = body.get('bounded_lane')
            if bounded:
                packet = json.loads(bounded['packet'])['payload']
                self.admissions.append((bounded['phase'], packet))
                if bounded['phase'] == 'profile':
                    output = {'profile_patch': []}
                elif bounded['phase'] == 'prepare':
                    output = {'event_id':packet['partition']['id'], 'context':'Supported original testimony.',
                        'source_refs':packet['partition']['source_refs']}
                elif bounded['phase'] == 'draft':
                    from test_progressive_composer import draft_all
                    output = draft_all(packet)
                elif bounded['phase'] == 'review':
                    output = {'ready_for_user_review':True,'publication_approved':False,'findings':[]}
                else:
                    output = self.extract(packet)
                if inspect.isawaitable(output):
                    output = await output
                if bounded['phase'] == 'extract' and (bounded['fence'].get('two_lane') or {}).get('strategy_mode'):
                    selected_strategy = strategy or 'explore'
                    output = {**output,'strategy_proposal':{'strategy':selected_strategy,
                        'objective':'clarify_order' if selected_strategy == 'shape' else 'follow_story','focus_event_ids':[]}}
            else:
                if self.fail_immediate:
                    return httpx.Response(503)
                output = proposal(mode=work, name=name, question='What happened next?')
                focus = body.get('interview_context', {}).get('workspace_focus', {})
                if focus.get('event_id'):
                    output['plan']['active_event_id'] = focus['event_id']
                    output['plan']['candidates'][0]['context']['event_id'] = focus['event_id']
                if strategy:
                    from test_interview_strategy import wire
                    pause = body['interview_context']['source']['text'].startswith('Please stop.')
                    output = wire(question=None if pause else 'What happened next?',used_strategy=strategy,
                        selection_reason='pause' if pause else 'latest_story',stopped=bool(pause),work={'mode':work,'name':name})
            return worker_response(request, output)
        transport = httpx.MockTransport(provider)
        monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path,
            worker_url='http://controlled.invalid', worker_secret='synthetic', worker_transport=transport))
        def worker_sql(query, **options):
            result = sql(query, **options)
            if result.returncode:
                self.last_db_error = result.stderr
            return result
        self.worker = MemoryEventWorker(Broker(worker_sql), worker_url='http://controlled.invalid',
            worker_secret='synthetic', worker_transport=transport)
        self.worker.lane_publisher = FixturePublication(sql.publication_dsn, authenticated_owner=OWNER)
        def storage_factory(authorization):
            storage = PostgresRest(sql, OTHER if authorization == 'Bearer another-owner' else OWNER).storage()
            if family:
                storage.story_entitlement = lambda: {'status':'paid','plan_key':'family_memoir_v1','timeline':True,'family_tree':True}
            return storage
        self.client = TestClient(create_app(MemoryStore(), story_storage_factory=storage_factory), raise_server_exceptions=False)

    def say(self, text, turn=None, **options):
        payload = {'text': text, 'client_turn_id': turn or str(uuid4()), **options}
        if self.project:
            payload['project_id'] = self.project
        response = self.client.post('/v1/agent/turn', json=payload)
        assert response.status_code == 200, response.text
        self.project = response.json()['project_id']
        return response.json()

    def drain(self):
        lane = self.sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
        for _ in range(64):
            outcome = asyncio.run(self.worker.execute_lane(lane))
            if outcome.get('retrieval_complete') or outcome['status'] in {'finished', 'deferred'}:
                return outcome
        pytest.fail('Bounded Lane B did not settle')

    def attribution(self, source_id, **params):
        response = self.client.get(f'/v1/story/sources/{self.project}/{source_id}/attribution', params=params)
        assert response.status_code == 200, response.text
        return response.json()

    def retry(self):
        response = self.client.post('/v1/story/memory/retry', json={'project_id':self.project})
        assert response.status_code == 200, response.text

    def deliver_receipts(self):
        async def run():
            async def postgrest(request):
                arguments = ','.join(key + '=>' + ('null' if value is None else literal(value))
                    for key,value in json.loads(request.content).items())
                query = 'set role service_role; select to_jsonb(public.' + request.url.path.rsplit('/',1)[-1] + '(' + arguments + '));'
                result = await asyncio.to_thread(self.sql,query)
                value = result.stdout.strip()
                return httpx.Response(200, content=value.splitlines()[-1] if value else 'null',
                    headers={'content-type':'application/json'})
            async with httpx.AsyncClient(transport=httpx.MockTransport(postgrest)) as client:
                broker = MemoirLaneBroker(url='http://disposable.invalid', key='synthetic',client=client)
                for _ in range(64):
                    await broker.drain_once()
                    if not await broker.rpc('pending_memoir_receipts',p_limit=1):
                        return
                pytest.fail('Bounded receipt delivery did not settle')
        return asyncio.run(run())


def empty(_packet):
    return {'events': [], 'place_journeys': [], 'prepared_questions': []}


def reference(packet, quote):
    source = packet['sources'][0]
    return {'source_id': source['id'], 'version': source['version'], 'quote': quote,
        'char_start': None, 'char_end': None}


def episode(packet, quote, *, title='Bicycle accident', existing=None):
    event = {'kind': 'event', 'title': title, 'source_refs': [reference(packet, quote)]}
    if existing:
        event.update(existing_id=existing['id'], expected_revision=existing['revision'])
    return event


def test_unrelated_event_correction_preserves_non_story_and_withheld_classifications(sql,tmp_path,monkeypatch):
    conversation = Conversation(sql,tmp_path,monkeypatch,
        lambda packet: {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'])]},family=True)
    with conversation.client:
        story = conversation.say('I repaired a bicycle in Chengde.')
        conversation.drain()
        event = conversation.attribution(story['accepted_source_id'])['items'][0]['event']
        thanks = conversation.say('Thank you.')
        conversation.drain()
        private = conversation.say('Do not record this.')
        conversation.drain()
        before = {saved['accepted_source_id']:conversation.attribution(saved['accepted_source_id'])
            for saved in (thanks,private)}
        assert before[thanks['accepted_source_id']]['items'][0]['disposition'] == 'non_story'
        assert before[private['accepted_source_id']]['items'][0]['disposition'] == 'withheld'
        patch = {'temporal':{'expression':'1966','precision':'year','year_start':1966,'year_end':1966}}
        rpc(sql,'correct_user_memory_event',f"{literal(conversation.project)},'{event['id']}',{event['revision']},"
            f"{literal(patch)}::jsonb,'The year was 1966.'")
        for source,original in before.items():
            current = conversation.attribution(source)
            assert current['policy_epoch'] > original['policy_epoch']
            assert current['items'] == original['items']
            assert (current['complete'],current['resolved']) == (original['complete'],original['resolved'])


def test_conflicting_place_correction_is_unresolved_not_two_authoritative_settings(sql,tmp_path,monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB',str(tmp_path/'receipts.sqlite3'))
    first = 'At age twelve I had a bicycle accident in Chengde.'
    correction = 'Actually, that bicycle accident was in Beijing, not Chengde.'
    def extract(packet):
        text = packet['sources'][0]['text']
        existing = packet['events'][0] if packet['events'] else None
        event = episode(packet,text,existing=existing)
        if not existing:
            event['temporal'] = {'expression':'age twelve','precision':'age','basis':[reference(packet,'age twelve')]}
        place = 'Chengde' if text == first else 'Beijing'
        return {**empty(packet),'events':[event],'event_places':[
            {'event_index':0,'role':'setting','place':{'place':place,'hierarchy':['Earth','China',place],
                'granularity':'city'},'source_ref':reference(packet,text)}]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract,family=True)
    with conversation.client:
        saved = conversation.say(first)
        conversation.drain()
        original = conversation.attribution(saved['accepted_source_id'])['items'][0]['event']
        assert original['places'][0]['place']['place'] == 'Chengde'
        corrected = conversation.say(correction)
        conversation.drain()
        event = conversation.attribution(corrected['accepted_source_id'])['items'][0]['event']
        assert event['id'] == original['id'] and event['temporal']['expression'] == 'age twelve'
        assert event['places'] == []
        assert event['place_conflicts'] == ['setting']
        path = f'/v1/story/events/{conversation.project}/{event["id"]}/places'
        places = conversation.client.get(path).json()['items']
        assert {item['place']['place'] for item in places} == {'Chengde','Beijing'}
        assert {item['status'] for item in places} == {'conflicted'}
        # Subsequent reconciliation and the composer see uncertainty, not both facts.
        def continuation(packet):
            context = packet['events'][0]
            assert context['places'] == [] and context['place_conflicts'] == ['setting']
            return {**empty(packet),'events':[episode(packet,packet['sources'][0]['text'],existing=context)]}
        conversation.extract = continuation
        conversation.say('My father helped me up after that bicycle accident.')
        conversation.drain()
        for _ in range(2):
            conversation.say('Thank you.')
            conversation.drain()
        conversation.deliver_receipts()
        lane = sql("select id from public.user_memoir_lane where skill='composer';").stdout.strip()
        outcome = asyncio.run(conversation.worker.execute_lane(lane))
        assert outcome.get('retrieval_complete'), (outcome,conversation.last_db_error)
        draft = next(packet for phase,packet in conversation.admissions if phase == 'draft')
        context = next(item for item in draft['request']['context']['attribution_coverage']['events'] if item['id'] == event['id'])
        assert context['places'] == [] and context['place_conflicts'] == ['setting']
        assert len([phase for phase,_ in conversation.admissions if phase == 'extract']) == 3


def test_repeated_support_for_the_same_place_does_not_create_a_conflict(sql,tmp_path,monkeypatch):
    def extract(packet):
        text = packet['sources'][0]['text']
        return {**empty(packet),'events':[episode(packet,text,existing=packet['events'][0] if packet['events'] else None)],
            'event_places':[{'event_index':0,'role':'setting','place':{'place':'Chengde',
                'hierarchy':['Earth','China','Chengde'],'granularity':'city'},'source_ref':reference(packet,text)}]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        conversation.say('I had a bicycle accident in Chengde.')
        conversation.drain()
        saved = conversation.say('That bicycle accident was certainly in Chengde.')
        conversation.drain()
        event = conversation.attribution(saved['accepted_source_id'])['items'][0]['event']
        assert event['place_conflicts'] == [] and event['places_complete']
        assert {item['place']['place'] for item in event['places']} == {'Chengde'}


def test_free_source_attribution_cannot_bypass_family_timeline_access(sql,tmp_path,monkeypatch):
    text = 'At age twelve I had a bicycle accident in Chengde.'
    def extract(packet):
        event = episode(packet,text)
        event['temporal'] = {'expression':'age twelve','precision':'age','basis':[reference(packet,'age twelve')]}
        return {**empty(packet),'events':[event],'event_places':[
            {'event_index':0,'role':'setting','place':{'place':'Chengde','hierarchy':['Earth','China','Chengde'],
                'granularity':'city'},'source_ref':reference(packet,text)}]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    with conversation.client:
        saved = conversation.say(text)
        path = f'/v1/story/sources/{conversation.project}/{saved["accepted_source_id"]}/attribution'
        # The display gate is stable before and after background facts exist.
        pending = conversation.client.get(path)
        conversation.drain()
        response = conversation.client.get(path)
        assert response.status_code == 403, response.text
        assert pending.status_code == 403
        assert 'Chengde' not in response.text and 'age twelve' not in response.text
        # Free users retain basic source-processing counts, not event context.
        sources = conversation.client.get('/v1/story/sources',params={'project_id':conversation.project}).json()['sources']
        assert sources[0]['attribution']['linked_passages'] == 1
        assert 'event' not in sources[0]['attribution'] and 'places' not in sources[0]['attribution']


def test_empty_extraction_accounts_for_unresolved_testimony_without_claiming_resolution(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch, empty)
    with conversation.client:
        saved = conversation.say('I remember the bicycle accident, but not when it happened.')
        source = saved['accepted_source_id']
        pending = conversation.attribution(source)
        assert pending['complete'] is False
        assert pending['items'][0]['disposition'] == 'pending'
        outcome = conversation.drain()
        readback = conversation.attribution(source)
        assert readback['complete'] is True and readback['resolved'] is False
        assert readback['items'][0]['disposition'] == 'unresolved'
        assert readback['items'][0]['reason'] == 'no_supported_event'
        assert readback['items'][0]['event'] is None
        sources = conversation.client.get('/v1/story/sources', params={'project_id':conversation.project}).json()['sources']
        assert sources[0]['attribution']['complete'] and not sources[0]['attribution']['resolved']
        assert sources[0]['attribution']['unresolved_passages'] == 1
        assert outcome['attribution_pages'][0]['complete'] and not outcome['attribution_pages'][0]['resolved']
        assert outcome['attribution_pages'][0]['timeline_method'] == 'model'
        count = len(conversation.admissions)
        conversation.drain()
        assert len(conversation.admissions) == count


def test_genuine_thanks_is_accounted_without_extraction_despite_an_extract_hint(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch, empty)
    with conversation.client:
        saved = conversation.say('Thank you!')
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert readback['complete'] and readback['resolved']
        assert {item['disposition'] for item in readback['items']} == {'non_story'}
        assert not [phase for phase, _ in conversation.admissions if phase == 'extract']


def test_continuing_testimony_reuses_event_time_and_setting_without_another_journey(sql, tmp_path, monkeypatch):
    first_text = 'At age twelve I had a bicycle accident in Chengde.'
    followup = 'After that bicycle accident my father helped me up.'
    def extract(packet):
        text = packet['sources'][0]['text']
        if text == first_text:
            event = episode(packet, text)
            event.update(life_stage='childhood', stage_evidence=[reference(packet, 'age twelve')],
                temporal={'expression':'age twelve', 'precision':'age', 'basis':[reference(packet, 'age twelve')]})
            return {**empty(packet), 'events':[event], 'event_places':[{'event_index':0, 'role':'setting',
                'place':{'place':'Chengde', 'hierarchy':['Earth','China','Hebei','Chengde'], 'granularity':'city'},
                'source_ref':reference(packet, text)}]}
        assert text == followup
        existing = packet['events'][0]
        assert existing['temporal']['expression'] == 'age twelve'
        return {**empty(packet), 'events':[episode(packet, text, existing=existing)]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        first = conversation.say(first_text)
        conversation.drain()
        initial = conversation.attribution(first['accepted_source_id'])
        linked = next(item for item in initial['items'] if item['disposition'] == 'linked')
        event = linked['event']
        assert event['places'][0]['role'] == 'setting'
        assert event['places'][0]['place']['place'] == 'Chengde'
        second = conversation.say(followup)
        conversation.drain()
        later = conversation.attribution(second['accepted_source_id'])
        assert later['resolved'] is True
        assert later['items'][0]['event']['id'] == event['id']
        assert later['items'][0]['event']['temporal']['expression'] == 'age twelve'
        assert later['items'][0]['event']['temporal'].get('year_start') is None
        assert later['items'][0]['event']['places'][0]['place']['place'] == 'Chengde'
        assert len([phase for phase, _ in conversation.admissions if phase == 'extract']) == 2
        assert conversation.client.get('/v1/story/readiness', params={'project_id':conversation.project}).json()['derived_workspace']['places'] == []


def test_vague_yes_keeps_delivered_event_context_without_confirming_testimony(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet), 'events':[episode(packet, packet['sources'][0]['text'])]})
    with conversation.client:
        first = conversation.say('I had a bicycle accident.')
        conversation.drain()
        event = conversation.attribution(first['accepted_source_id'])['items'][0]['event']
        conversation.say('Please continue.', workspace_focus={'kind':'explore_memory',
            'event_id':event['id'], 'event_revision':event['revision']})
        conversation.drain()
        before = conversation.client.get('/v1/story/readiness', params={'project_id':conversation.project}).json()['stages']
        yes = conversation.say('Yes.')
        conversation.drain()
        readback = conversation.attribution(yes['accepted_source_id'])
        assert readback['resolved'] is False
        assert readback['items'][0]['disposition'] == 'unresolved'
        assert readback['items'][0]['event'] is None
        assert readback['items'][0]['context_event']['id'] == event['id']
        after = conversation.client.get('/v1/story/readiness', params={'project_id':conversation.project}).json()['stages']
        assert before == after
        assert len([phase for phase, _ in conversation.admissions if phase == 'extract']) == 1


def test_private_recording_boundary_is_withheld_not_non_story(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch, empty)
    with conversation.client:
        saved = conversation.say('Do not record this.')
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert {item['disposition'] for item in readback['items']} == {'withheld'}
        assert readback['resolved'] is False
        assert not [phase for phase, _ in conversation.admissions if phase == 'extract']


@pytest.mark.parametrize('text,work,name,disposition', [
    ('Hello!', 'extract', None, 'non_story'), ('谢谢。', 'extract', None, 'non_story'),
    ('What can you do?', 'reply_only', None, 'non_story'),
    ('My name is Joan.', 'reply_only', 'Joan', 'non_story'), ('Please stop.', 'extract', None, 'non_story'),
    ('Yes.', 'extract', None, 'unresolved'), ('There.', 'reply_only', None, 'unresolved'),
])
def test_small_no_story_rules_do_not_require_a_model(sql, tmp_path, monkeypatch, text, work, name, disposition):
    conversation = Conversation(sql, tmp_path, monkeypatch, empty, work=work, name=name)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        assert {item['disposition'] for item in conversation.attribution(saved['accepted_source_id'])['items']} == {disposition}
        assert not [phase for phase, _ in conversation.admissions if phase == 'extract']
        if name:
            assert conversation.client.get('/v1/agent/profile').json()['name'] == name


def test_short_new_facts_override_a_reply_only_hint(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet), 'events':[episode(packet, packet['sources'][0]['text'])]}, work='reply_only')
    with conversation.client:
        saved = conversation.say('My father helped me up.')
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert readback['resolved'] and readback['items'][0]['event'] is not None
        assert len([phase for phase, _ in conversation.admissions if phase == 'extract']) == 1


def test_partial_reply_exposes_unlinked_passages_and_a_mixed_control(sql, tmp_path, monkeypatch):
    story, control, unresolved = '我记得那次摔车。', '先别问问题。', '另外有件事情我还没想清楚。'
    text = story + control + unresolved
    def extract(packet):
        return {**empty(packet), 'events':[episode(packet, story)], 'passage_dispositions':[
            {'disposition':'non_story', 'reason':'conversation_control', 'source_ref':reference(packet, control)}]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert readback['complete'] and not readback['resolved']
        assert [item['disposition'] for item in readback['items']] == ['linked','non_story','unresolved']
        assert [(item['char_start'],item['char_end']) for item in readback['items']] == [
            (0,len(story)), (len(story),len(story+control)), (len(story+control),len(text))]
        page1 = conversation.attribution(saved['accepted_source_id'], limit=1)
        assert len(page1['items']) == 1 and page1['next_cursor']
        page2 = conversation.attribution(saved['accepted_source_id'], cursor=page1['next_cursor'], limit=1)
        assert page2['items'][0]['disposition'] == 'non_story' and page2['next_cursor']
        wrong = conversation.client.get(f'/v1/story/sources/{conversation.project}/{saved["accepted_source_id"]}/attribution',
            headers={'Authorization':'Bearer another-owner'})
        assert wrong.status_code >= 400 and 'Bicycle accident' not in wrong.text
        project_mismatch = conversation.client.get(f'/v1/story/sources/another-project/{saved["accepted_source_id"]}/attribution')
        assert project_mismatch.status_code >= 400 and 'Bicycle accident' not in project_mismatch.text


def test_event_places_are_selective_roles_not_every_place_for_every_event(sql, tmp_path, monkeypatch):
    move = 'I moved from Beijing to Chengde.'
    relative = 'My father worked in Hobart.'
    def extract(packet):
        events = [episode(packet, move, title='My move'), episode(packet, relative, title="Father's work")]
        events[1]['attribution'] = 'father'
        associations = []
        for index, role, place, country in [(0,'origin','Beijing','China'), (0,'destination','Chengde','China'), (1,'setting','Hobart','Australia')]:
            associations.append({'event_index':index, 'role':role, 'place':{'place':place,'hierarchy':['Earth',country,place],
                'granularity':'city'}, 'source_ref':reference(packet, [move, relative][index])})
        return {**empty(packet), 'events':events, 'event_places':associations}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        saved = conversation.say(move + relative)
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert readback['resolved']
        assert len(readback['items']) == 2
        first, second = [item['event'] for item in readback['items']]
        assert {(p['role'],p['place']['place']) for p in first['places']} == {('origin','Beijing'),('destination','Chengde')}
        assert {(p['role'],p['place']['place']) for p in second['places']} == {('setting','Hobart')}
        assert first['id'] != second['id']


@pytest.mark.parametrize('failure', ['blocked', 'failed'])
def test_attribution_does_not_block_a_and_failed_work_remains_pending(sql, tmp_path, monkeypatch, failure):
    entered, release = asyncio.Event(), asyncio.Event()
    async def extract(packet):
        entered.set()
        await release.wait()
        if failure == 'failed':
            raise RuntimeError('Controlled provider unavailable')
        return {**empty(packet), 'events':[episode(packet, packet['sources'][0]['text'])]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        first = conversation.say('I remember the bicycle accident.')
        # Keep worker/provider on this loop; foreground HTTP uses a separate thread.
        async def direct_scenario():
            lane = sql("select id from public.user_memoir_lane where skill='timeline';").stdout.strip()
            background = asyncio.create_task(conversation.worker.execute_lane(lane))
            await entered.wait()
            try:
                async with asyncio.timeout(15):
                    reply = await asyncio.to_thread(conversation.say, 'Thank you.')
                assert reply['conversation_saved'] and not background.done()
            finally:
                release.set()
                await background
        asyncio.run(direct_scenario())
        if failure == 'failed':
            assert conversation.attribution(first['accepted_source_id'])['items'][0]['disposition'] == 'pending'
            conversation.extract = lambda packet: {**empty(packet), 'events':[episode(packet, packet['sources'][0]['text'])]}
            conversation.retry()
        conversation.drain()
        assert conversation.attribution(first['accepted_source_id'])['resolved']


@pytest.mark.parametrize('quote,attribution', [
    ('My father said I was born in 1930.','father'),
    ('My father said I was born in 1930.',None),
    ('I was born in 1930.',None),
])
def test_a_relatives_quoted_birth_year_is_not_a_narrator_age_anchor(sql, tmp_path, monkeypatch, quote, attribution):
    text = 'My father said I was born in 1930. At age twelve I had a bicycle accident.'
    def extract(packet):
        event = episode(packet, text)
        birth = reference(packet, quote)
        if attribution:
            birth['attribution'] = attribution
        event['temporal'] = {'expression':'age twelve','precision':'age','year_start':1942,'year_end':1942,
            'basis':[birth, reference(packet, 'age twelve')]}
        return {**empty(packet), 'events':[event]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert not readback['complete'] and not readback['resolved']
        assert all(item['event'] is None for item in readback['items'])
        def unknown(packet):
            event = episode(packet, text)
            event['temporal'] = {'expression':'age twelve','precision':'age','basis':[reference(packet, 'age twelve')]}
            return {**empty(packet),'events':[event]}
        conversation.extract = unknown
        conversation.retry()
        conversation.drain()
        corrected = conversation.attribution(saved['accepted_source_id'])
        assert corrected['resolved']
        assert corrected['items'][0]['event']['temporal']['expression'] == 'age twelve'
        assert corrected['items'][0]['event']['temporal']['year_start'] is None


def test_a_withheld_episode_does_not_discard_an_independent_allowed_episode(sql, tmp_path, monkeypatch):
    private = 'I had a bicycle accident in Chengde.'
    allowed = 'I worked as a carpenter in Hobart.'
    text = private + ' Do not record this event. ' + allowed
    def extract(packet):
        return {**empty(packet), 'events':[episode(packet, private), episode(packet, allowed, title='Carpentry')],
            'event_places':[{'event_index':index, 'role':'setting', 'place':{'place':place,
                'hierarchy':['Earth',country,place], 'granularity':'city'}, 'source_ref':reference(packet, quote)}
                for index,place,country,quote in [(0,'Chengde','China',private),(1,'Hobart','Australia',allowed)]]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert readback['complete'] and not readback['resolved']
        assert any(item['disposition'] == 'withheld' and item['char_start'] == 0 for item in readback['items'])
        linked = [item['event'] for item in readback['items'] if item['disposition'] == 'linked']
        assert len(linked) == 1
        assert linked[0]['places'][0]['place']['place'] == 'Hobart'


def test_partial_unicode_coverage_resumes_after_worker_restart_without_reextracting_saved_windows(sql, tmp_path, monkeypatch):
    text = '我记得那次摔车。' * 350
    fail = True
    def extract(packet):
        source = packet['sources'][0]
        if source['char_start'] and fail:
            raise RuntimeError('Controlled interruption after first window')
        quote = source['text'][:2000]
        event = episode(packet, quote, existing=packet['events'][0] if packet['events'] else None)
        event['source_refs'][0].update(char_start=0, char_end=len(quote))
        return {**empty(packet),'events':[event]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        partial = conversation.attribution(saved['accepted_source_id'])
        assert not partial['complete'] and not partial['resolved']
        assert any(item['disposition'] == 'linked' for item in partial['items'])
        fail = False
        replacement = MemoryEventWorker(Broker(sql), worker_url='http://controlled.invalid', worker_secret='synthetic',
            worker_transport=conversation.worker.worker_transport)
        replacement.lane_publisher = FixturePublication(sql.publication_dsn, authenticated_owner=OWNER)
        conversation.worker = replacement
        conversation.retry()
        conversation.drain()
        final = conversation.attribution(saved['accepted_source_id'])
        assert final['complete']
        assert len({item['key'] for item in final['items']}) == len(final['items'])
        packets = [packet['sources'][0] for phase,packet in conversation.admissions if phase == 'extract']
        assert sum(source['char_start'] == 0 for source in packets) == 1
        assert all(len(source['text']) <= 2304 for source in packets)
        event_ids = {item['event']['id'] for item in final['items'] if item['event']}
        assert len(event_ids) == 1


def test_accepted_testimony_is_attributed_after_a_failed_reply_without_inventing_a_round(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet),'events':[episode(packet, packet['sources'][0]['text'])]})
    with conversation.client:
        turn, text = str(uuid4()), 'I remember the bicycle accident.'
        greeting = conversation.client.post('/v1/agent/greeting', json={'action':'begin'})
        assert greeting.status_code == 200, greeting.text
        conversation.project = greeting.json()['project_id']
        conversation.fail_immediate = True
        failed = conversation.client.post('/v1/agent/turn', json={'text':text,'client_turn_id':turn,'project_id':conversation.project})
        assert failed.status_code >= 400
        response = conversation.client.get('/v1/agent/turns/' + turn, params={'project_id':conversation.project})
        assert response.status_code == 200, response.text
        receipt = response.json()
        assert receipt['state'] == 'source_accepted' and receipt['recall_status']['rounds_completed'] == 0
        conversation.project = receipt['project_id']
        conversation.drain()
        assert conversation.attribution(receipt['source_id'])['resolved']
        conversation.fail_immediate = False
        recovered = conversation.say(text, turn=turn)
        assert recovered['accepted_source_id'] == receipt['source_id']
        conversation.drain()
        final = conversation.client.get('/v1/agent/turns/' + turn, params={'project_id':conversation.project}).json()
        assert final['state'] == 'conversation_saved' and final['recall_status']['rounds_completed'] == 1
        assert len([phase for phase, _ in conversation.admissions if phase == 'extract']) == 1


@pytest.mark.parametrize('birth,story,expression', [
    ('I was born in 1960.', 'At age twelve I had a bicycle accident.', 'age twelve'),
    ('我1960年出生。', '我十二岁时摔过自行车。', '十二岁'),
])
def test_age_calculation_uses_exact_narrator_birth_evidence_without_turning_it_into_event_narration(sql, tmp_path, monkeypatch, birth, story, expression):
    def extract(packet):
        event = episode(packet, story)
        event.update(life_stage='childhood',stage_evidence=[reference(packet, expression)],
            temporal={'expression':expression,'precision':'age','year_start':1972,'year_end':1973,
                'basis':[reference(packet, birth),reference(packet, expression)]})
        return {**empty(packet),'events':[event],'passage_dispositions':[
            {'disposition':'non_story','reason':'profile_introduction','source_ref':reference(packet,birth)}]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        saved = conversation.say(birth + story)
        conversation.drain()
        readback = conversation.attribution(saved['accepted_source_id'])
        assert readback['resolved'], conversation.last_db_error
        assert readback['items'][0]['disposition'] == 'non_story'
        linked = [item for item in readback['items'] if item['event']]
        assert all(item['char_start'] >= len(birth) for item in linked)
        assert linked[0]['event']['temporal'] == {'expression':expression,'precision':'age','year_start':1972,'year_end':1973}


def test_a_recent_event_without_a_delivered_question_reference_is_not_context_authority(sql, tmp_path, monkeypatch):
    conversation = Conversation(sql, tmp_path, monkeypatch,
        lambda packet: {**empty(packet),'events':[episode(packet, packet['sources'][0]['text'])]})
    with conversation.client:
        conversation.say('I had a bicycle accident.')
        conversation.drain()
        yes = conversation.say('Yes.')
        conversation.drain()
        item = conversation.attribution(yes['accepted_source_id'])['items'][0]
        assert item['disposition'] == 'unresolved' and item['context_event'] is None and item['event'] is None


def test_place_readback_is_paged_and_keeps_the_existing_family_gate(sql, tmp_path, monkeypatch):
    text = 'I moved from Beijing to Chengde.'
    def extract(packet):
        return {**empty(packet),'events':[episode(packet,text)],'event_places':[
            {'event_index':0,'role':role,'place':{'place':place,'hierarchy':['Earth','China',place],'granularity':'city'},
                'source_ref':reference(packet,text)} for role,place in [('origin','Beijing'),('destination','Chengde')]]}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract, family=True)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        event = conversation.attribution(saved['accepted_source_id'])['items'][0]['event']
        path = f'/v1/story/events/{conversation.project}/{event["id"]}/places'
        first = conversation.client.get(path, params={'limit':1})
        assert first.status_code == 200, first.text
        assert len(first.json()['items']) == 1 and first.json()['next_cursor']
        second = conversation.client.get(path, params={'limit':1,'cursor':first.json()['next_cursor']})
        assert second.status_code == 200 and len(second.json()['items']) == 1 and second.json()['complete']
        assert {first.json()['items'][0]['role'],second.json()['items'][0]['role']} == {'origin','destination'}
        # A forged cursor cannot cross the event scope even for its owner.
        bad = conversation.client.get(f'/v1/story/events/{conversation.project}/another-event/places',
            params={'cursor':first.json()['next_cursor']})
        assert bad.status_code >= 400
        with TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: PostgresRest(sql, OWNER).storage())) as free:
            assert free.get(path).status_code == 403


def test_composer_consumes_canonical_places_and_incomplete_attribution_without_reextracting(sql, tmp_path, monkeypatch):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path/'receipts.sqlite3'))
    story = 'I repaired a bicycle in Chengde.'
    def extract(packet):
        return {**empty(packet),'events':[episode(packet,story)], 'event_places':[
            {'event_index':0,'role':'setting','place':{'place':'Chengde','hierarchy':['Earth','China','Chengde'],
                'granularity':'city'},'source_ref':reference(packet,story)}]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        saved = conversation.say(story + ' Something else remains unclear.')
        conversation.drain()
        for _ in range(4):
            conversation.say('Thank you.')
            conversation.drain()
        conversation.deliver_receipts()
        lane = sql("select id from public.user_memoir_lane where skill='composer';").stdout.strip()
        assert lane
        outcome = asyncio.run(conversation.worker.execute_lane(lane))
        assert outcome.get('retrieval_complete'), (outcome,conversation.last_db_error)
        drafts = [packet for phase,packet in conversation.admissions if phase == 'draft']
        assert drafts
        context = drafts[0]['request']['context']['attribution_coverage']
        assert context['scope'] == 'bounded_sources' and not context['lifetime_complete']
        source = next(item for item in context['sources'] if item['source_id'] == saved['accepted_source_id'])
        assert source['complete'] and not source['resolved'] and source['unresolved_passages']
        event = context['events'][0]
        assert event['temporal']['year_start'] is None
        assert event['places'][0]['role'] == 'setting' and event['places'][0]['place']['place'] == 'Chengde'
        assert len([phase for phase,_ in conversation.admissions if phase == 'extract']) == 1
        assert conversation.attribution(saved['accepted_source_id'])['items'][0]['event']['id'] == event['id']


@pytest.mark.parametrize('action', ['edit','withdraw'])
def test_source_change_during_extraction_cannot_publish_stale_attribution(sql,tmp_path,monkeypatch,action):
    original, replacement = 'I repaired a bicycle in Chengde.', 'I worked in Hobart.'
    changed = False
    def extract(packet):
        nonlocal changed
        source = packet['sources'][0]
        if not changed:
            changed = True
            rpc(sql,'change_user_narrator_source',f"{literal(conversation.project)},'{source['id']}',1,'{action}'," +
                (literal(replacement) if action == 'edit' else 'null'))
        return {**empty(packet),'events':[episode(packet,source['text'])], 'event_places':[
            {'event_index':0,'role':'setting','place':{'place':'Chengde','hierarchy':['Earth','China','Chengde'],
                'granularity':'city'},'source_ref':reference(packet,original)}]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        saved = conversation.say(original)
        conversation.drain()
        assert changed
        response = conversation.client.get(f'/v1/story/sources/{conversation.project}/{saved["accepted_source_id"]}/attribution')
        assert 'Chengde' not in response.text
        if action == 'withdraw':
            assert response.status_code >= 400
        else:
            assert response.status_code == 200
            assert response.json()['source_version'] == 2 and not response.json()['complete']
            conversation.extract = lambda packet: {**empty(packet),'events':[episode(packet,replacement)]}
            conversation.retry()
            conversation.drain()
            current = conversation.attribution(saved['accepted_source_id'])
            assert current['resolved'] and current['items'][0]['event']['places'] == []


def test_author_removed_links_and_corrected_time_remain_authoritative(sql,tmp_path,monkeypatch):
    text = 'I repaired a bicycle in Chengde in 1966. Something remains unclear.'
    def extract(packet):
        return {**empty(packet),'events':[episode(packet,text)],'event_places':[
            {'event_index':0,'role':'setting','place':{'place':'Chengde','hierarchy':['Earth','China','Chengde'],
                'granularity':'city'},'source_ref':reference(packet,'Chengde')}]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract,family=True)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        event = conversation.attribution(saved['accepted_source_id'])['items'][0]['event']
        # The existing author correction interface owns placement, not the model.
        patch = {'temporal':{'expression':'1966','precision':'year','year_start':1966,'year_end':1966,
            'basis':[{'source_id':saved['accepted_source_id'],'version':1,'quote':'1966'}]}}
        rpc(sql,'correct_user_memory_event',f"{literal(conversation.project)},'{event['id']}',{event['revision']},{literal(patch)}::jsonb,'The year was 1966.'")
        current = conversation.attribution(saved['accepted_source_id'])['items'][0]['event']
        assert current['temporal']['year_start'] == 1966
        assert current['places'][0]['place']['place'] == 'Chengde'
        rpc(sql,'unlink_user_memory_event_source',f"{literal(conversation.project)},'{event['id']}',{current['revision']},'{saved['accepted_source_id']}','This belongs to another event.'")
        removed = conversation.attribution(saved['accepted_source_id'])
        assert not removed['resolved'] and all(item['event'] is None for item in removed['items'])
        places = conversation.client.get(f'/v1/story/events/{conversation.project}/{event["id"]}/places')
        assert 'Chengde' not in places.text
        conversation.retry()
        conversation.drain()
        assert not conversation.attribution(saved['accepted_source_id'])['resolved']


@pytest.mark.parametrize('invalid', ['version','repeated_quote','private_place','wrong_event'])
def test_invalid_auxiliary_evidence_is_atomic_and_retryable(sql,tmp_path,monkeypatch,invalid):
    first, second = 'I repaired a bicycle in Chengde.', 'My father worked in Hobart.'
    text = first + second + ' Chengde.'
    def extract(packet):
        ref = reference(packet,'Chengde' if invalid == 'repeated_quote' else first)
        if invalid == 'version':
            ref['version'] = 2
        place = {'place':'Chengde','hierarchy':['Earth','China','Chengde'],'granularity':'city'}
        if invalid == 'private_place':
            place['hierarchy'][-1] = 'Chengde School'
        return {**empty(packet),'events':[episode(packet,first),episode(packet,second,title="Father's work")],
            'event_places':[{'event_index':1 if invalid == 'wrong_event' else 0,'role':'setting','place':place,'source_ref':ref}]}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract)
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        rejected = conversation.attribution(saved['accepted_source_id'])
        assert not rejected['complete'] and not rejected['resolved']
        assert all(item['event'] is None for item in rejected['items'])
        assert len([phase for phase,_ in conversation.admissions if phase == 'extract']) == 3
        def valid(packet):
            result = {**empty(packet),'events':[episode(packet,first)],'event_places':[
                {'event_index':0,'role':'setting','place':{'place':'Chengde','hierarchy':['Earth','China','Chengde'],
                    'granularity':'city'},'source_ref':reference(packet,'Chengde')}]}
            start = text.index('Chengde')
            result['event_places'][0]['source_ref'].update(char_start=start,char_end=start+len('Chengde'))
            return result
        conversation.extract = valid
        conversation.retry()
        conversation.drain()
        accepted = conversation.attribution(saved['accepted_source_id'])
        assert accepted['complete'] and accepted['items'][0]['event']['places'][0]['place']['place'] == 'Chengde'


def test_source_cursor_expires_after_replacement_and_mixed_introduction_is_not_suppressed(sql,tmp_path,monkeypatch):
    story = 'I repaired a bicycle in Chengde.'
    text = 'My name is Joan. ' + story + ' Something else remains unclear.'
    conversation = Conversation(sql,tmp_path,monkeypatch,
        lambda packet: {**empty(packet),'events':[episode(packet,story)]},work='reply_only',name='Joan')
    with conversation.client:
        saved = conversation.say(text)
        conversation.drain()
        first = conversation.attribution(saved['accepted_source_id'],limit=1)
        assert first['next_cursor']
        assert any(phase == 'extract' for phase,_ in conversation.admissions)
        rpc(sql,'change_user_narrator_source',f"{literal(conversation.project)},'{saved['accepted_source_id']}',1,'edit','Corrected original testimony.'")
        stale = conversation.client.get(f'/v1/story/sources/{conversation.project}/{saved["accepted_source_id"]}/attribution',
            params={'cursor':first['next_cursor']})
        assert stale.status_code >= 400 and 'Chengde' not in stale.text
        fresh = conversation.attribution(saved['accepted_source_id'])
        assert fresh['source_version'] == 2 and not fresh['complete']


@pytest.mark.parametrize('strategy',['comfort','explore','shape'])
def test_attribution_is_independent_of_automatic_interview_strategy(sql,tmp_path,monkeypatch,strategy):
    story = 'At age twelve I repaired a bicycle in Chengde.'
    correction = 'Actually, I repaired that bicycle at age thirteen.'
    def extract(packet):
        text = packet['sources'][0]['text']
        quote = story if story in text else correction
        existing = packet['events'][0] if packet['events'] else None
        event = episode(packet,quote,existing=existing)
        expression = 'age twelve' if story in text else 'age thirteen'
        event['temporal'] = {'expression':expression,'precision':'age','basis':[reference(packet,expression)]}
        places = [] if existing else [{'event_index':0,'role':'setting','place':{'place':'Chengde',
            'hierarchy':['Earth','China','Chengde'],'granularity':'city'},'source_ref':reference(packet,story)}]
        return {**empty(packet),'events':[event],'event_places':places}
    conversation = Conversation(sql,tmp_path,monkeypatch,extract,work='reply_only',strategy=strategy)
    with conversation.client:
        first = conversation.say('Please stop. ' + story)
        conversation.drain()
        initial = conversation.attribution(first['accepted_source_id'])
        event = next(item['event'] for item in initial['items'] if item['event'])
        assert event['temporal']['expression'] == 'age twelve' and event['places'][0]['place']['place'] == 'Chengde'
        # A mode-only legacy preference is inert after #79 and cannot reset B.
        before = len(conversation.admissions)
        sql("update public.user_profile set profile=profile||'{\"preferred_phase\":\"comfort\"}'::jsonb;")
        conversation.drain()
        assert len(conversation.admissions) == before
        thanks = conversation.say('Thank you.')
        conversation.drain()
        assert conversation.attribution(thanks['accepted_source_id'])['resolved']
        corrected = conversation.say(correction)
        conversation.drain()
        current = conversation.attribution(corrected['accepted_source_id'])['items'][0]['event']
        assert current['id'] == event['id'] and current['temporal']['expression'] == 'age thirteen'
        assert current['places'][0]['place']['place'] == 'Chengde'
        assert len([phase for phase,_ in conversation.admissions if phase == 'extract']) == 2
