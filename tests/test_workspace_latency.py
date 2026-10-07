import asyncio
import json

import pytest

from apps.api.codex_runtime import CodexRuntime


@pytest.mark.parametrize('separate_runtime', [False, True])
def test_next_reply_waits_for_an_in_progress_workspace_write(monkeypatch, separate_runtime):
    import threading
    from apps.api.turn_stream import turn_events

    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)
    writing, release_write, contended = (threading.Event() for _ in range(3))

    class Storage:
        user_id = 'workspace-write-contention'
        holder = None
        commits = 0
        data = {'preferred_language': 'zh-CN'}

        def acquire_agent_turn_lease(self, token, seconds):
            if self.holder is not None:
                contended.set()
                return False
            self.holder = token
            return True

        def release_agent_turn_lease(self, token):
            assert self.holder == token
            self.holder = None
            return True

        def renew_agent_turn_lease(self, token, *args): return self.holder == token
        def agent_session(self): return None
        def memories(self): return []
        def profile(self): return dict(self.data)

        def save_profile(self, profile):
            if self.commits == 1 and profile.get('name') == 'Synthetic':
                writing.set()
                assert release_write.wait(3), 'Workspace write was not released'
            self.data = dict(profile)

        def commit_agent_turn(self, *args, **kwargs):
            self.commits += 1
            return {'id': f'memory-{self.commits}'}

    async def run():
        storage = Storage()
        runtime = CodexRuntime(worker_url='http://test-worker')
        next_runtime = CodexRuntime(worker_url='http://test-worker') if separate_runtime else runtime

        async def worker(**kwargs):
            reply = '你记得一起捉昆虫。'
            if kwargs.get('on_delta'):
                await kwargs['on_delta'](reply)
            return {'thread_id': 'collector', 'reply': reply +
                    '[[MEMORY_SPARK_PROFILE]]{"name":"Synthetic"}[[/MEMORY_SPARK_PROFILE]]',
                    'artifacts': []}

        monkeypatch.setattr(runtime, '_worker_turn', worker)
        monkeypatch.setattr(next_runtime, '_worker_turn', worker)

        async def collect(text, runtime):
            async def turn(emit):
                return await runtime.turn(storage, text, language='zh-CN',
                                          on_delta=emit, on_event=emit.event)
            return [json.loads(line) async for line in turn_events(turn)]

        first = asyncio.create_task(collect('我小时候在花园里玩。', runtime))
        second = None
        try:
            assert await asyncio.to_thread(writing.wait, 2)
            second = asyncio.create_task(collect('我和朋友一起捉昆虫。', next_runtime))
            assert await asyncio.to_thread(contended.wait, 2)
            release_write.set()
            first_events, second_events = await asyncio.gather(first, second)
            assert any(e['type'] == 'conversation_saved' for e in first_events)
            assert not [e for e in second_events if e['type'] == 'error'], second_events
            assert any(e['type'] == 'conversation_saved' for e in second_events)
            assert storage.commits == 2
        finally:
            release_write.set()
            await asyncio.gather(first, *([second] if second else []), return_exceptions=True)

    asyncio.run(run())


@pytest.mark.parametrize('stream', [False, True])
def test_workspace_transport_allows_the_worker_extraction_budget(stream):
    import httpx
    from apps.api.codex_runtime import WORKSPACE_TIMEOUT

    def handler(request):
        assert request.extensions['timeout']['read'] > WORKSPACE_TIMEOUT
        result = {'thread_id': 'workspace', 'reply': '', 'artifacts': []}
        if stream:
            events = [{'type': 'provider_complete', 'data': result}, {'type': 'result', 'data': result}]
            return httpx.Response(200, text='\n'.join(map(json.dumps, events)),
                                  headers={'Content-Type': 'application/x-ndjson'})
        return httpx.Response(200, json=result)

    async def run():
        runtime = CodexRuntime(worker_url='http://worker', worker_secret='test',
                               worker_transport=httpx.MockTransport(handler))
        async def event(value): pass
        result = await runtime._worker_turn(user_id='test', prior=None, memories=[], profile={},
            place_journey=None, family_enabled=False, family_context=None, project_id=None,
            text='memory', language='zh-CN', agent_role='workspace',
            **({'on_event': event} if stream else {}))
        if result.get('_artifact_task'):
            await result['_artifact_task']
        assert result['thread_id'] == 'workspace'

    asyncio.run(run())


