"""Mira's current reply rejects retired pool and worker-handoff contracts."""
from copy import deepcopy

from jsonschema import validate, ValidationError
import pytest

from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
from test_conversation_reply import proposal, reply_context


@pytest.mark.parametrize('field,value', [
    ('hint', None), ('deferred_hints', []), ('resolved_questions', []),
    ('work', {'mode': 'reply_only', 'name': None}), ('selected_candidate_id', None),
    ('strategy_proposal', {'strategy': 'shape'}),
])
def test_retired_fields_are_rejected_instead_of_silently_adapted(field, value):
    context = reply_context()
    raw = {**proposal(), field: value}
    with pytest.raises(ValidationError):
        validate(raw, governed_collector_schema(context))
    with pytest.raises(ValueError):
        validate_governed_collector_result(raw, context)


@pytest.mark.parametrize('reason', ['prepared_candidate', 'adapted_candidate'])
def test_reply_has_no_prepared_question_selection_reason(reason):
    with pytest.raises(ValueError):
        validate_governed_collector_result({**proposal(), 'reason': reason}, reply_context())


def hint(ctx, identity, *, confirmation=False):
    source = ctx['source']
    return dict(id='bq-' + identity * 64, question='What changed after that?',
        topic='move', quote=source['text'], source_id=source['id'], source_version=source['version'],
        char_start=0, char_end=len(source['text']), requires_confirmation=confirmation)


def photo_context():
    ctx = reply_context('I recognise this gate in the photo from our childhood visits.')
    ctx['photo_context'] = [dict(photo_id='reference:gate', kind='public_reference', title='Gate')]
    association = dict(photo_id='reference:gate', event_id=None, source_id=ctx['source']['id'],
        source_version=ctx['source']['version'], quote=ctx['source']['text'],
        description='The narrator recognises the gate from childhood visits.', provenance='narrator_metadata')
    return ctx, {**proposal(), 'associations': [association], 'response_photo_ids': ['reference:gate']}


def test_available_photo_identification_reaches_the_existing_validated_association_contract():
    ctx, raw = photo_context()
    before = deepcopy(raw)
    validate(raw, governed_collector_schema(ctx))
    result = validate_governed_collector_result(raw, ctx)
    assert result['associations'] == raw['associations']
    assert result['response_photos'][0]['photo_id'] == 'reference:gate'
    assert raw == before


@pytest.mark.parametrize('fault', ['foreign_photo', 'foreign_source', 'fabricated_quote'])
def test_conditional_photo_fields_keep_existing_evidence_checks(fault):
    ctx, raw = photo_context()
    association = raw['associations'][0]
    if fault == 'foreign_photo':
        association['photo_id'] = 'another-project-photo'
    elif fault == 'foreign_source':
        association['source_id'] = 'another-project-source'
    else:
        association['quote'] = 'The model invented this identification.'
    with pytest.raises(ValueError):
        validate_governed_collector_result(raw, ctx)
