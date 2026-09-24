import asyncio
import json
import sys

from apps.api.codex_agent import CodexConnection
from apps.api.codex_runtime import build_loop_trace


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