@pytest.mark.parametrize('legacy_markers', [False, True])
@pytest.mark.parametrize('earth', ['Earth', '地球'])
def test_one_conversation_previews_and_persists_every_grounded_place(monkeypatch, legacy_markers, earth):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)
    text = ('后来我5，6岁的时候就搬到市区了，原来学校的家属院在大石庙镇，后来搬到了市区双桥区。'
            '但是每到放假我都要做我爸的通勤车回大石庙找我的小伙伴们玩好几天，'
            '有时候去找司正焉（他那个时候叫做司文转）有时候去找杨洪涛。'
            '再后来慢慢长大了学习的任务忙了，回去的次数就慢慢变少了')
    def marker(place):
        return ('[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps({
            'place': place, 'hierarchy': [earth, '中国', '河北', '承德', place],
            'granularity': 'suburb',
        }, ensure_ascii=False) + '[[/MEMORY_SPARK_PLACE_JOURNEY]]')
    markers = marker('Paris') + marker('大石庙镇') + marker('双桥区') + marker('大石庙镇')

    class Storage:
        user_id = f'multiple-places-{legacy_markers}'
        commits = 0
        def __init__(self): self.saved = []
        def acquire_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def agent_session(self): return None
        def memories(self): return []
        def profile(self): return getattr(self, 'saved_profile', {'preferred_language': 'zh-CN'})
        def save_profile(self, profile): self.saved_profile = dict(profile)
        def place_journey(self): return self.saved[-1] if self.saved else None
        def commit_agent_turn(self, *args, **kwargs):
            self.commits += 1
            assert 'MEMORY_SPARK_PLACE_JOURNEY' not in args[2]
            return {'id': 'memory', 'source_sequence': 1}
        def save_place_journey(self, token, journey, **kwargs):
            assert self.commits == 1
            record = {**journey, 'latitude': None, 'longitude': None,
                      'status': 'active', 'revision': len(self.saved) + 1,
                      'source_sequence': kwargs.get('source_sequence', 0),
                      'updated_at': '2026-10-01T00:00:00Z'}
            self.saved.append(record)
            return record

    async def run():
        storage, runtime, events = Storage(), CodexRuntime(), []
        runtime.worker_url = 'http://test-worker'
        previews_ready = asyncio.Event()
        async def worker(**kwargs):
            if kwargs.get('agent_role') == 'workspace':
                # Several complete markers in one delta, plus split delimiters.
                for fragment in (markers[:17], markers[17:-12], markers[-12:]):
                    await kwargs['on_delta'](fragment)
                previews_ready.set()
                return {'thread_id': 'workspace', 'reply': markers, 'artifacts': []}
            await kwargs['on_delta']('你还记得一起玩的时光。')
            await asyncio.wait_for(previews_ready.wait(), 1)
            assert storage.commits == 0
            assert [event['data']['place_journey']['place'] for event in events
                    if event['type'] == 'place_preview'] == ['大石庙镇', '双桥区']
            return {'thread_id': 'collector', 'artifacts': [], '_workspace_capable': True,
                    'reply': '你还记得一起玩的时光。' + (markers if legacy_markers else '')}
        async def emit(event): events.append(event)
        async def delta(fragment): pass
        monkeypatch.setattr(runtime, '_worker_turn', worker)
        result = await runtime.turn(storage, text, on_delta=delta, on_event=emit)
        assert not [event for event in events if event['type'] == 'workspace_error'], events
        assert result['reply'] == '你还记得一起玩的时光。'
        assert [place['place'] for place in result['place_journeys']] == ['大石庙镇', '双桥区']
        assert [place['place'] for place in storage.saved] == ['大石庙镇', '双桥区']
        assert result['place_journey'] == {**storage.saved[-1], 'period': '', 'life_stage': None}
        updates = [event['data'] for event in events if event['type'] == 'workspace_update'
                   and event['data'].get('place_journeys')]
        assert updates and all(update['place_journeys'] == [
            {**p, 'period': '', 'life_stage': None} for p in storage.saved] for update in updates)
    asyncio.run(run())


