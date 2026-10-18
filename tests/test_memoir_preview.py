import asyncio
import copy
import json

import pytest
from fastapi.testclient import TestClient

from apps.api import memoir_preview
from apps.api.main import create_app
from apps.api.store import MemoryStore
from test_recall import RecallStorage
from test_story_flow import _auth_headers


@pytest.mark.parametrize('old_flag',[None,'false','true'])
def test_canonical_draft_head_does_not_depend_on_a_retired_rollout_flag(monkeypatch,old_flag):
    if old_flag is None:monkeypatch.delenv('MEMOIR_LIFETIME_MEMORY',raising=False)
    else:monkeypatch.setenv('MEMOIR_LIFETIME_MEMORY',old_flag)
    calls=[]
    head={'snapshot_state':'pending','project_id':'canonical-project'}
    class Storage:
        def lifetime_rpc(self,name,**payload):
            calls.append((name,payload))
            return head
    assert memoir_preview.lifetime_draft_head(Storage(),'canonical-project')==head
    assert calls==[('read_lifetime_private_draft_head',{'p_project_id':'canonical-project'})]


@pytest.fixture(autouse=True)
def private_queue(monkeypatch, tmp_path):
    monkeypatch.setenv('MEMORY_SPARK_TASK_DB', str(tmp_path / 'preview.sqlite'))


@pytest.mark.parametrize('reply', ['{"ready":true}', '```json\n{"ready":true}\n```', '```\n{"ready":true}\n```'])
def test_composer_json_may_have_a_markdown_envelope(reply):
    assert memoir_preview.json_reply(reply) == {'ready': True}


def test_composer_commentary_is_not_accepted_as_a_candidate():
    with pytest.raises(ValueError):
        memoir_preview.json_reply('Here is the result: {"ready":true}')


def test_composer_requires_a_canonical_lane_before_dispatch():
    from types import SimpleNamespace

    runtime = SimpleNamespace(worker_url='http://worker.invalid', worker_secret='synthetic')
    with pytest.raises(ValueError, match='canonical composer lane'):
        asyncio.run(memoir_preview.composer_call(runtime, None, 'p', 'en-AU', 'draft', {}))


def test_removed_index_workflow_cannot_start_model_work(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail('Retired index workflow reached a model')
    monkeypatch.setattr(memoir_preview, 'composer_call', forbidden)
    with pytest.raises(KeyError):
        memoir_preview.composer_instructions('index')
    with pytest.raises(KeyError):
        memoir_preview.composer_output_schema('index')
    with pytest.raises(ValueError, match='canonical event index'):
        asyncio.run(memoir_preview.compose_candidate({'context': {}}, None, None, 'p', 'en-AU',
            checkpoint={}, progress=forbidden))


def test_legacy_preview_fallback_does_not_create_a_generation_job(monkeypatch):
    storage, _ = fixture_storage()
    def forbidden(*args, **kwargs):
        pytest.fail('Legacy preview started model work')
    monkeypatch.setattr(memoir_preview, 'composer_call', forbidden)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda _: storage))
    response = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
    assert response.status_code == 503
    assert response.headers['X-Error-Code'] == 'LIFETIME_CANONICAL_REQUIRED'


def test_drafting_and_review_use_pinned_prompt_artifacts(monkeypatch, tmp_path):
    import shutil
    before = {phase: memoir_preview.composer_instructions(phase)
              for phase in ('prepare', 'draft', 'review')}
    skill = tmp_path / 'memoir-composer'
    shutil.copytree(memoir_preview.SKILL, skill)
    policy = 'An updated narrative policy supplied by the skill bundle.'
    (skill / 'references/narrative-enrichment.md').write_text(policy)
    monkeypatch.setattr(memoir_preview, 'SKILL', skill)

    for phase, expected in before.items():
        assert memoir_preview.composer_instructions(phase) == expected
        assert policy not in expected


def test_narrative_policy_change_invalidates_preview_cache(monkeypatch, tmp_path):
    import shutil
    skill = tmp_path / 'memoir-composer'
    shutil.copytree(memoir_preview.SKILL, skill)
    monkeypatch.setattr(memoir_preview, 'SKILL', skill)
    before = memoir_preview.snapshot_key([], 'project', 'en-AU')
    policy = skill / 'references/narrative-enrichment.md'
    policy.write_text(policy.read_text() + '\nUpdated editorial guidance.\n')

    assert memoir_preview.snapshot_key([], 'project', 'en-AU') != before


