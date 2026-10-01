import asyncio
from contextlib import asynccontextmanager
import base64
import json
import sys
import pytest
from pathlib import Path

from apps.api.codex_agent import CodexConnection
from apps.api.codex_runtime import (
    CodexRuntime,
    build_conversation_system_prompt,
    build_loop_trace,
    build_system_prompt,
    build_workspace_extraction_prompt,
)


def test_loop_trace_exposes_actions_without_private_model_reasoning():
    trace = build_loop_trace(memory_count=2, resumed=True, saved_paths=3)

    assert trace[0]["label"] == "Analyze"
    assert any(step["label"] == "memory.search" for step in trace)
    assert any(step["label"] == "codex.thread.resume" for step in trace)
    assert any(step["label"] == "memory.save" for step in trace)
    assert trace[-1]["label"] == "Respond"
    assert all("chain-of-thought" not in step["detail"].lower() for step in trace)


def test_system_prompt_requires_simplified_chinese_responses():
    prompt = build_system_prompt("(none)", language="zh-CN")

    assert "简体中文" in prompt
    assert "不要用英语回答" in prompt


def test_visible_collector_prompt_is_separate_from_workspace_markers():
    conversation = build_conversation_system_prompt('(none)', language='en-AU')
    workspace = build_workspace_extraction_prompt('(none)', language='en-AU')

    assert '[[MEMORY_SPARK_PROFILE]]' not in conversation
    assert '[[MEMORY_SPARK_PLACE_JOURNEY]]' not in conversation
    assert '[[MEMORY_SPARK_PROFILE]]' in workspace
    assert 'Workspace extraction contract' in workspace


def test_private_extraction_omits_the_interview_prompt_but_retains_marker_contracts():
    from apps.api.codex_runtime import MEMOIR_SYSTEM_PROMPT
    workspace = build_workspace_extraction_prompt('(none)', family_enabled=True)
    assert MEMOIR_SYSTEM_PROMPT not in workspace
    for marker in ('PROFILE', 'PLACE_JOURNEY', 'FAMILY_TREE', 'AUTHOR_TIMELINE'):
        assert f'[[MEMORY_SPARK_{marker}]]' in workspace


def test_loop_trace_is_localized_for_simplified_chinese():
    trace = build_loop_trace(memory_count=2, resumed=False, saved_paths=1, language="zh-CN")

    assert trace[0]["label"] == "分析"
    assert trace[-1]["label"] == "回复"
    assert all("memory" not in step["detail"].lower() for step in trace)


def test_same_explicit_place_is_marked_for_new_project_activation():
    journey = {
        "schema_version": 1,
        "status": "active",
        "revision": 4,
        "place": "Geelong",
        "hierarchy": ["Earth", "Australia", "Victoria", "Geelong"],
        "granularity": "city",
        "latitude": -38.1499,
        "longitude": 144.3617,
        "duration_ms": 5200,
        "updated_at": "2026-09-26T00:00:00Z",
    }
    candidate = {key: journey[key] for key in (
        "schema_version", "place", "hierarchy", "granularity", "latitude", "longitude", "duration_ms"
    )}

    _persisted, change = asyncio.run(CodexRuntime._persist_place_journey(
        object(), object(), journey, candidate
    ))

    assert change == {"changed": False, "kind": "unchanged", "revision": 4, "mentioned": True}


def test_repeated_place_advances_its_source_sequence():
    from unittest.mock import AsyncMock, Mock

    current = {
        'schema_version': 1, 'status': 'active', 'revision': 4,
        'source_sequence': 1, 'place': 'Sydney',
        'updated_at': '2026-09-28T00:00:00Z',
        'hierarchy': ['Earth', 'Australia', 'Sydney'],
        'granularity': 'city', 'duration_ms': 5200,
    }
    storage = Mock()
    lease = Mock()
    lease.io = AsyncMock(return_value={**current, 'source_sequence': 3, 'revision': 5})
    persisted, change = asyncio.run(CodexRuntime._persist_place_journey(
        storage, lease, current, current, source_sequence=3,
    ))
    assert persisted['source_sequence'] == 3
    assert change['mentioned'] is True