@pytest.mark.parametrize('legacy_markers', [False, True])
@pytest.mark.parametrize('parent_first', [False, True])
@pytest.mark.parametrize('language,text,residence,region,birthplace,independent_region', [
    ('zh-CN', '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院',
     '悉尼', '河北省', '承德市', False),
    ('zh-CN', '现在生活在悉尼，出生在河北省承德市，后来还去过河北省其他地方。',
     '悉尼', '河北省', '承德市', True),
    ('en-AU', 'I live in Sydney now, but I was born in Chengde, Hebei.',
     'Sydney', 'Hebei', 'Chengde', False),
    ('en-AU', 'I live in Sydney now, but I was born in Chengde, Hebei. Later I travelled across Hebei.',
     'Sydney', 'Hebei', 'Chengde', True),
], ids=['qualified-zh', 'independent-zh', 'qualified-en', 'independent-en'])
def test_backend_removes_only_qualifying_province_records(
    monkeypatch, legacy_markers, parent_first, language, text, residence, region, birthplace,
    independent_region,
):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)
    province = {'place': region, 'hierarchy': ['Earth', 'China', region], 'granularity': 'region'}
    city = {'place': birthplace, 'hierarchy': [*province['hierarchy'], birthplace], 'granularity': 'city'}
    places = [{'place': residence, 'hierarchy': ['Earth', 'Australia', residence], 'granularity': 'city'},
              *([province, city] if parent_first else [city, province])]
    markers = ''.join('[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps(place, ensure_ascii=False)
                      + '[[/MEMORY_SPARK_PLACE_JOURNEY]]' for place in places)
    expected = [place['place'] for place in places
                if independent_region or place['granularity'] != 'region']

    class Storage:
        user_id = 'province-deduplication-test'
        def __init__(self):
            self.saved = []
            self.data = {'preferred_language': language}
        def acquire_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def agent_session(self): return None
        def memories(self): return []
        def profile(self): return self.data
        def save_profile(self, profile): self.data = profile
        def place_journey(self): return self.saved[-1] if self.saved else None
        def commit_agent_turn(self, *args, **kwargs): return {'id': 'memory'}
        def save_place_journey(self, token, journey, **kwargs):
            record = {**journey, 'status': 'active', 'revision': len(self.saved) + 1,
                      'source_sequence': kwargs.get('source_sequence', 0),
                      'updated_at': '2026-10-07T00:00:00Z'}
            self.saved.append(record)
            return record

    async def run():
        storage, events = Storage(), []
        runtime = CodexRuntime(worker_url='http://test-worker')
        async def worker(**kwargs):
            if kwargs.get('agent_role') == 'workspace':
                for fragment in (markers[:17], markers[17:-12], markers[-12:]):
                    await kwargs['on_delta'](fragment)
                return {'thread_id': 'workspace', 'reply': markers, 'artifacts': []}
            await kwargs['on_delta']('Tell me more.')
            return {'thread_id': 'collector', 'reply': 'Tell me more.'
                    + (markers if legacy_markers else ''), 'artifacts': [], '_workspace_capable': True}
        async def emit(event): events.append(event)
        async def delta(fragment): pass
        monkeypatch.setattr(runtime, '_worker_turn', worker)
        result = await runtime.turn(storage, text, language=language, on_delta=delta, on_event=emit)
        assert not [event for event in events if event['type'] == 'workspace_error'], events
        assert [place['place'] for place in result['place_journeys']] == expected
        assert [place['place'] for place in storage.saved] == expected
        assert result['place_journey']['place'] == expected[-1]
        saved_city = next(place for place in storage.saved if place['place'] == birthplace)
        assert saved_city['hierarchy'] == city['hierarchy']
        previews = [event['data']['place_journey']['place'] for event in events
                    if event['type'] == 'place_preview']
        assert set(previews) == set(expected)
        updates = [event['data'] for event in events
                   if event['type'] == 'workspace_update' and event['data'].get('place_journeys')]
        assert updates and all([place['place'] for place in update['place_journeys']] == expected
                               for update in updates)

    asyncio.run(run())


