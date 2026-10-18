"""The live UI publisher cannot treat partial conversations as completed cases."""
from copy import deepcopy

import pytest

from scripts.run_memoir_game_ui_acceptance import ready_cases


def completed():
    return {'evaluation': {'cases': [dict(case_id='harbour-copper-notebook', user_email='test@test.com',
        status='completed', evidence_validated=True,
        rounds=[dict(round=n, status='completed', reply='A saved reply', accepted_source_id=f'original-{n}')
                for n in range(1, 51)], checkpoints=[{'milestone': n} for n in range(5, 51, 5)])]}}


def test_an_ongoing_campaign_cannot_authorize_ui_publication():
    receipt = completed()
    receipt['evaluation']['cases'][0]['status'] = 'running'
    assert ready_cases(receipt) == {}


@pytest.mark.parametrize('change', ['unsaved', 'missing_checkpoint', 'duplicate_source', 'wrong_owner'])
def test_completion_flag_cannot_hide_missing_evidence_or_a_changed_owner(change):
    receipt = deepcopy(completed())
    case = receipt['evaluation']['cases'][0]
    if change == 'unsaved': case['rounds'][-1]['status'] = 'submitting'
    elif change == 'missing_checkpoint': case['checkpoints'].pop()
    elif change == 'duplicate_source': case['rounds'][-1]['accepted_source_id'] = 'original-1'
    else: case['user_email'] = 'someone-else@example.invalid'
    with pytest.raises(ValueError): ready_cases(receipt)
