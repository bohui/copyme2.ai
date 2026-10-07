"""Exercise canonical composition with only the external model controlled.

The application prepares, validates, reviews and renders the returned bundle;
checkpoint RPCs are a task-local substitute for the separately tested database.
"""
import asyncio
import copy
import json
import os
from types import SimpleNamespace

import httpx
import pytest

from apps.api.canonical_composer import compose_shared_snapshot, fingerprint
from apps.api.memory_events import validate_extraction


@pytest.mark.parametrize('locale,quote,veto,title', [
    ('en-AU', 'I bought a house in 1980.', 'Please do not add this event to my timeline.', 'My home'),
    ('zh-CN', '我在1980年买了一栋房子。', '请不要把这个事件加入我的时间线。', '我的家'),
])
@pytest.mark.parametrize('span_kind,legacy_action', [('absent', 'replace')] + [
    (span, action) for span in ('exact', 'oversized')
    for action in ('replace', 'carry_once', 'carry_always', 'inline_once', 'inline_always',
                   'storyline_once', 'storyline_always', 'unscoped_once', 'unscoped_always')
])
def test_composed_evidence_keeps_the_authorised_occurrence(locale, quote, veto, title, span_kind, legacy_action):
    # The same words may refer to distinct events. Only the second occurrence
    # is authorised here; substring search must not point back to the vetoed one.
    prefix = quote + ' ' + veto + ' ' if span_kind != 'absent' else ''
    text = prefix + quote
    ref = {'source_id': 'original', 'version': 1, 'quote': quote}
    if span_kind != 'absent':
        # Earlier Python/SQL evidence checks accepted a suffix with an oversized
        # end because both substring operations clamp at the source boundary.
        ref.update(char_start=len(prefix), char_end=999 if span_kind == 'oversized' else len(text))
    source = {'id': 'original', 'project_id': 'project', 'kind': 'narrator_chat',
              'author_role': 'storyteller', 'status': 'active', 'sequence': 1,
              'version': 1, 'text': text}
    approved = validate_extraction({'events': [
        {'kind': 'event', 'title': title, 'source_refs': [ref]}
    ]}, [source], [])
    assert len(approved) == 1
    event = {**approved[0], 'id': 'canonical-home', 'revision': 1,
             'life_stage': 'unplaced', 'status': 'active'}
    job = {'user_id': 'synthetic-owner', 'project_id': 'project', 'locale': locale,
           'lane_id': 'synthetic-lane', 'token': 'synthetic-token',
           'base_revision': 0, 'policy_epoch': 0, 'coverage_round': 5,
           'sources': [source], 'events': [event], 'previous': None,
           'source_manifest': [{'id': source['id'], 'version': 1}],
           'event_manifest': [{'id': event['id'], 'revision': 1}]}
    before = copy.deepcopy(job)
    checkpoint = {}
    observed_phases = []
    carry_attempts = []

    class Checkpoints:
        async def rpc(self, name, **payload):
            if name == 'read_memoir_checkpoint':
                return copy.deepcopy(checkpoint.get(payload['p_key']))
            assert name == 'save_memoir_checkpoint'
            checkpoint[payload['p_key']] = copy.deepcopy(payload['p_value'])

    def controlled_model(request):
        payload = json.loads(request.content)
        phase, packet = payload['composer_phase'], json.loads(payload['text'])
        observed_phases.append(phase)
        if phase == 'prepare':
            partition = packet['partition']
            result = {'event_id': partition['id'], 'context': title,
                      'source_refs': partition['source_refs']}
        elif phase == 'review':
            result = {'ready_for_user_review': True, 'publication_approved': False, 'findings': []}
        else:
            assert phase == 'draft'  # A canonical composer never re-extracts events.
            result = controlled_draft(packet, quote, title)
            if packet['request']['prior_state']['revision'] and legacy_action != 'replace':
                if legacy_action.endswith('_always') or not carry_attempts:
                    carry_attempts.append(True)
                    if legacy_action.startswith('carry_'):
                        result['chapters'] = []
                        result['carry_forward_chapter_ids'] = ['home-chapter']
                    elif legacy_action.startswith('inline_'):
                        result['chapters'] = [copy.deepcopy(packet['request']['prior_state']['chapters'][0]['chapter'])]
                        result['chapters'][0].update(base_revision=packet['request']['prior_state']['revision'], change_type='enrich')
                    else:
                        body = result['storyline'] if legacy_action.startswith('storyline_') else result['chapters'][0]
                        bad_refs = [{'source_id': source['id'], 'version': '1'}]
                        if legacy_action.startswith('storyline_'):
                            bad_refs[0].update(char_start=0, char_end=len(quote))
                        body['source_refs'] = bad_refs
                        body['blocks'][0]['source_refs'] = bad_refs
        return httpx.Response(200, json={'reply': json.dumps(result, ensure_ascii=False)})

    worker = SimpleNamespace(broker=Checkpoints(), worker_url='http://controlled-model.invalid',
        worker_secret='synthetic', worker_transport=httpx.MockTransport(controlled_model))
    bundle = asyncio.run(compose_shared_snapshot(job, worker))
    assert bundle['status'] == 'ready'
    assert bundle['preview']['text'] == quote
    assert bundle['preview']['locale'] == locale
    passage = next(section for section in bundle['sections'] if 'block' in section)
    assert passage['event_ids'] == [event['id']]
    assert passage['source_refs'] == [{'source_id': source['id'], 'version': '1',
        'char_start': len(prefix), 'char_end': len(text)}]
    assert bundle['request']['events'][0]['source_refs'] == passage['source_refs']
    assert observed_phases == ['prepare', 'draft', 'review']
    assert job == before

    if span_kind != 'absent':
        # An existing v1 checkpoint may already contain the wrong occurrence.
        # The projection contract change must invalidate those cached bundles.
        legacy = copy.deepcopy(bundle)
        def reset_spans(value):
            if isinstance(value, dict):
                if 'source_id' in value and 'char_start' in value:
                    value.update(char_start=0, char_end=len(quote))
                for child in value.values():
                    reset_spans(child)
            elif isinstance(value, list):
                for child in value:
                    reset_spans(child)
        reset_spans(legacy)
        legacy['content_config'] = fingerprint({'locale': locale, 'skill': 'shared-composer-1',
            'model': os.getenv('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL', os.getenv('MEMORY_SPARK_LLM_MODEL', 'gpt-5.6-luna-pooled')),
            'policy': bundle['request']['policy']})
        observed_phases.clear()
        if legacy_action.startswith('storyline_'):
            legacy['manuscript']['kind'] = 'sample_storyline'
            legacy['manuscript']['storyline'] = {key: legacy['manuscript']['chapters'][0][key]
                for key in ('title', 'source_refs', 'event_ids', 'blocks')}
            legacy['manuscript']['chapters'] = []
        updated_job = {**job, 'base_revision': 1, 'previous': legacy}
        if legacy_action.endswith('_always'):
            with pytest.raises(RuntimeError, match='another composition review'):
                asyncio.run(compose_shared_snapshot(updated_job, worker))
            assert 'review' not in observed_phases
            assert legacy['sections'][0]['source_refs'][0]['char_start'] == 0
            return
        repaired = asyncio.run(compose_shared_snapshot(updated_job, worker))
        assert observed_phases[-1] == 'review'
        if legacy_action.endswith('_once'):
            assert observed_phases.count('draft') == 2
        assert repaired['sections'][0]['source_refs'] == passage['source_refs']
        assert repaired['content_config'] != legacy['content_config']
        # Once repaired, an unchanged checkpoint still reuses exact bytes.
        observed_phases.clear()
        unchanged = asyncio.run(compose_shared_snapshot(
            {**job, 'base_revision': 2, 'previous': repaired}, worker))
        assert unchanged == {**repaired, 'unchanged': True}
        assert observed_phases == []