@pytest.mark.parametrize('place,expected_preview,cancel', [('Sydney', True, False), ('Paris', False, False), ('Sydney', True, True)])
def test_place_preview_arrives_while_collector_and_extraction_are_still_streaming(monkeypatch, place, expected_preview, cancel):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)
    marker = '[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps({
        'schema_version': 1, 'place': place, 'hierarchy': ['Earth', place],
        'granularity': 'city', 'latitude': -33.86, 'longitude': 151.21,
    }) + '[[/MEMORY_SPARK_PLACE_JOURNEY]]'

    class Storage:
        user_id = 'parallel-place-test'
        commits = 0
        saved_place = None
        def acquire_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def agent_session(self): return None
        def memories(self): return []
        def profile(self): return getattr(self, 'saved_profile', {'preferred_language': 'en-AU'})
        def save_profile(self, profile): self.saved_profile = dict(profile)
        def place_journey(self): return self.saved_place
        def commit_agent_turn(self, *args, **kwargs):
            self.commits += 1
            return {'id': 'memory'}
        def save_place_journey(self, token, journey, **kwargs):
            assert self.commits == 1, 'preview must not persist an unsaved turn'
            self.saved_place = {**journey, 'status': 'active', 'revision': 1,
                                'updated_at': '2026-10-01T00:00:00Z'}
            return self.saved_place

    async def run():
        storage = Storage()
        runtime = CodexRuntime()
        runtime.worker_url = 'http://test-worker'
        collector_started, marker_sent, finish = asyncio.Event(), asyncio.Event(), asyncio.Event()
        events, calls = [], []
        async def worker(**kwargs):
            role = kwargs.get('agent_role', 'collector')
            calls.append(role)
            if role == 'workspace':
                await collector_started.wait()
                for fragment in (marker[:20], marker[20:]):
                    await kwargs['on_delta'](fragment)
                marker_sent.set()
                try:
                    await finish.wait()
                finally:
                    events.append({'type': 'extraction_settled'})
                return {'thread_id': 'workspace', 'reply': marker, 'artifacts': []}
            collector_started.set()
            await kwargs['on_delta']('Tell me about Sydney.')
            await finish.wait()
            return {'thread_id': 'collector', 'reply': 'Tell me about Sydney.', 'artifacts': [],
                    '_workspace_capable': True}
        async def emit(event): events.append(event)
        async def delta(text): pass
        monkeypatch.setattr(runtime, '_worker_turn', worker)
        task = asyncio.create_task(runtime.turn(storage, 'I grew up in Sydney.', on_delta=delta, on_event=emit))
        try:
            await asyncio.wait_for(marker_sent.wait(), 1)
            previews = [event for event in events if event['type'] == 'place_preview']
            assert bool(previews) is expected_preview
            assert storage.commits == 0
            assert not task.done()
            if cancel:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                assert any(event['type'] == 'extraction_settled' for event in events)
                assert storage.commits == 0
                return
            finish.set()
            result = await task
            assert calls.count('workspace') == 1, 'parallel extraction must be reused after commit'
            assert bool(result['place_journey']) is expected_preview
        finally:
            finish.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_place_update_precedes_optional_artifact_transfer(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)

    class Storage:
        user_id = 'latency-test'

        def acquire_agent_turn_lease(self, *args):
            return True

        def release_agent_turn_lease(self, *args):
            return True

        def place_journey(self):
            return None

        def save_place_journey(self, token, journey, **kwargs):
            return {**journey, 'duration_ms': 5200, 'status': 'active', 'revision': 1,
                'source_sequence': 1, 'updated_at': '2026-10-01T00:00:00Z'}

    async def run():
        runtime = CodexRuntime()
        artifacts = asyncio.get_running_loop().create_future()
        place_ready = asyncio.Event()

        async def emit(event):
            if event.get('data', {}).get('place_journey_change', {}).get('changed'):
                place_ready.set()

        task = asyncio.create_task(runtime._persist_workspace(
            storage=Storage(), user_id='latency-test', project_id=None,
            family_enabled=False, existing_family_context=None,
            current_place_journey=None,
            parsed_place_journey={'schema_version': 1, 'place': 'Sydney',
                'hierarchy': ['Earth', 'Australia', 'Sydney'], 'granularity': 'city'},
            parsed_family_context=None, family_skills=[], profile={}, profile_updates=None,
            task_requests=[], memories=[], text='Sydney', language='en-AU', turn_sequence=1,
            deferred_artifacts=[], deferred_artifacts_task=artifacts, deferred_home=None,
            memory={}, legacy_markers=True, turn_id='test', on_event=emit, trajectory=None,
        ))
        try:
            await asyncio.wait_for(place_ready.wait(), 0.2)
            assert not artifacts.done()
        finally:
            artifacts.set_result([])
            await task

    asyncio.run(run())


