"""Privacy fixtures must reach SQL and exclude previous assistant input."""
import asyncio
from copy import deepcopy
import json
import shutil

import pytest

from scripts import issue53_profile_sequences as profile
from scripts.issue53_sequence_application import controlled_sequences


@pytest.fixture(scope='module')
def privacy_sequences(tmp_path_factory):
    folder = tmp_path_factory.mktemp('issue53-privacy')
    planned = profile.plan(scenario=['issue53/switch-skip/' + locale for locale in ('en-AU', 'zh-CN')],
                           max_skill_calls=16)
    rows, journal = asyncio.run(controlled_sequences(planned, folder))
    return planned, rows, journal, folder


def test_privacy_controls_are_explicit_bilingual_fixture_data():
    cases = [s for s in profile.load_manifest()['scenarios'] if s['family'] == 'switch-skip']
    assert {s['locale'] for s in cases} == {'en-AU', 'zh-CN'}
    for case in cases:
        step = next(s for s in case['steps'] if s['id'] == 'turn-2')
        assert len(step['policy_controls']) == 1
        control = step['policy_controls'][0]
        assert control['kind'] == 'excluded_topic'
        assert step['text'].count(control['quote']) == 1


def test_privacy_fixture_reaches_sql_and_filters_governed_history(privacy_sequences):
    planned, rows, journal, folder = privacy_sequences
    report = profile.compare(planned, rows, journal, {}, directory=folder)
    assert all(r['execution'] == 'completed' for r in rows)
    assert all(r['contracts']['status'] == 'pass' for r in report['rows'])
    for row in planned['rows']:
        if row['step_id'] != 'turn-2':
            continue
        capture = journal['rows'][row['row_id']]
        packet = capture['packet_readbacks'][-1]
        assert packet['tail_readback']['complete'] is True
        assert not packet['tail_readback']['records'][0].get('conversation_saved', False)
        assert 'assistant' not in packet['tail'][0]
        assert capture['before']['replies'] == capture['after']['replies'][:-1]


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_resealed_empty_policy_review_fails_comparison(privacy_sequences, tmp_path, locale):
    planned, rows, journal, folder = privacy_sequences
    copied = tmp_path / 'changed'
    shutil.copytree(folder, copied)
    changed = deepcopy(journal)
    row = next(r for r in planned['rows'] if r['scenario_id'].endswith('/' + locale)
               and r['step_id'] == 'turn-2' and r['arm'] == 'candidate')
    capture = changed['rows'][row['row_id']]
    # Simulate the neutral fixture that previously passed all 80 row contracts.
    capture['after']['policy_reviews'] = []
    body = {k: v for k, v in capture.items()
            if k not in {'sequence_receipt_path', 'sequence_receipt_sha256'}}
    (copied / capture['sequence_receipt_path']).write_text(json.dumps(body))
    capture['sequence_receipt_sha256'] = profile.digest(body)
    report = profile.compare(planned, rows, changed, {}, directory=copied)
    actual = next(r for r in report['rows'] if r['row_id'] == row['row_id'])
    assert actual['contracts']['status'] == 'fail'
    assert actual['contracts']['reason'] == 'policy_control_readback_missing'
    assert report['latency']['overall']['matched_complete_pairs'] < len(planned['rows']) // 2


@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_self_consistent_retained_private_reply_fails_contract(privacy_sequences, locale):
    planned, rows, journal, folder = privacy_sequences
    row = next(r for r in planned['rows'] if r['scenario_id'].endswith('/' + locale)
               and r['step_id'] == 'turn-2' and r['arm'] == 'candidate')
    capture = deepcopy(journal['rows'][row['row_id']])
    prior = journal['rows'][row['row_id'].replace('turn-2', 'turn-1')]
    packet = capture['packet_readbacks'][-1]
    reply = capture['before']['replies'][0]['reply']
    packet['tail_readback']['records'][0].update(conversation_saved=True, assistant_reply=reply)
    packet['tail'][0]['assistant'] = {'text': reply}
    with pytest.raises(ValueError, match='privacy_tail_not_filtered'):
        profile._sequence(planned, row, capture, prior)
