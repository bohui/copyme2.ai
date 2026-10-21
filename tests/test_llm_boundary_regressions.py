"""Regressions from PR 105 review, with fixed model and isolated installations."""
import json
import os
import re
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


def test_installed_photo_skill_uses_local_capture_parsing(tmp_path):
    skill = Path(__file__).resolve().parents[1] / 'skills/memoir-place-photo-research'
    installed = tmp_path / 'codex-home/skills/memoir-place-photo-research'
    shutil.copytree(skill, installed, ignore=shutil.ignore_patterns('__pycache__'))
    script = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location('photo_research', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert not hasattr(module, '_caption_date_proposal')
assert module._crawl4ai_scene_date('Chengde street 1983',
    {'mode': 'historical_range', 'start': '1980-01-01', 'end': '1989-12-31'})['start'] == '1983-01-01'
assert module._crawl4ai_scene_date('Uploaded on 1983',
    {'mode': 'historical_range', 'start': '1980-01-01', 'end': '1989-12-31'}) is None
assert module._crawl4ai_location_matches('Chengde street 1983', 'Chengde')
assert not module._crawl4ai_location_matches('Beijing street 1983', 'Chengde')
"""
    environment = {key: value for key, value in os.environ.items() if not key.startswith(('MEMORY_SPARK_', 'PHOTO_RESEARCH_'))}
    result = subprocess.run([sys.executable, '-I', '-c', script, str(installed / 'scripts/photo_research.py')],
        cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_installed_photo_skill_runs_documented_offline_suite(tmp_path):
    skill = Path(__file__).resolve().parents[1] / 'skills/memoir-place-photo-research'
    installed = tmp_path / '.agents/skills/memoir-place-photo-research'
    shutil.copytree(skill, installed, ignore=shutil.ignore_patterns('__pycache__'))
    environment = {key: value for key, value in os.environ.items()
                   if key != 'PYTHONPATH' and not key.startswith(('MEMORY_SPARK_', 'PHOTO_RESEARCH_'))}
    result = subprocess.run([sys.executable, '-I', '-m', 'unittest', 'discover',
        '-s', '.agents/skills/memoir-place-photo-research/tests', '-v'],
        cwd=tmp_path, env=environment, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert re.search(r'\bRan [1-9]\d* tests?\b', result.stderr), result.stderr
