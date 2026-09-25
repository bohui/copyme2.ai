"""Offline Linux integration check: run inside the worker's real capability set.

Uses a deterministic stdio app-server double, not a model or Supabase. All
fixture data lives in a fresh directory under the selected worker volume.
"""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
from uuid import UUID

from apps.api.codex_worker_service import CodexWorker, WorkerTurnInput


SERVER = r'''
import json, os, sys
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
assert os.getuid() >= 20000
assert (home / 'config.toml').read_text()
for line in sys.stdin:
    request = json.loads(line)
    if 'id' not in request:
        continue
    method = request['method']
    if method == 'initialize':
        result = {'userAgent': 'isolation-test'}
    elif method == 'thread/resume':
        assert (home / 'sessions' / 'thread-old.jsonl').read_text() == 'legacy rollout'
        result = {'thread': {'id': request['params']['threadId']}}
    elif method == 'thread/start':
        result = {'thread': {'id': 'thread-new'}}
    elif method == 'turn/start':
        result = {'turn': {'id': 'turn'}}
    print(json.dumps({'id': request['id'], 'result': result}), flush=True)
    if method == 'turn/start':
        thread = request['params']['threadId']
        print(json.dumps({'method': 'item/completed', 'params': {
            'threadId': thread, 'item': {'type': 'agentMessage', 'text': 'verified'}}}), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {
            'threadId': thread, 'turn': {'id': 'turn', 'status': 'completed'}}}), flush=True)
'''


async def main():
    assert sys.platform == 'linux' and os.geteuid() == 0
    parent = Path(os.environ.get('MEMORY_SPARK_CODEX_HOME', '/tmp'))
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='isolation-test-', dir=parent) as directory:
        root = Path(directory)
        root.chmod(0o711)
        legacy = root / 'legacy'
        first = str(UUID(int=1))
        second = str(UUID(int=2))
        (legacy / first / 'sessions').mkdir(parents=True)
        (legacy / first / 'sessions' / 'thread-old.jsonl').write_text('legacy rollout')
        worker = CodexWorker(home_root=root / 'homes', legacy_root=legacy,
                             command=[sys.executable, '-u', '-c', SERVER], timeout=10)
        result = await worker.turn(WorkerTurnInput(
            user_id=first, thread_id='thread-old', text='resume'))
        assert result['reply'] == 'verified'
        assert result['thread_id'] == 'thread-old'
        assert result['artifacts']
        print('PASS: legacy session resume and different-UID child cleanup', flush=True)

        other_uid = worker._uid_for(second)
        other_home = worker._home(second, other_uid)
        victim = other_home / 'private'
        victim.write_text('private memory')
        os.chown(victim, other_uid, other_uid)
        uid = worker._uid_for(first)
        config = worker.home_root / first / 'config.toml'
        config.unlink()
        config.symlink_to(victim)
        worker._home(first, uid)
        assert victim.read_text() == 'private memory'
        assert victim.stat().st_uid == other_uid
        print('PASS: privileged config rewrite cannot follow tenant symlink', flush=True)

        probe = "from pathlib import Path; Path(" + repr(str(victim)) + ").read_text()"
        command = worker._run_command(uid)
        command = command[:command.index(sys.executable)] + [sys.executable, '-c', probe]
        denied = await asyncio.create_subprocess_exec(*command,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        assert await denied.wait() != 0
        print('PASS: tenant cannot read sibling memory', flush=True)

        # Cancellation must kill/reap an app-server which never responds.
        from apps.api.codex_agent import CodexConnection
        waiting = worker._run_command(uid)
        waiting = waiting[:waiting.index(sys.executable)] + [
            sys.executable, '-c', 'import time; time.sleep(60)']
        connection = CodexConnection(waiting, worker.home_root / first, timeout=10)
        task = asyncio.create_task(connection.__aenter__())
        for _ in range(100):
            if hasattr(connection, 'process'):
                break
            await asyncio.sleep(0.01)
        assert hasattr(connection, 'process')
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        assert connection.process.returncode is not None
        print('PASS: cancelled app-server is reaped', flush=True)


if __name__ == '__main__':
    # Mocker currently ignores cap_add/cap_drop. Enforce the Compose capability
    # set in-process so this check cannot accidentally pass with full privilege.
    if sys.platform == 'linux':
        status = dict(line.split(':', 1) for line in Path('/proc/self/status').read_text().splitlines())
        expected = sum(1 << bit for bit in (0, 1, 3, 5, 6, 7))
        if int(status['CapEff'].strip(), 16) != expected:
            if os.environ.get('MEMORY_SPARK_TEST_CAPS_SET'):
                raise RuntimeError('Could not enforce the worker capability set')
            os.environ['MEMORY_SPARK_TEST_CAPS_SET'] = '1'
            os.execv('/usr/bin/setpriv', [
                'setpriv', '--bounding-set=-all,+chown,+dac_override,+fowner,+kill,+setgid,+setuid',
                sys.executable, __file__,
            ])
        print('PASS: supervisor has exactly the configured Linux capabilities', flush=True)
    asyncio.run(main())