def test_index_versions_are_bound_to_the_immutable_source_registry():
    request = {'sources': [{'id': 's1', 'version': 'immutable-hash'}],
               'periods': [], 'events': [{'id': 'e1', 'summary': 'Original fact',
                    'source_refs': [{'source_id': 's1', 'version': 'mistyped-hash? no'}]}]}
    bound = memoir_preview.bind_index_sources(request)
    assert bound['events'][0]['source_refs'] == [{'source_id': 's1', 'version': 'immutable-hash'}]
    assert bound['events'][0]['summary'] == 'Original fact'
    assert request['events'][0]['source_refs'][0]['version'] == 'mistyped-hash? no'


@pytest.mark.parametrize('sources', [[], [{'id': 's1', 'version': 'v1'}, {'id': 's1', 'version': 'v2'}]])
def test_index_cannot_bind_unknown_or_ambiguous_source_references(sources):
    request = {'sources': sources, 'periods': [], 'events': [
        {'source_refs': [{'source_id': 's1', 'version': 'invented'}]}]}
    with pytest.raises(ValueError, match='source reference'):
        memoir_preview.bind_index_sources(request)


def test_canonical_included_event_without_placement_is_deferred():
    draft = {
        'kind': 'sample_chapter',
        'chapters': [{'id': 'chapter', 'event_ids': ['placed']}],
        'storyline': {'event_ids': []},
        'event_dispositions': [
            {'event_id': 'placed', 'disposition': 'included', 'chapter_ids': ['chapter'],
             'reason': 'Placed.'},
            {'event_id': 'orphan', 'disposition': 'included', 'chapter_ids': ['chapter'],
             'reason': 'Orphan.'},
        ],
    }
    result = memoir_preview.normalize_canonical_event_dispositions(draft)
    assert result['event_dispositions'][1] == {
        'event_id': 'orphan', 'disposition': 'deferred', 'chapter_ids': [],
        'reason': 'Orphan. 事件未在当前章节中落位，暂缓纳入本次样章。',
    }


def test_new_chapter_revision_normalization_preserves_existing_revision_checks():
    request = {'prior_state': {'chapters': [{'chapter': {'id': 'existing'}}]}}
    draft = {'chapters': [{'id': 'existing', 'base_revision': 2, 'blocks': []},
                          {'id': 'new', 'base_revision': 5, 'blocks': []}]}
    assert memoir_preview.normalize_new_chapter_revisions(request, draft)['chapters'] == [
        {'id': 'existing', 'base_revision': 2, 'blocks': []},
        {'id': 'new', 'base_revision': 0, 'blocks': []}]


def test_composition_retry_preserves_rejected_candidate_and_exact_validation(monkeypatch):
    from test_lifetime_memory_lane_engine import page, fence_for
    from apps.api.lifetime_memory_lane_engine import canonical_lane_request
    request = canonical_lane_request(fence_for(page('composer')))
    checkpoint = {'request': request}
    rejected = {'text': 'candidate requiring correction'}
    validation = {'ok': False, 'errors': [{'code': 'UNKNOWN_EVENT', 'at': 'event-ledger'}]}
    saved = []
    calls = []
    async def operation(kind, *args):
        return {'ready': True, 'input_fingerprint': 'fixture', 'counter': {}} if kind == 'plan' else validation
    async def progress(phase):
        saved.append(copy.deepcopy(checkpoint))
    async def call(*args):
        calls.append(copy.deepcopy(args[-1]))
        if len(calls) == 1:
            return rejected
        raise TimeoutError('interrupted correction')
    monkeypatch.setattr(memoir_preview, 'skill_operation', operation)
    monkeypatch.setattr(memoir_preview, 'composer_call', call)
    for _ in range(2):
        with pytest.raises(TimeoutError):
            asyncio.run(memoir_preview.compose_candidate(request, None, None, 'p', 'zh-CN',
                        checkpoint=checkpoint, progress=progress))
    assert saved[-1]['repair'] == {'candidate': rejected, 'validation': validation, 'review': None}
    assert calls[-1]['candidate'] == rejected
    assert calls[-1]['validation'] == validation


