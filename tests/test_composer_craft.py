"""Controlled canonical replays of manual craft calibration, not craft scoring."""
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apps.api.canonical_composer import compose_shared_snapshot
from apps.api.lifetime_memory_policy import PolicyUnavailable
from controlled_composer_review import controlled_review
from test_canonical_composer_provenance import controlled_draft


CALIBRATION = json.loads((Path(__file__).parent / 'evaluation/memoir_composer_craft_cases.json').read_text())


@pytest.mark.parametrize('case', CALIBRATION['cases'], ids=lambda case: case['id'])
def test_craft_observations_cannot_override_evidence_or_privacy(monkeypatch, case):
    # These labels were authored with the synthetic examples. No model or
    # deterministic substring check establishes their semantic correctness.
    assert CALIBRATION['annotation_origin'] == 'agent_authored_pending_independent_semantic_review'
    source = case['source']
    for item in case['craft']:
        assert item['criterion'] in CALIBRATION['criteria']
        assert item['confidence'] in ('high', 'medium', 'low') and item['confidence_basis']
        assert all(excerpt and excerpt in source['text'] for excerpt in item['source_excerpts'])
        assert all(excerpt and excerpt in case['candidate']['text'] for excerpt in item['prose_excerpts'])
        assert all(excerpt and excerpt in json.dumps(case['author_intent'], ensure_ascii=False)
            for excerpt in item['intent_excerpts'])
        if item['applicability'] == 'applicable':
            assert type(item['score']) is int and 0 <= item['score'] <= 3
            assert item['source_excerpts'] and item['prose_excerpts']
        else:
            assert item['applicability'] in ('not_applicable', 'insufficient_evidence')
            assert item['score'] is None and item['reason']
    original = dict(id=source['id'], project_id='project', kind='narrator_chat', author_role='storyteller',
        status='active', sequence=1, version=source['version'], text=source['text'])
    event = dict(id='memory', revision=1, life_stage='unplaced', status='active', title=case['candidate']['title'],
        source_refs=[dict(source_id=source['id'], version=source['version'], char_start=0,
            char_end=len(source['text']), quote=source['text'])])
    job = dict(user_id='owner', project_id='project', locale=case['locale'], lane_id='lane', token='token',
        base_revision=0, policy_epoch=1, coverage_round=5, sources=[original], events=[event], previous=None,
        source_manifest=[dict(id=source['id'], version=source['version'])], event_manifest=[dict(id='memory', revision=1)],
        editorial_request=case['author_intent'])
    before = deepcopy(job)
    phases, checkpoints = [], {}

    class Broker:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return deepcopy(checkpoints.get(payload['p_key']))
            checkpoints[payload['p_key']] = deepcopy(payload['p_value'])
            return True

    async def provider(runtime, storage, project, locale, phase, packet):
        phases.append(phase)
        if phase == 'prepare':
            return dict(event_id='memory', context=source['text'], source_refs=event['source_refs'])
        assert packet['request']['context']['editorial_request'] == case['author_intent']
        if phase == 'draft':
            return controlled_draft(packet, case['candidate']['text'], case['candidate']['title'])
        if case['expected_gate'] == 'policy_pending':
            raise PolicyUnavailable()
        review = controlled_review(packet)
        if case['coverage_deferral']:
            for contribution in review['contributions']:
                contribution.update(disposition='deferred', prose=[], reason=case['coverage_deferral'])
        if case['expected_gate'] == 'pass':
            review['findings'] = [dict(verdict='editorial', severity='warning',
                explanation='Craft improvements remain optional and must use authorized evidence.')]
        else:
            # Deliberately contradictory ready/warning metadata must not clear
            # the controlled grounding defect, however polished the prose looks.
            review['findings'] = [dict(verdict=case['expected_gate'], severity='warning', explanation=case['gate_reason'])]
        return review

    monkeypatch.setattr('apps.api.canonical_composer.composer_call', provider)
    monkeypatch.setattr('apps.api.memoir_preview.composer_call', provider)
    worker = SimpleNamespace(broker=Broker(), worker_url='https://fixture.invalid', worker_secret='synthetic', worker_transport=None)
    if case['expected_gate'] == 'pass':
        result = asyncio.run(compose_shared_snapshot(job, worker))
        assert result['status'] == 'ready'
        assert result['manuscript']['chapters'][0]['blocks'][0]['text'] == case['candidate']['text']
        assert phases == ['prepare', 'draft', 'review']
    elif case['expected_gate'] == 'policy_pending':
        with pytest.raises(PolicyUnavailable):
            asyncio.run(compose_shared_snapshot(job, worker))
        assert phases == ['prepare', 'draft', 'review']
        assert any(value.get('phase') == 'reviewing' and value.get('draft') for value in checkpoints.values())
    else:
        with pytest.raises(RuntimeError, match='another composition review'):
            asyncio.run(compose_shared_snapshot(job, worker))
        assert phases == ['prepare'] + ['draft', 'review'] * 3
    assert job == before