def test_app_server_initialization_and_errors(tmp_path):
    server = tmp_path / 'server.py'
    server.write_text('''import sys,json
for line in sys.stdin:
 m=json.loads(line)
 if 'id' not in m: continue
 if m['method']=='initialize':
  print(json.dumps({'id':m['id'],'result':{'userAgent':'codex-test'}}),flush=True)
 else:
  print(json.dumps({'id':m['id'],'result':{'thread':{'id':'thread-123'}}}),flush=True)
''')

    async def run():
        async with CodexConnection([sys.executable, str(server)], tmp_path) as connection:
            result = await connection.request('thread/start', {'ephemeral': False})
            assert result['thread']['id'] == 'thread-123'
    asyncio.run(run())


def test_app_server_receives_absolute_home_for_relative_runtime_path(tmp_path, monkeypatch):
    server = tmp_path / 'server.py'
    server.write_text('''import json,os,sys
for line in sys.stdin:
 message=json.loads(line)
 if message.get('method') == 'initialize':
  print(json.dumps({'id':message['id'],'result':{'userAgent':'codex-test'}}),flush=True)
 elif message.get('id'):
  print(json.dumps({'id':message['id'],'result':{
   'home':os.environ['HOME'],'codex_home':os.environ['CODEX_HOME']
  }}),flush=True)
''')
    monkeypatch.chdir(tmp_path)
    relative_home = Path('var/codex-users/test-user')
    expected_home = relative_home.resolve()

    async def run():
        async with CodexConnection([sys.executable, str(server)], relative_home) as connection:
            result = await connection.request('debug/home', {})
            assert result == {
                'home': str(expected_home),
                'codex_home': str(expected_home),
            }

    asyncio.run(run())


def test_cancellation_during_spawn_still_reaps_the_child(tmp_path, monkeypatch):
    spawn = asyncio.create_subprocess_exec
    async def run():
        ready, finish = asyncio.Event(), asyncio.Event()
        async def delayed_spawn(*args, **kwargs):
            process = await spawn(*args, **kwargs)
            ready.set()
            await finish.wait()
            return process
        monkeypatch.setattr(asyncio, 'create_subprocess_exec', delayed_spawn)
        connection = CodexConnection(
            [sys.executable, '-c', 'import time; time.sleep(60)'], tmp_path)
        task = asyncio.create_task(connection.__aenter__())
        await ready.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert connection.process.returncode is not None
    asyncio.run(run())


