"""Regressions from PR 105 review, with fixed model and isolated installations."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient

from apps.api import agent_routes, policy_review
from apps.api.codex_runtime import CodexRuntime
from apps.api.main import create_app
from apps.api.model_request import complete_json
from apps.api.store import MemoryStore
from memoir_postgres_workflow import PostgresRest
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database, database
from test_agent_commit_postgres import OWNER, as_user
from test_shared_memory_events_postgres import rpc, literal


def pending_source(sql):
    identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
    turn = str(uuid4())
    text = 'A pending original memory.'
    accepted = json.loads(sql(as_user(f"select public.accept_user_interview_turn({literal(identity['project_id'])},'{turn}',{literal(text)});")).stdout)
    assert rpc(sql, 'read_lifetime_policy_status', f"'{identity['conversation_id']}'")['pending']
    return identity, turn, text, accepted['source']


@pytest.mark.parametrize('retry', [True, False])
def test_pause_keeps_pending_review_private_and_uncommitted(sql, tmp_path, monkeypatch, retry):
    identity, turn, text, source = pending_source(sql)
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMOIR_LIFETIME_GENERATION_PAUSED', 'true')
    calls = []
    original = policy_review.complete_json

    async def review(*args, **kwargs):
        calls.append('policy')
        return await original(*args, **kwargs)

    monkeypatch.setattr(policy_review, 'complete_json', review)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(agent_routes, 'runtime', CodexRuntime(home_root=tmp_path / 'homes'))
    with TestClient(create_app(MemoryStore())) as client:
        response = client.post('/v1/agent/turn', json={
            'project_id': identity['project_id'], 'client_turn_id': turn if retry else str(uuid4()),
            'text': text if retry else 'Another memory.'})
    assert response.status_code == 503 and response.headers['X-Error-Code'] == 'LIFETIME_GENERATION_PAUSED'
    assert calls == []
    status = rpc(sql, 'read_lifetime_policy_status', f"'{identity['conversation_id']}'")
    assert status['pending'] and status['pending_source_id'] == source['id']
    assert sql('select count(*) from public.user_lifetime_source_policy_receipt;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip() == '1'


@pytest.mark.parametrize('environment_endpoint', [None, 'https://environment.invalid/v1'])
@pytest.mark.parametrize('pending', [True, False])
def test_policy_review_uses_runtime_gateway_and_credential(sql, tmp_path, monkeypatch, environment_endpoint, pending):
    if pending:
        identity, turn, text, _ = pending_source(sql)
    else:
        identity = rpc(sql, 'resolve_lifetime_conversation', 'null')
        turn, text = str(uuid4()), 'A new original memory.'
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL', sql.publication_dsn)
    monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY', 'true')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'runtime-fixture-key')
    runtime = CodexRuntime(home_root=tmp_path / 'homes', base_url='https://runtime.invalid/task-proxy/v1',
        worker_url='https://worker.invalid', worker_secret='fixture',
        worker_transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    if environment_endpoint is None:
        monkeypatch.delenv('MEMORY_SPARK_LLM_BASE_URL', raising=False)
    else:
        monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', environment_endpoint)
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'environment-fixture-key')
    calls = []

    def provider(request):
        calls.append((str(request.url), request.headers['authorization']))
        return httpx.Response(200, json={'id': 'fixture-policy', 'status': 'completed', 'output': [
            {'type': 'message', 'content': [{'type': 'output_text', 'text': json.dumps({'complete': True, 'restrictions': []})}]}]})

    async def review(*args, **kwargs):
        return await complete_json(*args, **kwargs, transport=httpx.MockTransport(provider))

    monkeypatch.setattr(policy_review, 'complete_json', review)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda _: PostgresRest(sql, OWNER).storage())
    monkeypatch.setattr(agent_routes, 'runtime', runtime)
    with TestClient(create_app(MemoryStore())) as client:
        client.post('/v1/agent/turn', json={'project_id': identity['project_id'], 'client_turn_id': turn, 'text': text})
    assert calls == [('https://runtime.invalid/task-proxy/v1/responses', 'Bearer runtime-fixture-key')]
    assert sql('select count(*) from public.user_lifetime_source_policy_receipt;').stdout.strip() == '1'


@pytest.mark.parametrize('configured', [False, True])
def test_installed_photo_skill_can_inspect_without_memoir(tmp_path, configured):
    skill = Path(__file__).resolve().parents[1] / 'skills/memoir-place-photo-research'
    installed = tmp_path / 'codex-home/skills/memoir-place-photo-research'
    shutil.copytree(skill, installed, ignore=shutil.ignore_patterns('__pycache__'))
    if configured:
        # Synthetic pins exist only in this disposable installation.
        for part in ('discovery', 'capture-evidence'):
            prompt = installed / 'prompts' / f'{part}.md'
            prompt.with_name(prompt.name + '.langfuse.json').write_text(json.dumps({
                'schema_version': 1, 'type': 'text', 'version': 7,
                'name': f'memoir/skills/memoir-place-photo-research/{part}',
                'sha256': hashlib.sha256(prompt.read_bytes()).hexdigest()}))
    script = """
import importlib.util, sys, io, json, os
spec = importlib.util.spec_from_file_location('photo_research', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
module._crawl4ai_load_dotenv = lambda: None
if sys.argv[2] == 'False':
    assert module._caption_date_proposal([{'caption': 'An observed caption.'}]) is None
else:
    os.environ.update(MEMORY_SPARK_LLM_BASE_URL='https://fixture.invalid/v1',
        MEMORY_SPARK_LLM_API_KEY='fixture-key', MEMORY_SPARK_LLM_MODEL='fixture-model', MEMORY_SPARK_PHOTO_WEB_SEARCH='1')
    calls = []
    def respond(request, **kwargs):
        body = json.loads(request.data)
        assert request.full_url == 'https://fixture.invalid/v1/responses'
        calls.append(body)
        if 'tools' in body:
            value = {'id': 'fixture-search', 'output': [{'type': 'web_search_call', 'id': 'fixture-tool',
                'status': 'completed', 'action': {'sources': [{'url': 'https://archive.invalid/photo'}]}}]}
        else:
            value = {'id': 'fixture-caption', 'status': 'completed', 'output': [{'type': 'message',
                'content': [{'type': 'output_text', 'text': '{"complete":true,"assertions":[]}'}]}]}
        return io.BytesIO(json.dumps(value).encode())
    module.http_request.urlopen = respond
    module.public_addresses = lambda *args: None
    caption = module._caption_date_proposal([{'caption': 'An observed caption.'}])
    assert caption['complete'] is True
    assert caption['receipt']['prompt_manifest']['artifacts'][0]['version'] == 7
    search = module.llm_search('A public city', {'mode': 'current'})
    assert search['prompt_manifest']['artifacts'][0]['name'].endswith('/discovery')
    assert len(calls) == 2 and calls[0]['instructions'] and calls[1]['instructions']
    prompt = module._prompt_adapter().prompt_path('memoir/skills/memoir-place-photo-research/capture-evidence')
    prompt.write_text('Unpublished edit')
    try:
        module._caption_date_proposal([{'caption': 'An observed caption.'}])
        raise AssertionError('Changed instructions must not be dispatched')
    except ValueError:
        pass
    assert len(calls) == 2
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith(('MEMORY_SPARK_', 'PHOTO_RESEARCH_'))}
    result = subprocess.run([sys.executable, '-I', '-c', script, str(installed / 'scripts/photo_research.py'), str(configured)],
        cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
