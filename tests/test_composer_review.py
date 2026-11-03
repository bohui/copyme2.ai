"""Acceptance of exact prose and explicit original-source contributions."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.memoir_preview import compose_candidate
from controlled_composer_review import controlled_review


@pytest.mark.parametrize('changed', ['source_id', 'section_id'])
def test_craft_review_cannot_reformat_opaque_evidence_identifiers(changed):
    from apps.api.composer_review import review_errors
    text = 'The bicycle was blue.'
    ref = dict(source_id='source:opaque-01', version='1', char_start=0, char_end=len(text))
    unit = dict(section_id='chapter:one__block:one', field='text', excerpt=text, source_refs=[ref])
    requirements = dict(contributions=[dict(source_ref=ref, quote=text)], prose=[unit])
    review = controlled_review(dict(requirements=requirements))
    rating = review['craft']['ratings'][0]
    rating.update(applicability='applicable', score=2,
        source_evidence=[dict(source_ref=deepcopy(ref), excerpt=text)],
        prose_evidence=[{key: unit[key] for key in ('section_id', 'field', 'excerpt')}])
    assert review_errors(review, requirements) == []
    if changed == 'source_id':
        rating['source_evidence'][0]['source_ref']['source_id'] = 'source-opaque-01'
    else:
        rating['prose_evidence'][0]['section_id'] = 'chapter-one__block-one'
    errors = review_errors(review, requirements)
    assert ('CRAFT_SOURCE_MISMATCH' if changed == 'source_id' else 'CRAFT_PROSE_MISMATCH') in errors


@pytest.mark.parametrize('complete_audit', [False, True])
def test_en10_ready_without_findings_cannot_reuse_an_unaudited_review(monkeypatch, complete_audit):
    fixture = json.loads((Path(__file__).parent / 'fixtures/composer_en10_missed_finding.json').read_text())
    phases = []

    async def provider(runtime, storage, project, locale, phase, packet):
        phases.append(phase)
        if phase == 'draft':
            return deepcopy(fixture['candidate'])
        if not complete_audit:
            return deepcopy(fixture['review'])
        review = controlled_review(packet)
        spatial = next(check for check in review['prose_checks'] if 'close at hand' in check['excerpt'])
        spatial.update(verdict='unsupported', explanation='The cited originals never locate the tin close at hand.')
        assert review['findings'] == [] and review['ready_for_user_review'] is True
        return review

    async def progress(phase):
        pass

    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    with pytest.raises(RuntimeError, match='another composition review'):
        asyncio.run(compose_candidate(fixture['request'], SimpleNamespace(), SimpleNamespace(),
            fixture['request']['project_id'], 'en-AU', checkpoint={
                'draft': deepcopy(fixture['candidate']), 'review': deepcopy(fixture['review'])}, progress=progress))
    assert phases == ['review', 'draft', 'review', 'draft', 'review']


def test_unchanged_legacy_bundle_cannot_skip_a_current_review(monkeypatch):
    from apps.api.canonical_composer import compose_shared_snapshot
    from test_canonical_composer_provenance import controlled_draft
    source = dict(id='original', project_id='project', kind='narrator_chat', author_role='storyteller',
        status='active', sequence=1, version=1, text='I grew up in Chengde.')
    event = dict(id='childhood', revision=1, life_stage='unplaced', status='active', title='Childhood',
        source_refs=[dict(source_id='original', version=1, char_start=0, char_end=21, quote=source['text'])])
    job = dict(user_id='owner', project_id='project', locale='en-AU', lane_id='lane', token='token',
        base_revision=0, policy_epoch=1, coverage_round=5, sources=[source], events=[event], previous=None,
        source_manifest=[dict(id='original', version=1)], event_manifest=[dict(id='childhood', revision=1)])
    phases = []
    checkpoints = {}

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return deepcopy(checkpoints.get(payload['p_key']))
            checkpoints[payload['p_key']] = deepcopy(payload['p_value'])

    async def provider(runtime, storage, project, locale, phase, packet):
        phases.append(phase)
        if phase == 'prepare':
            return dict(event_id=event['id'], context=source['text'], source_refs=event['source_refs'])
        if phase == 'draft':
            return controlled_draft(packet, source['text'], 'Childhood')
        return controlled_review(packet)

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    first = asyncio.run(compose_shared_snapshot(job, worker))
    first['review'] = dict(ready_for_user_review=True, publication_approved=False, findings=[])
    phases.clear()
    second = asyncio.run(compose_shared_snapshot({**job, 'base_revision':1, 'previous':first}, worker))
    assert second['status'] == 'ready'
    assert phases == ['review']
    assert second['review']['contract_version'] == 3
    assert second['manuscript']['chapters'][0]['blocks'] == first['manuscript']['chapters'][0]['blocks']
    assert second['draft']['expected_manuscript_revision'] == 1
    assert second['draft']['input_snapshot_id'] == second['request']['snapshot']['id']
