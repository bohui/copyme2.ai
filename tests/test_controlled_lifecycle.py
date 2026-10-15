"""Ownership and signal scopes for the shared diagnostic lifecycle helper."""
import asyncio
import os
import signal
import subprocess

import pytest

from scripts.controlled_lifecycle import cancel_on_sigterm, reconcile_native_directory, sigterm_cancellable


def test_nested_concurrent_owners_cancel_and_restore_previous_handler():
    original = signal.getsignal(signal.SIGTERM)
    previous_calls = []
    def previous(*args): previous_calls.append(args)
    signal.signal(signal.SIGTERM, previous)
    async def scenario():
        entered, cleaned = set(), set()
        @sigterm_cancellable
        async def owner(name):
            with cancel_on_sigterm():
                entered.add(name)
                try:
                    await asyncio.Event().wait()
                finally:
                    await asyncio.sleep(.01)
                    cleaned.add(name)
        tasks = [asyncio.create_task(owner(name)) for name in ('one', 'two')]
        while len(entered) < 2:
            await asyncio.sleep(0)
        handler = signal.getsignal(signal.SIGTERM)
        assert handler is not previous
        handler(signal.SIGTERM, None)
        results = await asyncio.gather(*tasks, return_exceptions=True)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert cleaned == entered == {'one', 'two'}
        assert signal.getsignal(signal.SIGTERM) is previous
    try:
        asyncio.run(scenario())
        assert previous_calls == []
    finally:
        signal.signal(signal.SIGTERM, original)


def test_reconciliation_refuses_an_unrelated_pid_without_removing_identity(tmp_path, monkeypatch):
    data = tmp_path/'memoir-lease-pg-synthetic'/'data'
    data.mkdir(parents=True)
    pid_file = data/'postmaster.pid'
    pid_file.write_text(f'{os.getpid()}\n{data}\n')
    run = subprocess.run
    calls = []
    def observe(command, **options):
        calls.append(command[0])
        assert command[0] == 'ps', 'An unverified process must never receive a stop command'
        return run(command, **options)
    monkeypatch.setattr(subprocess, 'run', observe)
    with pytest.raises(RuntimeError, match='identity unverified'):
        reconcile_native_directory(tmp_path, dict(os.environ))
    assert calls == ['ps']
    assert pid_file.read_text() == f'{os.getpid()}\n{data}\n'
