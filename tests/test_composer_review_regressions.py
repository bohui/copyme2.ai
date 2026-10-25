"""Review-only refresh and nonblank contribution witnesses at public seams."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.canonical_composer import compose_shared_snapshot
from controlled_composer_review import WHITESPACE_ONLY, controlled_review
from test_canonical_composer_provenance import controlled_draft


def unchanged_job():
    source = dict(id='original', project_id='project', kind='narrator_chat', author_role='storyteller',
        status='active', sequence=1, version=1, text='I grew up in Chengde.')
    event = dict(id='childhood', revision=1, life_stage='unplaced', status='active', title='Childhood',
        source_refs=[dict(source_id='original', version=1, char_start=0, char_end=21, quote=source['text'])])
    return dict(user_id='owner', project_id='project', locale='en-AU', lane_id='lane', token='token',
        base_revision=0, policy_epoch=1, coverage_round=5, sources=[source], events=[event], previous=None,
        source_manifest=[dict(id='original', version=1)], event_manifest=[dict(id='childhood', revision=1)])


@pytest.mark.parametrize('whitespace', WHITESPACE_ONLY)
@pytest.mark.parametrize('deferred', [False, True])
def test_contribution_needs_nonblank_prose_or_truthful_partial_deferral(monkeypatch, whitespace, deferred):
    job = unchanged_job()
    before = deepcopy(job)
    prose = 'I' + whitespace + 'grew up.'
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
            return dict(event_id='childhood', context=job['sources'][0]['text'], source_refs=job['events'][0]['source_refs'])
        if phase == 'draft':
            return controlled_draft(packet, prose, 'Childhood')
        review = controlled_review(packet)
        item, = review['contributions']
        if deferred:
            item.update(disposition='deferred', prose=[], reason='The passage says I grew up but omits the location Chengde.')
        else:
            item['prose'] = [dict(section_id='home-chapter__home-passage', field='text', excerpt=whitespace)]
        return review

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    if deferred:
        result = asyncio.run(compose_shared_snapshot(job, worker))
        assert result['manuscript']['chapters'][0]['blocks'][0]['text'] == prose
        assert result['review']['contributions'][0]['disposition'] == 'deferred'
        assert phases == ['prepare', 'draft', 'review']
    else:
        with pytest.raises(RuntimeError, match='another composition review'):
            asyncio.run(compose_shared_snapshot(job, worker))
        assert phases == ['prepare'] + ['draft', 'review'] * 3
    assert job == before


@pytest.mark.parametrize('change', ['unchanged', 'version_two', 'carried_delta', 'policy_epoch', 'source_edit', 'source_role',
    'withdraw', 'privacy_guard', 'semantic_repair', 'semantic_blocks'])
def test_completed_prose_refresh_respects_current_authority_and_bounded_repair(monkeypatch, change):
    from apps.api.lifetime_memory_policy import PolicyUnavailable
    job = unchanged_job()
    phases = []
    checkpoints = {}
    refreshing = False

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return deepcopy(checkpoints.get(payload['p_key']))
            checkpoints[payload['p_key']] = deepcopy(payload['p_value'])

    async def provider(runtime, storage, project, locale, phase, packet):
        phases.append(phase)
        if phase == 'prepare':
            return dict(event_id='childhood', context=packet['sources'][0]['text'], source_refs=packet['partition']['source_refs'])
        if phase == 'draft':
            return controlled_draft(packet, packet['request']['sources'][0]['text'], 'Childhood')
        if refreshing and change == 'privacy_guard':
            raise PolicyUnavailable()
        review = controlled_review(packet)
        if refreshing and change in ('semantic_repair', 'semantic_blocks') and (change == 'semantic_blocks' or phases.count('review') == 1):
            review['findings'] = [dict(verdict='unsupported', severity='warning', explanation='Controlled semantic rejection.')]
        if refreshing and change == 'policy_epoch':
            assert packet['request']['snapshot']['policy_epoch'] == 2
        if refreshing and change == 'source_role':
            assert packet['request']['sources'][0]['author_role'] == 'family'
        return review

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    previous = asyncio.run(compose_shared_snapshot(job, worker))
    if change not in ('policy_epoch', 'source_edit', 'source_role', 'withdraw'):
        if change == 'version_two':
            previous['review'].pop('craft')
            previous['review']['contract_version'] = 2
        else:
            previous['review'] = dict(ready_for_user_review=True, publication_approved=False, findings=[])
    if change == 'carried_delta':
        previous['draft'].update(chapters=[],
            carry_forward_chapter_ids=[chapter['id'] for chapter in previous['manuscript']['chapters']])
    saved = deepcopy(previous)
    old_checkpoints = deepcopy(checkpoints)
    current = {**deepcopy(job), 'base_revision': 1, 'previous': previous}
    if change == 'policy_epoch':
        current['policy_epoch'] = 2
    elif change == 'source_edit':
        current['sources'][0].update(version=2, text='I grew up in Sydney.')
        current['source_manifest'][0]['version'] = 2
        current['events'][0].update(revision=2, source_refs=[dict(source_id='original', version=2,
            quote='I grew up in Sydney.', char_start=0, char_end=20)])
        current['event_manifest'][0]['revision'] = 2
    elif change == 'source_role':
        current['sources'][0]['author_role'] = 'family'
    elif change == 'withdraw':
        current.update(sources=[], events=[], source_manifest=[], event_manifest=[])
    phases.clear()
    refreshing = True
    if change == 'privacy_guard':
        with pytest.raises(PolicyUnavailable):
            asyncio.run(compose_shared_snapshot(current, worker))
        assert phases == ['review']
        assert any(value.get('phase') == 'reviewing' and value.get('draft') for value in checkpoints.values())
    elif change == 'semantic_blocks':
        with pytest.raises(RuntimeError, match='another composition review'):
            asyncio.run(compose_shared_snapshot(current, worker))
        assert phases == ['review', 'draft', 'review', 'draft', 'review']
    else:
        result = asyncio.run(compose_shared_snapshot(current, worker))
        expected = {'unchanged':['review'], 'version_two':['review'], 'carried_delta':['review'], 'policy_epoch':['draft','review'],
            'source_edit':['prepare','draft','review'], 'source_role':['draft','review'],
            'withdraw':[], 'semantic_repair':['review','draft','review']}[change]
        assert phases == expected
        if change == 'withdraw':
            assert result['status'] == 'insufficient_context' and result['preview'] is None
        else:
            assert result['status'] == 'ready'
            if change != 'source_edit':
                assert result['manuscript']['chapters'][0]['blocks'] == saved['manuscript']['chapters'][0]['blocks']
            if change in ('unchanged', 'version_two', 'carried_delta'):
                assert result['draft']['event_dispositions'] == saved['draft']['event_dispositions']
                assert result['draft']['expected_manuscript_revision'] == 1
                assert result['draft']['input_snapshot_id'] == result['request']['snapshot']['id']
    assert previous == saved
    assert all(checkpoints[key] == value for key, value in old_checkpoints.items())