def test_runtime_dispatches_to_private_worker_and_syncs_allowlisted_artifacts(monkeypatch):
    class Storage:
        user_id = "11111111-1111-4111-8111-111111111111"

        def __init__(self):
            self.files = {}
            self.saved_session = None
            self.profile_data = {}
            self.place_data = None
            self.saved_place_journey = None

        def acquire_agent_turn_lease(self, token, lease_seconds):
            return True

        def renew_agent_turn_lease(self, token, lease_seconds):
            return True

        def release_agent_turn_lease(self, token):
            return True

        def agent_session(self):
            return {"codex_thread_id": "thread-old"}

        def memories(self):
            return [{"content": "A private memory"}]

        def profile(self):
            return self.profile_data

        def save_profile(self, profile):
            self.profile_data = profile

        def place_journey(self):
            return self.place_data

        def save_place_journey(self, lease_token, journey):
            self.saved_place_journey = journey
            self.place_data = {
                **journey,
                "status": "active",
                "revision": 1,
                "updated_at": "2026-09-26T00:00:00Z",
            }
            return self.place_data

        @staticmethod
        def agent_path(path):
            return path

        def commit_agent_turn(self, token, thread_id, text, source_paths):
            self.saved_session = thread_id
            return {"content": text, "kind": "agent", "source_paths": source_paths}

        def put_agent_turn_file(self, token, path, content):
            root, tail = path.split('/', 1)
            path = f'{root}/turns/{token}/{tail}'
            self.files[path] = content
            return path

    class Response:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "thread_id": "thread-new",
                "reply": (
                    "What detail stands out most?\n"
                    "[[MEMORY_SPARK_PROFILE]]"
                    '{"name":"Mina","avatar_style":"female","story_focus":{"who":"my grandmother","where":"Geelong",'
                    '"when":"the 1980s","what":"summer afternoons","life_stage":"childhood"}}'
                    "[[/MEMORY_SPARK_PROFILE]]\n"
                    "[[MEMORY_SPARK_PLACE_JOURNEY]]"
                    '{"schema_version":1,"place":"Geelong",'
                    '"hierarchy":["Earth","Australia","Victoria","Geelong"],'
                    '"granularity":"city","latitude":-38.1499,"longitude":144.3617,'
                    '"duration_ms":5200}'
                    "[[/MEMORY_SPARK_PLACE_JOURNEY]]"
                ),
                "artifacts": [{
                    "path": "sessions/thread-new.json",
                    "content": base64.b64encode(b"session state").decode("ascii"),
                }],
            }

    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.request = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        @asynccontextmanager
        async def stream(self, method, url, *, headers, json):
            response = await self.post(url, headers=headers, json=json)
            async def lines():
                import json as json_module
                yield json_module.dumps({'type': 'result', 'data': response.json()})
            response.aiter_lines = lines
            yield response

        async def post(self, url, *, headers, json):
            self.request = {"url": url, "headers": headers, "json": json}
            if json.get('agent_role') == 'memory_context':
                response = Response()
                response.json = lambda: {'thread_id': 'intake', 'reply': '{"preferred_language":"en-AU"}', 'artifacts': []}
                return response
            return Response()

    client = Client()
    monkeypatch.setattr("apps.api.codex_runtime.httpx.AsyncClient", lambda **kwargs: client)
    storage = Storage()

    events = []
    async def record_event(event):
        events.append(event)

    result = asyncio.run(CodexRuntime(
        worker_url="http://codex-worker:8766",
        worker_secret="worker-secret",
        model="test-model",
    ).turn(storage, "I was a child in Geelong. Please use the female timeline illustrations.", on_event=record_event))

    assert events[0]['type'] == 'progress'
    assert any(event.get('data', {}).get('id') == 'save'
               and event['data']['status'] == 'completed'
               and event['data']['detail'] == 'Conversation memory saved' for event in events)
    saved_index = next(i for i, event in enumerate(events) if event['type'] == 'conversation_saved')
    place_index = next(i for i, event in enumerate(events) if event.get('data', {}).get('skill') == 'memoir-place-journey')
    assert place_index > saved_index
    assert any(step.get('skill') == 'memoir-place-journey' for step in result['trace'])
    assert not any(step.get('skill') == 'memoir-family-tree' for step in result['trace'])
    assert events[saved_index]['data']['trace']
    assert result["trace_mode"] == "codex-worker"
    assert result["thread_id"] == "thread-new"
    path = result['source_paths'][0]
    assert path.startswith('sessions/turns/') and path.endswith('/thread-new.json')
    assert storage.saved_session == "thread-new"
    assert storage.profile_data == {
        "preferred_language": "en-AU",
        "name": "Mina",
        "avatar_style": "female",
        "story_focus": {
            "who": "my grandmother",
            "where": "Geelong",
            "when": "the 1980s",
            "what": "summer afternoons",
            "life_stage": "childhood",
        },
    }
    assert result["profile_updates"] == storage.profile_data
    assert storage.saved_place_journey == {
        "schema_version": 1,
        "place": "Geelong",
        "hierarchy": ["Earth", "Australia", "Victoria", "Geelong"],
        "granularity": "city",
        "latitude": -38.1499,
        "longitude": 144.3617,
        "duration_ms": 5200,
    }
    assert result["place_journey"] == {
        **storage.saved_place_journey,
        "status": "active",
        "revision": 1,
        "updated_at": "2026-09-26T00:00:00Z",
    }
    assert result["place_journey_change"] == {
        "changed": True,
        "kind": "created",
        "revision": 1,
    }
    assert "MEMORY_SPARK_PLACE_JOURNEY" not in result["reply"]
    assert storage.files[path] == b"session state"
    assert client.request["url"] == "http://codex-worker:8766/internal/codex/turn"
    assert client.request["headers"] == {"X-Codex-Worker-Secret": "worker-secret", "Accept": "application/x-ndjson"}
    assert client.request["json"] == {
        "user_id": storage.user_id,
        "thread_id": "thread-old",
        "memories": ["A private memory"],
        "profile": {"preferred_language": "en-AU"},
        "place_journey": {},
        "family_context": {},
        "family_enabled": False,
        "project_id": None,
        "text": "I was a child in Geelong. Please use the female timeline illustrations.",
        "model": "test-model",
        "language": "en-AU",
    }