@pytest.mark.parametrize('phase', ['draft', 'review'])
def test_composer_wire_schemas_support_chatgpt_strict_output(phase):
    # ChatGPT strict structured output rejects optional object properties,
    # including properties of referenced definitions used by later phases.
    def check(value):
        if isinstance(value, dict):
            if 'const' in value:
                assert 'type' in value
            if value.get('type') == 'object':
                assert set(value.get('required', [])) == set(value.get('properties', {}))
                assert value.get('additionalProperties') is False
            for child in value.values():
                check(child)
        elif isinstance(value, list):
            for child in value:
                check(child)

    check(memoir_preview.composer_output_schema(phase))


@pytest.mark.parametrize('phase', ['draft'])
def test_composer_wire_null_offsets_preserve_domain_refs(phase):
    from jsonschema import Draft202012Validator

    original = json.loads((memoir_preview.SKILL / 'examples/focused_trial/draft.json').read_text())
    expected = original
    wire_reply = copy.deepcopy(expected)

    def add_null_offsets(value):
        if isinstance(value, dict):
            if 'source_id' in value and 'version' in value:
                value.setdefault('char_start', None)
                value.setdefault('char_end', None)
            for child in value.values():
                add_null_offsets(child)
        elif isinstance(value, list):
            for child in value:
                add_null_offsets(child)

    add_null_offsets(wire_reply)
    Draft202012Validator(memoir_preview.composer_output_schema(phase)).validate(wire_reply)
    result = memoir_preview.normalize_composer_refs(wire_reply)
    assert result == expected  # Preserve real quote offsets and other nullable fields.


def fixture_storage(name='focused_trial', anonymous=False):
    original = json.loads((memoir_preview.SKILL / f'examples/{name}/request.json').read_text())
    storage = RecallStorage(completed=20, anonymous=anonymous)
    storage._memories = [{
        'id': source['id'], 'kind': 'agent',
        'content': f"Storyteller: {source['text']}\nMemory Spark: Invented assistant biography",
    } for source in original['sources']]
    return storage, original


def test_preview_is_not_started_before_backend_limit(monkeypatch):
    storage, _ = fixture_storage()
    storage.completed = 19
    def forbidden(*args, **kwargs):
        pytest.fail('Preview admission started model work')
    monkeypatch.setattr(memoir_preview, 'composer_call', forbidden)
    client = TestClient(create_app(MemoryStore(), story_storage_factory=lambda authorization: storage))
    response = client.post('/v1/story/preview', headers=_auth_headers(), json={'project_id': 'project-preview'})
    assert response.status_code == 409


@pytest.mark.parametrize('kind', ['sample_storyline', 'sample_chapter'])
def test_reader_preview_suppresses_only_leading_title_headings(kind):
    chapter = {'blocks': [
        {'type': 'heading', 'text': ' 从承德到悉尼 '},
        {'type': 'paragraph', 'text': '正文原样保留。'},
        {'type': 'heading', 'text': '晚年的记忆'},
        {'type': 'paragraph', 'text': '从承德到悉尼'},
        {'type': 'heading', 'text': '从承德到悉尼'},
    ]}
    bundle = {'preview': {'kind': kind, 'title': '从承德到悉尼', 'text': 'old rendered text'},
              'draft': {'storyline': chapter}, 'manuscript': {'chapters': [chapter]}}
    original = copy.deepcopy(bundle)
    assert memoir_preview.reader_preview(bundle)['text'] == '正文原样保留。\n\n晚年的记忆\n\n从承德到悉尼\n\n从承德到悉尼'
    assert bundle == original


def test_cached_sample_reprojects_title_without_recomposing():
    bundle = {'snapshot_key': 'k', 'preview': {'kind': 'sample_storyline', 'title': 'Sample', 'text': 'Sample\n\nBody'},
              'draft': {'storyline': {'blocks': [{'type': 'heading', 'text': 'Sample'}, {'type': 'paragraph', 'text': 'Body'}]}}}
    rows = [{'kind': 'memoir', 'source_paths': ['memoir-preview:p'], 'content': json.dumps(bundle)}]
    assert memoir_preview.cached_preview(rows, 'k')['text'] == 'Body'
