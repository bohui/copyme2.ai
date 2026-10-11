"""Transport setup contracts; real RLS coverage lives in the PostgreSQL suites."""
from pathlib import Path
import subprocess

import pytest

import test_agent_commit_postgres as fixture


def test_native_tcp_fixture_uses_loopback_and_owned_port(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND', 'native-tcp')
    monkeypatch.setattr(fixture.shutil, 'which', lambda name: '/fixture/' + name)
    monkeypatch.setenv('PGHOST', 'remote.invalid')
    monkeypatch.setenv('PGOPTIONS', '-c search_path=hostile')
    calls = []
    def run(self, command, **kwargs):
        assert not any(key.startswith('PG') for key in self.environment)
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(fixture.ProcessDeadline, 'run', run)
    setup = fixture.database.__wrapped__()
    try:
        sql = next(setup)
        assert '--encoding=UTF8' in next(c for c in calls if c[0] == 'initdb')
        start = next(c for c in calls if c[0] == 'pg_ctl' and c[-1] == 'start')
        options = start[start.index('-o') + 1]
        assert '-h 127.0.0.1' in options
        assert "-k ''" in options
        assert sql.command[sql.command.index('-h') + 1] == '127.0.0.1'
        port = int(sql.command[sql.command.index('-p') + 1])
        assert 0 < port < 65536 and f'-p {port}' in options
    finally:
        setup.close()
    assert calls[-1][0] == 'pg_ctl' and calls[-1][-1] == 'stop'


def test_native_fixture_stops_partial_start_and_preserves_server_error(monkeypatch):
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND', 'native-tcp')
    monkeypatch.setattr(fixture.shutil, 'which', lambda name: '/fixture/' + name)
    calls = []
    def run(self, command, **kwargs):
        calls.append(command)
        if command[0] == 'initdb':
            Path(command[command.index('-D') + 1]).mkdir()
        if command[0] == 'pg_ctl' and command[-1] == 'start':
            data = Path(command[command.index('-D') + 1])
            (data / 'postmaster.pid').write_text('123\n')
            Path(command[command.index('-l') + 1]).write_text('specific PostgreSQL startup error')
            raise subprocess.CalledProcessError(1, command, b'', b'failed')
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(fixture.ProcessDeadline, 'run', run)
    with pytest.raises(RuntimeError, match='specific PostgreSQL startup error'):
        next(fixture.database.__wrapped__())
    assert calls[-1][0] == 'pg_ctl' and calls[-1][-1] == 'stop'
