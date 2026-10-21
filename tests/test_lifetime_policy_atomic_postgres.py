"""Fixed model proposals through real SQL policy gates; no language classifier."""
import json
import pytest
from test_agent_commit_postgres import database, as_user, OWNER, OTHER, OLD
from test_guest_conversation_transfer import attachment_database
from test_private_rounds_postgres import private_database
from test_shared_memory_events_postgres import event_database, rpc, literal
from test_lifetime_memory_postgres import sql, resolve

TURN = '00000000-0000-4000-8000-000000000701'


def accept(sql, identity, text, turn=TURN, check=True):
    result = sql(as_user(f"select public.accept_user_interview_turn({literal(identity['project_id'])},'{turn}',{literal(text)});"), check=check)
    return json.loads(result.stdout.strip()) if check else result


def status(sql, identity):
    return rpc(sql, 'read_lifetime_policy_status', f"'{identity['conversation_id']}'")


def begin_review(sql, identity):
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    return rpc(sql, 'capture_lifetime_fence', f"'{identity['conversation_id']}','{OLD}'")


def complete(sql, fence, source, restrictions=(), *, check=True, done=True):
    proposal = {'complete': done, 'restrictions': list(restrictions)}
    return sql(f"set role service_role; select public.complete_lifetime_policy_review({literal(fence)}::jsonb,'{source['id']}',{source['version']},{literal(proposal)}::jsonb,'{{\"response_id\":\"controlled-policy-response\"}}'); reset role;", check=check)


def restriction(text, kind='excluded_topic'):
    return dict(kind=kind, quote=text, char_start=0, char_end=len(text))


def test_acceptance_is_durable_but_private_work_waits_for_completed_review(sql):
    identity = resolve(sql)
    source = accept(sql, identity, 'An original statement.')['source']
    assert status(sql, identity)['pending'] is True
    fence = begin_review(sql, identity)
    assert rpc(sql, 'read_lifetime_policy_review', f'{literal(fence)}::jsonb')['id'] == source['id']
    blocked = rpc(sql, 'lock_lifetime_publication', f'{literal(fence)}::jsonb', check=False)
    assert blocked.returncode != 0
    complete(sql, fence, source)
    assert status(sql, identity)['pending'] is False
    rpc(sql, 'lock_lifetime_publication', f'{literal(fence)}::jsonb')


def test_restrictive_fixed_proposal_commits_exact_source_evidence_atomically(sql):
    identity = resolve(sql)
    text = 'I would rather keep the kitchen out of our conversations.'
    source = accept(sql, identity, text)['source']; fence = begin_review(sql, identity)
    complete(sql, fence, source, [restriction(text)])
    rows = json.loads(sql('select json_agg(data) from public.user_lifetime_continuity;').stdout)
    assert len(rows) == 1
    assert rows[0]['text'] == text and rows[0]['source_refs'][0]['quote'] == text
    assert status(sql, identity)['pending'] is False
    # Replaying acceptance does not duplicate or remove a completed restriction.
    assert accept(sql, identity, text)['source']['id'] == source['id']
    assert sql('select count(*) from public.user_lifetime_continuity;').stdout.strip() == '1'


@pytest.mark.parametrize('fault', ['incomplete', 'span', 'kind', 'count', 'type', 'duplicate'])
def test_invalid_review_rolls_back_every_write_and_keeps_pending(sql, fault):
    identity = resolve(sql); text = 'An exact source.'
    source = accept(sql, identity, text)['source']; fence = begin_review(sql, identity)
    rows = [restriction(text)]
    if fault == 'span': rows[0]['char_end'] -= 1
    if fault == 'kind': rows[0]['kind'] = 'allow_sharing'
    if fault == 'count': rows *= 9
    if fault == 'type': rows[0]['char_start'] = '0'
    if fault == 'duplicate': rows *= 2
    result = complete(sql, fence, source, rows, check=False, done=fault != 'incomplete')
    assert result.returncode != 0
    assert status(sql, identity)['pending'] is True
    assert sql('select count(*) from public.user_lifetime_continuity;').stdout.strip() == '0'
    assert sql('select count(*) from public.user_lifetime_source_policy_receipt;').stdout.strip() == '0'


def test_authenticated_clients_cannot_certify_their_own_review(sql):
    identity = resolve(sql); source = accept(sql, identity, 'An original.')['source']; fence = begin_review(sql, identity)
    result = rpc(sql, 'complete_lifetime_policy_review', f"{literal(fence)}::jsonb,'{source['id']}',1,'{{\"complete\":true,\"restrictions\":[]}}','{{\"response_id\":\"forged\"}}'", check=False)
    assert result.returncode != 0 and 'permission denied' in result.stderr
    assert status(sql, identity)['pending'] is True


def test_current_source_review_never_reads_older_private_context(sql):
    identity = resolve(sql); source = accept(sql, identity, 'Only this pending source.')['source']; fence = begin_review(sql, identity)
    result = rpc(sql, 'read_lifetime_policy_review', f'{literal(fence)}::jsonb')
    assert result.pop('interview_language') is None
    assert result == source
    forged = {**fence, 'source_revision': fence['source_revision'] + 1}
    result = rpc(sql, 'lock_lifetime_policy_review', f'{literal(forged)}::jsonb', check=False)
    assert result.returncode != 0


def test_exactly_eight_distinct_fixed_controls_commit_together(sql):
    identity=resolve(sql);text=' '.join(f'Clause {n}.' for n in range(8))
    source=accept(sql,identity,text)['source'];fence=begin_review(sql,identity)
    controls=[]
    for n in range(8):
        quote=f'Clause {n}.';start=text.index(quote)
        controls.append(dict(kind='excluded_topic',quote=quote,char_start=start,char_end=start+len(quote)))
    complete(sql,fence,source,controls)
    assert status(sql,identity)['pending'] is False
    assert sql('select count(*) from public.user_lifetime_continuity;').stdout.strip()=='8'
