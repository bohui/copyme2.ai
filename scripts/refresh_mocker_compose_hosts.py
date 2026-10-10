#!/usr/bin/env python3
"""Refresh Mocker's static Compose service aliases after partial recreation.

Only running containers returned by this Compose project are inspected. Peers
must share its project and network labels. Existing unrelated hosts are kept;
no container is started, stopped, or recreated, including an existing frontend.
"""
import argparse
import ipaddress
import json
import re
import subprocess


class RefreshError(RuntimeError):
    pass


def command(executable, *args):
    result = subprocess.run([executable, *args], capture_output=True, text=True, timeout=30)
    if result.returncode:
        # Inspect includes environment credentials. Never include captured output.
        raise RefreshError(f'Container command {args[0]} failed with exit code {result.returncode}')
    return result.stdout


def records(metadata, expected_ids):
    if (not isinstance(metadata, list) or not all(isinstance(v, dict) for v in metadata)
            or {v.get('Id') for v in metadata} != set(expected_ids)):
        raise RefreshError('Compose container inspection did not match its running inventory')
    result = []
    for value in metadata:
        labels = value.get('Config', {}).get('Labels', {})
        service = labels.get('com.mocker.compose.service', '')
        project = labels.get('com.mocker.compose.project', '')
        network = labels.get('com.mocker.compose.network', '')
        if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', service) or not project or not network:
            raise RefreshError('Compose service/network labels are required for alias refresh')
        address = str(ipaddress.ip_address(value['NetworkSettings']['IPAddress']))
        result.append({'id': value['Id'], 'service': service, 'project': project,
                       'network': network, 'address': address})
    if len({v['project'] for v in result}) != 1:
        raise RefreshError('Alias refresh requires one Compose project')
    return result


def hosts_text(original, aliases):
    lines = []
    for line in original.splitlines():
        content, mark, comment = line.partition('#')
        parts = content.split()
        if len(parts) < 2 or not any(name in aliases for name in parts[1:]):
            lines.append(line)
            continue
        remaining = [name for name in parts[1:] if name not in aliases]
        if remaining:
            lines.append(parts[0] + ' ' + ' '.join(remaining) + (' #' + comment if mark else ''))
        elif mark:
            lines.append('#' + comment)
    while lines and not lines[-1].strip():
        lines.pop()
    lines.extend(address + ' ' + name for name, address in sorted(aliases.items()))
    return '\n'.join(lines) + '\n'


def refresh(mocker, compose_file, apple_container='container'):
    ids = command(mocker, 'compose', 'ps', '-f', compose_file, '-q').split()
    if not ids:
        raise RefreshError('No running Compose containers to refresh')
    # Mocker emits separate JSON documents when inspecting multiple containers.
    metadata = []
    for container_id in ids:
        values = json.loads(command(mocker, 'inspect', container_id))
        records(values, [container_id])
        metadata.extend(values)
    peers = records(metadata, ids)
    for target in peers:
        aliases = {peer['service']: peer['address'] for peer in peers
                   if peer['network'] == target['network']}
        if len(aliases) != sum(peer['network'] == target['network'] for peer in peers):
            raise RefreshError('Scaled services require DNS; static aliases must be unique')
        original = command(apple_container, 'exec', target['id'], '/bin/cat', '/etc/hosts')
        expected = hosts_text(original, aliases)
        if original.rstrip('\n') != expected.rstrip('\n'):
            # Mocker 0.9.3 ignores exec's user override; Apple Container honors it.
            command(apple_container, 'exec', '--uid', '0', '--gid', '0', target['id'], '/bin/sh', '-c',
                    'printf "%s" "$1" > /etc/hosts', 'memoir-compose-hosts', expected)
            if command(apple_container, 'exec', target['id'], '/bin/cat', '/etc/hosts').rstrip('\n') != expected.rstrip('\n'):
                raise RefreshError('Compose service-alias readback did not match')
    return [peer['service'] for peer in peers]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mocker', default='mocker')
    parser.add_argument('--apple-container', default='container')
    parser.add_argument('--compose-file', default='compose.yml')
    args = parser.parse_args()
    try:
        services = refresh(args.mocker, args.compose_file, args.apple_container)
        print('Compose service aliases refreshed: ' + ', '.join(services))
    except (RefreshError, ValueError, KeyError, TypeError, OSError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, RefreshError) else 'invalid inspection or unavailable container runtime'
        print(f'Compose service-alias refresh failed: {reason}; no conversation was started')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
