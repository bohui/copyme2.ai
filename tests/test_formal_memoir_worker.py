"""Bounded formal assembly through the service RPC boundary, no providers."""
import asyncio
import json
from pathlib import Path

import httpx
import pytest

from apps.api.formal_memoir import advance_formal_memoir
from apps.api.memory_event_worker import MemoirLaneBroker

RUN = '44444444-4444-4444-8444-444444444444'
TOKEN = '77777777-7777-4777-8777-777777777777'
CHAPTER = '88888888-8888-4888-8888-888888888888'
SOURCE = '99999999-9999-4999-8999-999999999999'


def run_worker(remote, **kwargs):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(remote)) as client:
            broker = MemoirLaneBroker(url='https://synthetic.invalid', key='synthetic-service', client=client)
            return await advance_formal_memoir(broker, RUN, **kwargs)
    return asyncio.run(run())


def test_worker_assembles_complete_exact_evidence_and_returns_persisted_receipt():
    staged = []
    receipt = {'status': 'completed', 'edition_id': CHAPTER, 'revision': 1, 'manuscript_digest': 'c' * 64}

    def remote(request):
        assert request.url.host == 'synthetic.invalid'
        body = json.loads(request.content)
        operation = request.url.path.rsplit('/', 1)[-1]
        if operation == 'claim_formal_memoir':
            result = {'status': 'running', 'run_id': RUN, 'token': TOKEN, 'chapter_count': 1, 'next_ordinal': 1}
        elif operation == 'read_formal_memoir_chapter':
            result = {'chapter_id': CHAPTER, 'title': 'Chapter 1', 'chapter_plan_digest': 'b' * 64,
                      'evidence': [{'source_id': SOURCE, 'version': 1, 'char_start': 3, 'char_end': 20,
                                    'quote': 'I planted a tree.'}]}
        elif operation == 'stage_formal_memoir_chapter':
            staged.append(body)
            result = {'status': 'staged', 'chapter_id': CHAPTER, 'digest': 'a' * 64}
        elif operation == 'complete_formal_memoir':
            result = receipt
        else:
            raise AssertionError(operation)
        return httpx.Response(200, json=result)

    assert run_worker(remote) == receipt
    assert staged[0]['p_chapter'] == {'schema_version': 1, 'chapter_id': CHAPTER, 'title': 'Chapter 1',
        'blocks': [{'text': 'I planted a tree.', 'source_id': SOURCE, 'version': 1, 'char_start': 3, 'char_end': 20}]}
    assert staged[0]['p_validation'] == {'schema_version': 1, 'validator': 'formal-extractive-v1',
        'chapter_plan_digest': 'b' * 64, 'provenance': 'deterministic-extractive', 'blocking_count': 0}


@pytest.mark.parametrize('status', ['busy', 'completed'])
def test_busy_or_completed_run_never_fetches_sources(status):
    def remote(request):
        assert request.url.path.endswith('/claim_formal_memoir')
        return httpx.Response(200, json={'status': status})
    assert run_worker(remote) == {'status': status}


def test_worker_yields_a_fenced_lease_after_its_bounded_quantum():
    operations = []
    def remote(request):
        name = request.url.path.rsplit('/', 1)[-1]
        operations.append(name)
        if name == 'claim_formal_memoir':
            result = {'status': 'running', 'token': TOKEN, 'chapter_count': 2, 'next_ordinal': 1}
        elif name == 'read_formal_memoir_chapter':
            result = {'chapter_id': CHAPTER, 'title': 'Chapter 1', 'chapter_plan_digest': 'b' * 64,
                'evidence': [{'source_id': SOURCE, 'version': 1, 'char_start': 0, 'char_end': 1, 'quote': 'I'}]}
        elif name == 'stage_formal_memoir_chapter':
            result = {'status': 'staged'}
        elif name == 'release_formal_memoir':
            result = {'status': 'pending', 'run_id': RUN, 'next_ordinal': 2}
        else:
            raise AssertionError('Worker exceeded its quantum')
        return httpx.Response(200, json=result)
    assert run_worker(remote, quantum=1) == {'status': 'pending', 'run_id': RUN, 'next_ordinal': 2}
    assert operations[-1] == 'release_formal_memoir'


def test_correction_racing_with_yield_does_not_report_stale_work_as_pending():
    def remote(request):
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'claim_formal_memoir':
            result = {'status': 'running', 'token': TOKEN, 'chapter_count': 2, 'next_ordinal': 1}
        elif name == 'read_formal_memoir_chapter':
            result = {'chapter_id': CHAPTER, 'title': 'Chapter 1', 'chapter_plan_digest': 'b' * 64,
                'evidence': [{'source_id': SOURCE, 'version': 1, 'char_start': 0, 'char_end': 1, 'quote': 'I'}]}
        elif name == 'stage_formal_memoir_chapter':
            result = {'status': 'staged'}
        elif name == 'release_formal_memoir':
            return httpx.Response(400, json={'code': '40001', 'message': 'FORMAL_AUTHORITY_STALE'})
        else:
            raise AssertionError(name)
        return httpx.Response(200, json=result)
    with pytest.raises(httpx.HTTPStatusError):
        run_worker(remote, quantum=1)


@pytest.mark.parametrize('span', [
    {'quote': 'I', 'char_start': 0, 'char_end': 2},
    {'quote': '', 'char_start': 0, 'char_end': 1},
    {'quote': 'I' * 2001, 'char_start': 0, 'char_end': 2001}])
def test_unbounded_or_inconsistent_evidence_never_reaches_commit(span):
    released = []
    def remote(request):
        name = request.url.path.rsplit('/', 1)[-1]
        if name == 'claim_formal_memoir':
            result = {'status': 'running', 'token': TOKEN, 'chapter_count': 1, 'next_ordinal': 1}
        elif name == 'read_formal_memoir_chapter':
            result = {'chapter_id': CHAPTER, 'title': 'Chapter 1', 'chapter_plan_digest': 'b' * 64,
                      'evidence': [{'source_id': SOURCE, 'version': 1, **span}]}
        elif name == 'release_formal_memoir':
            released.append(True)
            result = {'status': 'pending'}
        else:
            raise AssertionError('Invalid evidence reached persistence')
        return httpx.Response(200, json=result)
    with pytest.raises(ValueError):
        run_worker(remote)
    assert released == [True]


@pytest.mark.parametrize('quantum', [0, 9, True])
def test_invalid_quantum_cannot_claim_a_run(quantum):
    def remote(request):
        raise AssertionError('Invalid work request reached the service')
    with pytest.raises(ValueError):
        run_worker(remote, quantum=quantum)


def test_server_chapter_schema_accepts_synthetic_fixture_and_rejects_extra_claims():
    from copy import deepcopy
    from jsonschema import Draft202012Validator, FormatChecker
    from apps.api.formal_memoir import FormalChapter
    root = Path(__file__).resolve().parents[1] / 'skills/memoir-story-game'
    schema = json.loads((root / 'schemas/formal-chapter.schema.json').read_text())
    chapter = json.loads((root / 'tests/fixtures/formal-chapter.json').read_text())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(chapter)
    assert FormalChapter.model_validate(chapter).blocks[0].text == 'I planted a tree.'
    injected = deepcopy(chapter)
    injected['blocks'][0]['unsupported_fact'] = 'A synthetic extra claim.'
    assert list(validator.iter_errors(injected))
    with pytest.raises(ValueError):
        FormalChapter.model_validate(injected)
