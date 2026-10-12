"""Transport setup contracts; real RLS coverage lives in the PostgreSQL suites."""
from pathlib import Path
import copy
import json
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


@pytest.mark.parametrize('publication_tcp', [False, True])
def test_apple_fixture_publication_endpoint_is_opt_in_and_host_loopback_only(monkeypatch, publication_tcp):
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND', 'apple-container')
    monkeypatch.setenv('PGHOST', 'unrelated.invalid')
    calls = []
    def run(self, command, **kwargs):
        assert not any(key.startswith('PG') for key in self.environment or {})
        calls.append(command)
        output = 'PostgreSQL init process complete; ready for start up.' if command[1] == 'logs' else ''
        if command[1] == 'inspect':
            start = next(call for call in calls if call[1] == 'run')
            port = int(start[start.index('--publish') + 1].split(':')[1])
            output = json.dumps(publication_snapshot(command[-1], port))
        return subprocess.CompletedProcess(command, 0, output, '')
    class SqlTransport:
        def __init__(self, command, **kwargs): self.command = command
        def __call__(self, query): return subprocess.CompletedProcess(self.command, 0, '', '')
        def close(self): pass
    monkeypatch.setattr(fixture.ProcessDeadline, 'run', run)
    monkeypatch.setattr(fixture, 'ContainerSql', SqlTransport)
    setup = fixture.database.__wrapped__(**({'publication_tcp': True} if publication_tcp else {}))
    try:
        sql = next(setup)
        start = next(command for command in calls if command[1] == 'run')
        name = start[start.index('--name') + 1]
        assert start[start.index('--cpus') + 1] == '1'
        assert start[start.index('--memory') + 1] == '1G'
        assert not any(option in start for option in ('--volume', '--mount', '--network'))
        if publication_tcp:
            binding = start[start.index('--publish') + 1]
            host, port, target = binding.split(':')
            assert host == '127.0.0.1' and target == '5432'
            assert 1024 < int(port) < 65536
            assert sql.publication_dsn == f'host=127.0.0.1 port={port} user=postgres dbname=postgres'
            release = next(call for call in calls if any('mv /tmp/memoir-publication-address.tmp' in part for part in call))
            assert release[-1] == '192.168.64.2'
            assert 'listen_addresses=*' not in ' '.join(start)
        else:
            assert '--publish' not in start and '-p' not in start
            assert start[-1] == 'listen_addresses='
            assert getattr(sql, 'publication_dsn', None) is None
    finally:
        setup.close()
    assert calls[-1] == ['container', 'stop', name]


def publication_snapshot(name='memoir-issue6-pg-0123456789ab', port=35432):
    return [{'configuration': {'id': name, 'publishedPorts': [{'hostAddress': '127.0.0.1',
        'hostPort': port, 'containerPort': 5432, 'proto': 'tcp', 'count': 1}]},
        'status': {'state': 'running', 'networks': [{'ipv4Address': '192.168.64.2/24'}]}}]


@pytest.mark.parametrize('problem', ['wrong_id', 'broad_host', 'wrong_port', 'multiple_ports',
    'missing_ports', 'wrong_protocol', 'multiple_guests', 'no_guest', 'public_guest',
    'loopback_guest', 'link_local_guest', 'multicast_guest', 'invalid_guest', 'stopped'])
def test_apple_publication_inspection_fails_closed_before_releasing_guest(monkeypatch, problem):
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND', 'apple-container')
    calls = []
    def run(self, command, **kwargs):
        calls.append(command)
        output = ''
        if command[1] == 'inspect':
            start = calls[0]
            port = int(start[start.index('--publish') + 1].split(':')[1])
            snapshot = publication_snapshot(command[-1], port)
            config, status = snapshot[0]['configuration'], snapshot[0]['status']
            if problem == 'wrong_id': config['id'] = 'unrelated-container'
            elif problem == 'broad_host': config['publishedPorts'][0]['hostAddress'] = '0.0.0.0'
            elif problem == 'wrong_port': config['publishedPorts'][0]['hostPort'] += 1
            elif problem == 'multiple_ports': config['publishedPorts'] *= 2
            elif problem == 'missing_ports': config.pop('publishedPorts')
            elif problem == 'wrong_protocol': config['publishedPorts'][0]['proto'] = 'udp'
            elif problem == 'multiple_guests': status['networks'] *= 2
            elif problem == 'no_guest': status['networks'] = []
            elif problem == 'stopped': status['state'] = 'stopped'
            else:
                status['networks'][0]['ipv4Address'] = {'public_guest': '8.8.8.8/24',
                    'loopback_guest': '127.0.0.1/8', 'link_local_guest': '169.254.1.2/16',
                    'multicast_guest': '224.0.0.1/4', 'invalid_guest': 'not-an-ip'}[problem]
            output = json.dumps(snapshot)
        return subprocess.CompletedProcess(command, 0, output, '')
    monkeypatch.setattr(fixture.ProcessDeadline, 'run', run)
    with pytest.raises((ValueError, KeyError)):
        next(fixture.database.__wrapped__(publication_tcp=True))
    assert [call[1] for call in calls] == ['run', 'inspect', 'stop']
    assert calls[-1][-1] == calls[0][calls[0].index('--name') + 1]


def test_apple_publication_accepts_known_older_inspection_shape_only():
    snapshot = publication_snapshot()
    old = copy.deepcopy(snapshot)
    old[0]['networks'] = old[0]['status']['networks']
    old[0]['status'] = 'running'
    assert fixture.publication_guest_address(old, 'memoir-issue6-pg-0123456789ab', 35432) == '192.168.64.2'


def test_apple_publication_port_collision_never_falls_back_or_releases_guest(monkeypatch):
    monkeypatch.setenv('MEMOIR_TEST_POSTGRES_BACKEND', 'apple-container')
    calls = []
    def run(self, command, **kwargs):
        calls.append(command)
        if command[1] == 'run':
            raise subprocess.CalledProcessError(1, command, b'', b'port already in use')
        return subprocess.CompletedProcess(command, 0, '', '')
    monkeypatch.setattr(fixture.ProcessDeadline, 'run', run)
    with pytest.raises(subprocess.CalledProcessError):
        next(fixture.database.__wrapped__(publication_tcp=True))
    assert [call[1] for call in calls] == ['run', 'stop']
    assert calls[-1][-1] == calls[0][calls[0].index('--name') + 1]