def test_birth_period_is_attached_only_to_the_birthplace_in_a_multi_place_turn(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)
    text = '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院'
    journeys = [{'place': place, 'hierarchy': ['Earth', country, place], 'granularity': 'city'}
                for place, country in [('悉尼', '澳大利亚'), ('承德市', '中国')]]

    class Storage:
        user_id = 'place-period-test'
        def acquire_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def place_journey(self): return None
        def profile(self): return {}
        def save_profile(self, profile): pass
        def save_place_journey(self, token, journey, **kwargs):
            return {**journey, 'duration_ms': 5200, 'status': 'active', 'revision': 1,
                    'source_sequence': 1, 'updated_at': '2026-10-03T00:00:00Z'}

    async def run():
        events = []
        async def emit(event): events.append(event)
        result = await CodexRuntime()._persist_workspace(
            storage=Storage(), user_id='place-period-test', project_id=None,
            family_enabled=False, existing_family_context=None, current_place_journey=None,
            parsed_place_journey=journeys[-1], parsed_place_journeys=journeys,
            parsed_family_context=None, family_skills=[], profile={},
            profile_updates={'story_focus': {'where': '河北省承德市附属医院', 'when': '1983年4月'}},
            task_requests=[], memories=[], text=text, language='zh-CN', turn_sequence=1,
            deferred_artifacts=[], deferred_artifacts_task=None, deferred_home=None,
            memory={}, legacy_markers=True, turn_id='test', on_event=emit, trajectory=None)
        assert [(place['place'], place['period']) for place in result['place_journeys']] == [
            ('悉尼', ''), ('承德市', '1983年4月')]
        updates = [event['data']['place_journeys'] for event in events
                   if event['type'] == 'workspace_update' and event['data'].get('place_journeys')]
        assert updates and all(places[0]['period'] == '' and places[1]['period'] == '1983年4月'
                               for places in updates)

    asyncio.run(run())


