"""Model work decisions survive retries at the real persistence boundary."""
import pytest

from test_interview_photos_postgres import (
    database, attachment_database, private_database, event_database, sql,
    rpc, literal, accept, as_user, OLD, TURN, upload,
)


def plan(mode='reply_only', name='韩凤江'):
    return {'candidates': [{'id': 'first-memory', 'question': '您最早记得的一段往事是什么？',
        'order': 0, 'bridge': '', 'context': {}}], 'chosen_id': 'first-memory',
        'active_event_id': None, 'work': {'mode': mode, 'name': name}}


def save(sql, value, *, check=True):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    return rpc(sql, 'save_user_interview_plan',
        f"'project','{TURN}',{literal(value)}::jsonb,'[]','{OLD}',"
        f"{literal('韩凤江，很高兴认识您。')},'[]','real-collector-thread'", check=check)


def test_work_decision_is_persisted_with_reply_and_retry_keeps_original(sql):
    accept(sql, '我叫韩凤江')
    original = save(sql, plan())
    assert original['plan']['work'] == {'mode': 'reply_only', 'name': '韩凤江'}
    restored = rpc(sql, 'read_user_interview_turn', f"'project','{TURN}'")
    assert restored['plan'] == original['plan'] and restored['reply'] == original['reply']
    retried = save(sql, plan('extract', None))
    assert retried['plan'] == original['plan'] and retried['thread_id'] == 'real-collector-thread'


@pytest.mark.parametrize('work', [
    {'mode': 'reply_only', 'name': 'Someone else'},
    {'mode': 'extract', 'name': '韩凤江'},
    {'mode': 'unknown', 'name': None},
    {'mode': 'reply_only', 'name': 123},
    {'mode': 'reply_only', 'name': '韩凤江', 'unexpected': True},
])
def test_invalid_or_ungrounded_work_is_rejected_atomically(sql, work):
    accept(sql, '我叫韩凤江')
    value = plan(); value['work'] = work
    assert save(sql, value, check=False).returncode != 0
    assert rpc(sql, 'read_user_interview_turn', f"'project','{TURN}'")['reply'] is None


def test_reply_only_cannot_discard_an_accepted_photo(sql):
    photo = upload(sql)
    accept(sql, '我叫韩凤江', photos=[photo['id']])
    assert save(sql, plan(), check=False).returncode != 0
    assert rpc(sql, 'read_user_interview_turn', f"'project','{TURN}'")['reply'] is None
