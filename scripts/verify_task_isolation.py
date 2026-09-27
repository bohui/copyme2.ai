"""Run inside codex-worker: verify a tenant cannot access task persistence."""
import os
import subprocess
import sys
from pathlib import Path


def main():
    assert 'MEMORY_SPARK_TASK_DB' not in os.environ
    assert not Path('/var/lib/memoir-tasks').exists()
    assert 'memoir-tasks' not in Path('/proc/mounts').read_text()
    target = os.environ['MEMORY_SPARK_TASK_STORE_URL'] + '/internal/tasks'
    probe = '''
import json, os, sys, urllib.request, urllib.error
assert os.getuid() == 20001
assert 'MEMORY_SPARK_CODEX_WORKER_SECRET' not in os.environ
try:
    open('/var/lib/memoir-tasks/tasks.sqlite', 'rb')
except FileNotFoundError:
    pass
else:
    raise AssertionError('Tenant can reach task database')
payload = {'user_id': '11111111-1111-4111-8111-111111111111', 'project_id': 'isolation-check',
           'task': {'kind': 'BuildSourceExport', 'sources': [{'id': 'synthetic', 'content': 'Synthetic'}]}}
request = urllib.request.Request(sys.argv[1], data=json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(request, timeout=10)
except urllib.error.HTTPError as error:
    assert error.code == 401
else:
    raise AssertionError('Unauthenticated tenant published a task')
'''
    subprocess.run(['/usr/bin/setpriv', '--reuid=20001', '--regid=20001',
                    '--clear-groups', '--no-new-privs', sys.executable, '-c', probe, target],
                   check=True, env={'PATH': os.environ['PATH']}, cwd='/tmp')
    print('PASS: no task mount in Codex; tenant cannot read DB or publish without supervisor credentials')


if __name__ == '__main__':
    main()