@pytest.mark.parametrize('legacy_markers', [False, True])
@pytest.mark.parametrize('focus_location', ['matching', 'missing', 'ambiguous'])
@pytest.mark.parametrize('language,text,residence,birthplace,where', [
    ('zh-CN', '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院',
     '悉尼', '承德市', '河北省承德市附属医院'),
    ('en-AU', 'I live in Sydney now, but I was born in Chengde, Hebei in April 1983.',
     'Sydney', 'Chengde', 'Chengde'),
], ids=['zh-CN', 'en-AU'])
def test_backend_assigns_birth_stage_only_to_birthplace(
    monkeypatch, legacy_markers, focus_location, language, text, residence, birthplace, where,
):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)
    region = '河北省' if language == 'zh-CN' else 'Hebei'
    places = [
        {'place': residence, 'hierarchy': ['Earth', 'Australia', residence], 'granularity': 'city'},
        {'place': birthplace, 'hierarchy': ['Earth', 'China', region, birthplace], 'granularity': 'city'},
        {'place': region, 'hierarchy': ['Earth', 'China', region], 'granularity': 'region'},
    ]
    markers = ''.join('[[MEMORY_SPARK_PLACE_JOURNEY]]' + json.dumps(place, ensure_ascii=False)
                      + '[[/MEMORY_SPARK_PLACE_JOURNEY]]' for place in places)
    focus = {'life_stage': 'baby'}
    if focus_location == 'matching':
        focus['where'] = where
    elif focus_location == 'ambiguous':
        focus['where'] = f'{residence}, {birthplace}'
    markers += '[[MEMORY_SPARK_PROFILE]]' + json.dumps({
        'story_focus': focus,
    }, ensure_ascii=False) + '[[/MEMORY_SPARK_PROFILE]]'

    class Storage:
        user_id = 'place-stage-test'
        def __init__(self):
            self.saved = []
            self.data = {'preferred_language': language}
        def acquire_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def agent_session(self): return None
        def memories(self): return []
        def profile(self): return self.data
        def save_profile(self, profile): self.data = profile
        def place_journey(self): return self.saved[-1] if self.saved else None
        def commit_agent_turn(self, *args, **kwargs): return {'id': 'memory'}
        def save_place_journey(self, token, journey, **kwargs):
            record = {**journey, 'status': 'active', 'revision': len(self.saved) + 1,
                      'source_sequence': kwargs.get('source_sequence', 0),
                      'updated_at': '2026-10-07T00:00:00Z'}
            self.saved.append(record)
            return record

    async def run():
        storage, events = Storage(), []
        runtime = CodexRuntime(worker_url='http://test-worker')
        async def worker(**kwargs):
            if kwargs.get('agent_role') == 'workspace':
                return {'thread_id': 'workspace', 'reply': markers, 'artifacts': []}
            return {'thread_id': 'collector', 'reply': 'Tell me more.'
                    + (markers if legacy_markers else ''), 'artifacts': [], '_workspace_capable': True}
        async def emit(event): events.append(event)
        monkeypatch.setattr(runtime, '_worker_turn', worker)
        result = await runtime.turn(storage, text, language=language, on_event=emit)
        assert not [event for event in events if event['type'] == 'workspace_error'], events
        birth_stage = 'baby' if focus_location == 'matching' else None
        expected = [(residence, None), (birthplace, birth_stage)]
        assert [(place['place'], place['life_stage']) for place in result['place_journeys']] == expected
        assert result['place_journey']['life_stage'] == birth_stage
        updates = [event['data'] for event in events
                   if event['type'] == 'workspace_update' and event['data'].get('place_journeys')]
        assert updates
        assert all([(place['place'], place['life_stage']) for place in update['place_journeys']]
                   == expected and update['place_journey']['life_stage'] == birth_stage for update in updates)

    asyncio.run(run())


def test_present_photo_request_clears_a_previous_calendar_period(monkeypatch):
    monkeypatch.delenv('MEMORY_SPARK_TASK_DB', raising=False)
    text = '请给我找一些现在Chatswood的参考照片，没有指定过去的年份。'
    journeys = [{'place': 'Chatswood', 'hierarchy': ['Earth', 'Australia', 'Sydney', 'Chatswood'], 'granularity': 'suburb'}]

    class Storage:
        user_id = 'place-period-test'
        def acquire_agent_turn_lease(self, *args): return True
        def release_agent_turn_lease(self, *args): return True
        def renew_agent_turn_lease(self, *args): return True
        def place_journey(self): return None
        def profile(self): return {}
        def save_profile(self, profile): pass
        def save_place_journey(self, token, journey, **kwargs):
            return {**journey, 'duration_ms': 5200, 'status': 'active', 'revision': 1,
                    'source_sequence': 1, 'updated_at': '2026-10-03T00:00:00Z'}

    async def run():
        events = []
        async def emit(event): events.append(event)
        result = await CodexRuntime()._persist_workspace(
            storage=Storage(), user_id='place-period-test', project_id=None,
            family_enabled=False, existing_family_context=None, current_place_journey=None,
            parsed_place_journey=journeys[-1], parsed_place_journeys=journeys,
            parsed_family_context=None, family_skills=[], profile={},
            profile_updates={'story_focus': {'where': 'Chatswood', 'when': '现在'}},
            task_requests=[], memories=[], text=text, language='zh-CN', turn_sequence=1,
            deferred_artifacts=[], deferred_artifacts_task=None, deferred_home=None,
            memory={}, legacy_markers=True, turn_id='test', on_event=emit, trajectory=None)
        assert result['place_journeys'][0].get('period') == ''

    asyncio.run(run())
