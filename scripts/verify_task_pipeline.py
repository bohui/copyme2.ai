"""Run inside the API container to verify real publisher → Temporal → worker.

Uses synthetic sources only. The resulting task/workflow is retained as an
operational smoke-test receipt under a fresh, non-customer owner UUID.
"""
import json
import os
import time
from uuid import uuid4

import httpx

from apps.api.task_queue import configured_queue


def main():
    owner = str(uuid4())
    payload = {'user_id': owner, 'project_id': 'pipeline-smoke', 'task': {
        'kind': 'BuildSourceExport', 'title': 'Synthetic pipeline check',
        'sources': [{'id': 'synthetic-memory', 'content': 'Synthetic worker test; no personal data.'}],
    }}
    url = os.environ['MEMORY_SPARK_CODEX_WORKER_URL'] + '/internal/tasks'
    headers = {'X-Codex-Worker-Secret': os.environ['MEMORY_SPARK_CODEX_WORKER_SECRET']}
    with httpx.Client(timeout=15) as client:
        response = client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        queued = response.json()
        duplicate = client.post(url, headers=headers, json=payload)
        duplicate.raise_for_status()
        assert duplicate.json()['id'] == queued['id'], 'Duplicate submission created another task'
    queue = configured_queue()
    for _ in range(45):
        result = queue.get(owner, queued['id'])
        if result['status'] == 'SUCCEEDED':
            assert result['result']['sources'] == payload['task']['sources']
            assert queue.get(str(uuid4()), queued['id']) is None
            print(json.dumps({'task_id': queued['id'], 'workflow_id': f"memoir-task:{queued['id']}",
                              'status': 'SUCCEEDED', 'deduplicated': True, 'owner_isolated': True}))
            return
        if result['status'] == 'FAILED':
            raise RuntimeError('Synthetic task failed')
        time.sleep(1)
    raise RuntimeError('Synthetic task did not complete within 45 seconds')


if __name__ == '__main__':
    main()