def controlled_draft(packet, prose, title):
    request, plan = packet['request'], packet['plan']
    event = request['events'][0]
    refs, ids, periods = event['source_refs'], [event['id']], [event['period_id']]
    chapter_id = 'home-chapter'
    base_revision = request['prior_state']['revision']
    chapter = {'id': chapter_id, 'base_revision': base_revision, 'title': title, 'subtitle': '',
        'period_ids': periods, 'event_ids': ids, 'source_refs': refs,
        'blocks': [{'id': 'home-passage', 'type': 'paragraph', 'text': prose,
            'asset_id': None, 'asset_version': None, 'caption': '', 'alt': '', 'credit': '',
            'source_refs': refs, 'uncertainty': []}],
        'change_type': 'enrich' if base_revision else 'create', 'update_reason': 'Original narrator evidence.'}
    storyline = plan['kind'] == 'sample_storyline'
    return {'schema_version': '1.0', 'project_id': request['project_id'],
        'input_snapshot_id': plan['input_snapshot_id'], 'input_fingerprint': plan['input_fingerprint'],
        'expected_manuscript_revision': plan['expected_manuscript_revision'],
        'kind': plan['kind'], 'status': 'draft', 'title': title, 'title_source_refs': refs,
        'counter': plan['counter'],
        'source_summary': [{'id': 'home-summary', 'text': prose, 'source_refs': refs,
                            'event_ids': ids, 'uncertainty': []}],
        'outline': [{'chapter_id': chapter_id, 'order': 0, 'title': title,
            'period_ids': periods, 'event_ids': ids, 'status': 'planned' if storyline else 'draft',
            'rationale': 'A supported episode.', 'source_refs': refs}],
        'chapters': [] if storyline else [chapter],
        'storyline': {key: chapter[key] for key in ('title', 'source_refs', 'event_ids', 'blocks')}
            if storyline else {'title': '', 'source_refs': [], 'event_ids': [], 'blocks': []},
        'carry_forward_chapter_ids': [], 'retired_chapter_ids': [], 'proposed_replacements': [],
        'event_dispositions': [{'event_id': event['id'], 'disposition': 'included',
            'chapter_ids': [] if storyline else [chapter_id], 'reason': 'Original evidence.'}],
        'questions_for_mira': [], 'review_flags': [], 'next_action': 'review_preview'}
