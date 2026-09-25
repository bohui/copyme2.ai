import asyncio
import base64
import json
import sys
import pytest

from apps.api.codex_agent import CodexConnection
from apps.api.codex_runtime import CodexRuntime, build_loop_trace


def test_loop_trace_exposes_actions_without_private_model_reasoning():
    trace = build_loop_trace(memory_count=2, resumed=True, saved_paths=3)

    assert trace[0]["label"] == "Analyze"
    assert any(step["label"] == "memory.search" for step in trace)
    assert any(step["label"] == "codex.thread.resume" for step in trace)
    assert any(step["label"] == "memory.save" for step in trace)
    assert trace[-1]["label"] == "Respond"
    assert all("chain-of-thought" not in step["detail"].lower() for step in trace)


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
                "reply": "What detail stands out most?",
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

        async def post(self, url, *, headers, json):
            self.request = {"url": url, "headers": headers, "json": json}
            return Response()

    client = Client()
    monkeypatch.setattr("apps.api.codex_runtime.httpx.AsyncClient", lambda **kwargs: client)
    storage = Storage()

    result = asyncio.run(CodexRuntime(
        worker_url="http://codex-worker:8766",
        worker_secret="worker-secret",
        model="test-model",
    ).turn(storage, "Tell me about that day."))

    assert result["trace_mode"] == "codex-worker"
    assert result["thread_id"] == "thread-new"
    path = result['source_paths'][0]
    assert path.startswith('sessions/turns/') and path.endswith('/thread-new.json')
    assert storage.saved_session == "thread-new"
    assert storage.files[path] == b"session state"
    assert client.request["url"] == "http://codex-worker:8766/internal/codex/turn"
    assert client.request["headers"] == {"X-Codex-Worker-Secret": "worker-secret"}
    assert client.request["json"] == {
        "user_id": storage.user_id,
        "thread_id": "thread-old",
        "memories": ["A private memory"],
        "text": "Tell me about that day.",
        "model": "test-model",
    }
