import json

import pytest

from scripts import refresh_mocker_compose_hosts as module


def peer(service, address, *, network='llm-network', project='memory-spark'):
    return {'id': 'memory-spark-' + service + '-1', 'configuration': {'labels': {
        'com.mocker.compose.service': service, 'com.mocker.compose.project': project,
        'com.mocker.compose.network': network}},
        'status': {'state': 'running', 'networks': [{'network': network, 'ipv4Address': address + '/24'}]}}


def test_refresh_repairs_missing_api_aliases_and_stale_worker_frontend_aliases(monkeypatch):
    metadata = [peer('api', '192.168.66.168'), peer('codex-worker', '192.168.66.149'),
                peer('worker', '192.168.66.174'), peer('web', '192.168.66.170')]
    contents = {v['id']: '127.0.0.1 localhost\n192.168.66.150 api\n' for v in metadata}
    contents[metadata[0]['id']] = '127.0.0.1 localhost\n192.168.66.168 memory-spark-api-1\n'
    calls = []

    def command(executable, *args):
        calls.append(args)
        assert executable == ('mocker' if args[0] == 'compose' else 'container')
        if args[:2] == ('compose', 'ps'):
            return '\n'.join(contents)
        if args[0] == 'inspect':
            assert len(args) == 2
            return json.dumps([v for v in metadata if v['id'] == args[1]])
        if args[0] == 'exec' and args[-2:] == ('/bin/cat', '/etc/hosts'):
            return contents[args[1]] + '\n'  # Extra trailing newlines must not cause rewrites.
        if args[:5] == ('exec', '--uid', '0', '--gid', '0'):
            contents[args[5]] = args[-1]
            return ''
        raise AssertionError(args)
    monkeypatch.setattr(module, 'command', command)
    assert module.refresh('mocker', 'compose.yml') == ['api', 'codex-worker', 'worker', 'web']
    for text in contents.values():
        assert '192.168.66.168 api\n' in text and '192.168.66.149 codex-worker\n' in text
        assert '192.168.66.150 api' not in text
    assert '192.168.66.168 memory-spark-api-1' in contents[metadata[0]['id']]
    previous = len(calls)
    module.refresh('mocker', 'compose.yml')
    assert not any(c[:5] == ('exec', '--uid', '0', '--gid', '0') for c in calls[previous:])
    metadata[0]['status']['networks'][0]['ipv4Address'] = '192.168.66.169/24'
    module.refresh('mocker', 'compose.yml')
    for text in contents.values():
        assert '192.168.66.169 api\n' in text and '192.168.66.168 api\n' not in text
    assert not any(c[0] in {'start', 'stop', 'rm', 'restart'} for c in calls)


def test_hosts_preserve_unrelated_names_comments_and_ipv6():
    text = '127.0.0.1 localhost\n::1 localhost ip6-localhost\n# api remains a comment\n192.168.0.1 api custom # keep me\n192.168.0.2 private\n'
    value = module.hosts_text(text, {'api': '192.168.66.168'})
    assert '::1 localhost ip6-localhost\n' in value
    assert '# api remains a comment\n' in value
    assert '192.168.0.1 custom # keep me\n' in value
    assert '192.168.0.2 private\n' in value
    assert value.count('192.168.66.168 api\n') == 1


@pytest.mark.parametrize('mutation', [
    lambda v: v[0]['status']['networks'][0].update(ipv4Address='192.168.66.1; bad'),
    lambda v: v[0]['status'].update(state='stopped'),
    lambda v: v[0]['status']['networks'][0].update(network='other-network'),
    lambda v: v[0]['status']['networks'].append(v[0]['status']['networks'][0]),
    lambda v: v[0]['configuration']['labels'].update({'com.mocker.compose.service': 'api; bad'}),
    lambda v: v[0]['configuration']['labels'].update({'com.mocker.compose.network': ''}),
    lambda v: v[0].update(id='foreign-id'),
    lambda v: v.append(peer('web', '192.168.66.170', project='other-project')),
])
def test_unverified_addresses_and_inventory_are_rejected(mutation):
    metadata = [peer('api', '192.168.66.168')]
    mutation(metadata)
    ids = ['memory-spark-api-1']
    if len(metadata) > 1:
        ids.append(metadata[-1]['id'])
    with pytest.raises((module.RefreshError, ValueError)):
        module.records(metadata, ids)
