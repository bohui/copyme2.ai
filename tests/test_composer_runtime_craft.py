"""Advisory craft inside the real canonical review path, with controlled models."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from apps.api.canonical_composer import compose_shared_snapshot
from controlled_composer_review import controlled_review
from test_canonical_composer_provenance import controlled_draft
from test_composer_review_regressions import unchanged_job


CRITERIA = ('focus', 'scene_craft', 'voice', 'supported_vulnerability',
    'retrospective_reflection', 'transformation', 'reader_resonance', 'fairness')


def craft_report(requirements, *, score=0):
    original = requirements['contributions'][0]
    unit = next(row for row in requirements['prose'] if row['field'] == 'text')
    return dict(rubric_id='memoir-craft-v1', ratings=[dict(criterion=criterion,
        applicability='applicable', score=score, confidence='high',
        confidence_basis='Controlled exact-original and prose fixture.',
        reason='Controlled advisory scalar, not independent semantic acceptance.',
        source_evidence=[dict(source_ref=deepcopy(original['source_ref']), excerpt=original['quote'])],
        prose_evidence=[{key:deepcopy(unit[key]) for key in ('section_id','field','excerpt')}],
        suggested_follow_up=None) for criterion in CRITERIA])


def test_low_craft_scores_are_advisory_and_do_not_redraft_supported_prose(monkeypatch):
    job = unchanged_job()
    phases, checkpoints, packets = [], {}, []

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return deepcopy(checkpoints.get(payload['p_key']))
            checkpoints[payload['p_key']] = deepcopy(payload['p_value'])
            return True

    async def provider(runtime, storage, project, locale, phase, packet):
        phases.append(phase)
        if phase == 'prepare':
            return dict(event_id='childhood', context=job['sources'][0]['text'], source_refs=job['events'][0]['source_refs'])
        if phase == 'draft':
            return controlled_draft(packet, job['sources'][0]['text'], 'Childhood')
        packets.append(deepcopy(packet))
        result = controlled_review(packet)
        result.update(contract_version=3, craft=craft_report(packet['requirements']))
        return result

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    result = asyncio.run(compose_shared_snapshot(job, worker))
    assert result['status'] == 'ready'
    assert phases == ['prepare','draft','review']
    assert result['review']['contract_version'] == 3
    assert [item['score'] for item in result['review']['craft']['ratings']] == [0]*8
    assert result['manuscript']['chapters'][0]['blocks'][0]['text'] == 'I grew up in Chengde.'
    assert result['draft']['questions_for_mira'] == []
    assert packets[0]['requirements']['craft_context']['stage'] == 'partial'
    assert any(value.get('review', {}).get('craft') == result['review']['craft'] for value in checkpoints.values())


def test_craft_metadata_repair_reuses_the_draft_and_its_evidence(monkeypatch):
    job = unchanged_job()
    phases, checkpoints, review_packets = [], {}, []

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
            return controlled_draft(packet, job['sources'][0]['text'], 'Childhood')
        review_packets.append(deepcopy(packet))
        review = controlled_review(packet)
        review.update(contract_version=3, craft=craft_report(packet['requirements']))
        if len(review_packets) == 1:
            review['craft']['ratings'][0]['source_evidence'][0]['excerpt'] = 'An invented original.'
        return review

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    result = asyncio.run(compose_shared_snapshot(job, worker))
    assert result['status'] == 'ready'
    assert phases == ['prepare','draft','review','review']
    assert review_packets[1]['candidate'] == review_packets[0]['candidate']
    assert review_packets[1]['review_errors'] == ['CRAFT_SOURCE_MISMATCH']
    assert review_packets[1]['review']['craft']['ratings'][0]['source_evidence'][0]['excerpt'] == 'An invented original.'


CRAFT_FAULTS = ('missing_criterion','duplicate_criterion','boolean_score','high_score','null_score',
    'scored_na','blank_source','foreign_source','wrong_prose','forbidden_followup','aggregate')


def corrupt_craft(report, fault):
    rating = report['ratings'][0]
    if fault == 'missing_criterion':
        report['ratings'].pop()
    elif fault == 'duplicate_criterion':
        report['ratings'][-1] = deepcopy(rating)
    elif fault == 'boolean_score':
        rating['score'] = True
    elif fault == 'high_score':
        rating['score'] = 4
    elif fault == 'null_score':
        rating['score'] = None
    elif fault == 'scored_na':
        rating['applicability'] = 'not_applicable'
    elif fault == 'blank_source':
        rating['source_evidence'][0]['excerpt'] = '\u3000'
    elif fault == 'foreign_source':
        rating['source_evidence'][0]['source_ref']['version'] = '99'
    elif fault == 'wrong_prose':
        rating['prose_evidence'][0]['excerpt'] = 'A phrase absent from this writing.'
    elif fault == 'forbidden_followup':
        rating.update(applicability='insufficient_evidence',score=None,
            suggested_follow_up='Tell me your private regrets and family conflict.')
    else:
        report['aggregate'] = 24


@pytest.mark.parametrize('fault', CRAFT_FAULTS)
def test_invalid_craft_metadata_never_redrafts_or_bypasses_refusal(monkeypatch, fault):
    job = unchanged_job()
    job['editorial_request'] = dict(follow_ups_allowed=False,
        instruction='Do not ask about private regrets or family conflict.')
    phases, checkpoints = [], {}

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
            return controlled_draft(packet, job['sources'][0]['text'], 'Childhood')
        assert packet['requirements']['craft_context']['followups_allowed'] is False
        review = controlled_review(packet)
        review['craft'] = craft_report(packet['requirements'])
        corrupt_craft(review['craft'], fault)
        return review

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    with pytest.raises(RuntimeError, match='another composition review'):
        asyncio.run(compose_shared_snapshot(job, worker))
    assert phases == ['prepare','draft','review','review','review']
    assert any(value.get('draft', {}).get('chapters', [{}])[0].get('blocks', [{}])[0].get('text') == 'I grew up in Chengde.'
        for value in checkpoints.values() if value.get('draft'))


def test_host_permitted_suggestion_stays_private_and_does_not_become_an_interview(monkeypatch):
    from apps.api.canonical_composer import composer_request
    from apps.api.memoir_preview import compose_candidate
    request = composer_request(unchanged_job())
    request['policy']['max_followup_questions'] = 1
    checkpoint, phases = {}, []
    question = 'If you wish, what would you like to add about that time?'

    async def progress(phase):
        checkpoint['phase'] = phase

    async def provider(runtime, storage, project, locale, phase, packet):
        phases.append(phase)
        if phase == 'draft':
            return controlled_draft(packet, 'I grew up in Chengde.', 'Childhood')
        review = controlled_review(packet)
        rating = review['craft']['ratings'][0]
        rating['suggested_follow_up'] = question
        assert packet['requirements']['craft_context']['followups_allowed'] is True
        return review

    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    result = asyncio.run(compose_candidate(request,SimpleNamespace(),SimpleNamespace(),'project','en-AU',
        checkpoint=checkpoint,progress=progress))
    assert result['status'] == 'ready' and phases == ['draft','review']
    assert result['review']['craft']['ratings'][0]['suggested_follow_up'] == question
    assert result['draft']['questions_for_mira'] == [] and question not in result['preview']['text']
