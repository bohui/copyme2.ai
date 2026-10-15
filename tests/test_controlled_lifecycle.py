"""Ownership and signal scopes for the shared diagnostic lifecycle helper."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess

import pytest

from scripts.controlled_lifecycle import ALLOCATION_ROOT_ENV, cancel_on_sigterm, new_native_root, reconcile_native_directory, sigterm_cancellable


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


@pytest.mark.parametrize('nested', [False, True])
def test_reconciliation_refuses_an_unrelated_pid_without_removing_identity(tmp_path, monkeypatch, nested):
    owner = tmp_path/'memoir-case-nested' if nested else tmp_path
    data = owner/'memoir-lease-pg-synthetic'/'data'
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


def test_transitive_registration_keeps_sibling_roots_short_and_removes_every_owner(monkeypatch):
    roots = []
    try:
        monkeypatch.delenv(ALLOCATION_ROOT_ENV, raising=False)
        for _ in range(4):
            root = new_native_root('memoir-case-')
            roots.append(root)
            assert root.parent == Path('/tmp')
            if len(roots) > 1:
                record = json.loads((roots[-2]/'owned-roots'/(root.name+'.json')).read_text())
                stat = root.stat()
                assert record == dict(root=str(root), device=stat.st_dev, inode=stat.st_ino)
            monkeypatch.setenv(ALLOCATION_ROOT_ENV, str(root))
        result = reconcile_native_directory(roots[0], dict(os.environ))
        assert result['verified'] and result['root_removed']
        assert {item['root'] for item in result['registered_roots']} == set(map(str, roots))
        assert all(not root.exists() for root in roots)
    finally:
        for root in roots:
            if root.exists():shutil.rmtree(root)


def test_changed_registered_root_identity_retains_both_owners(monkeypatch):
    roots = []
    try:
        monkeypatch.delenv(ALLOCATION_ROOT_ENV, raising=False)
        parent = new_native_root('memoir-case-');roots.append(parent)
        monkeypatch.setenv(ALLOCATION_ROOT_ENV, str(parent))
        child = new_native_root('memoir-case-');roots.append(child)
        registration = parent/'owned-roots'/(child.name+'.json')
        record = json.loads(registration.read_text());record['inode'] += 1
        registration.write_text(json.dumps(record))
        with pytest.raises(RuntimeError, match='allocation identity changed'):
            reconcile_native_directory(parent, dict(os.environ))
        assert parent.exists() and child.exists() and registration.exists()
    finally:
        for root in roots:
            if root.exists():shutil.rmtree(root)


def test_changed_command_birth_never_signals_a_group(tmp_path, monkeypatch):
    group = os.getpgrp()
    (tmp_path/'command-group.json').write_text(json.dumps(dict(group_id=group,leader_started='different birth')))
    signals = []
    monkeypatch.setattr(os, 'killpg', lambda *args:signals.append(args))
    with pytest.raises(RuntimeError, match='command identity unverified'):
        reconcile_native_directory(tmp_path, dict(os.environ))
    assert signals == [] and (tmp_path/'command-group.json').exists()


def test_missing_wrapper_command_record_cannot_verify_an_empty_root(tmp_path):
    root = tmp_path/'memoir-check-pg-unregistered';root.mkdir()
    with pytest.raises(RuntimeError, match='command identity unavailable'):
        reconcile_native_directory(root, dict(os.environ))
    assert root.exists()
