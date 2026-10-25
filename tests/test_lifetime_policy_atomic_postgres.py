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


@pytest.mark.parametrize('skill', ['timeline','composer'])
def test_last_completed_policy_review_wakes_only_the_waiting_lane(sql,skill):
    identity=resolve(sql)
    first=accept(sql,identity,'First original.')['source']
    # Raw acceptance retains reviews instead of the neutral seed RPC helper.
    second=json.loads(sql(as_user(f"select public.accept_user_narrator_source({literal(identity['project_id'])},"
        "'00000000-0000-4000-8000-000000000702','Second original.');")).stdout)
    fence=begin_review(sql,identity)
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,pending,error,available_at) "
        f"values('{OWNER}',{literal(identity['project_id'])},{literal(skill)},true,'LIFETIME_POLICY_PENDING',clock_timestamp()+interval '5 minutes');")
    original=sql('select jsonb_agg(to_jsonb(s) order by sequence) from public.user_narrator_source s;').stdout
    complete(sql,fence,first)
    assert sql("select available_at>clock_timestamp() from public.user_memoir_lane;").stdout.strip()=='t'
    assert rpc(sql,'lock_lifetime_publication',f'{literal(fence)}::jsonb',check=False).returncode!=0
    complete(sql,fence,second)
    assert sql("select pending and token is null and error is null and available_at<=clock_timestamp() from public.user_memoir_lane;").stdout.strip()=='t'
    assert sql('select jsonb_agg(to_jsonb(s) order by sequence) from public.user_narrator_source s;').stdout==original
    rpc(sql,'lock_lifetime_publication',f'{literal(fence)}::jsonb')


@pytest.mark.parametrize('state', ['active','other_error','not_pending','foreign'])
def test_completed_policy_review_does_not_disturb_other_lane_states(sql,state):
    identity=resolve(sql);source=accept(sql,identity,'An original.')['source'];fence=begin_review(sql,identity)
    queued=resolve(sql,owner=OTHER) if state=='foreign' else identity
    owner=OTHER if state=='foreign' else OWNER
    token=f"'{OLD}'" if state=='active' else 'null'
    error='MEMOIR_UNAVAILABLE' if state=='other_error' else 'LIFETIME_POLICY_PENDING'
    sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,pending,error,token,available_at) "
        f"values('{owner}',{literal(queued['project_id'])},'timeline',{str(state!='not_pending').lower()},{literal(error)},{token},clock_timestamp()+interval '5 minutes');")
    before=sql('select to_jsonb(l) from public.user_memoir_lane l;').stdout
    complete(sql,fence,source)
    assert sql('select to_jsonb(l) from public.user_memoir_lane l;').stdout==before


@pytest.mark.parametrize('review_complete', [False,True])
def test_policy_deferral_rechecks_review_that_may_have_finished_before_the_error_returned(sql,review_complete):
    identity=resolve(sql);source=accept(sql,identity,'An original.')['source'];fence=begin_review(sql,identity)
    lane=sql(f"insert into public.user_memoir_lane(user_id,project_id,skill,token,lease_until,run_deadline) "
        f"values('{OWNER}',{literal(identity['project_id'])},'timeline','{OLD}',clock_timestamp()+interval '1 minute',"
        "clock_timestamp()+interval '5 minutes') returning id;").stdout.strip()
    if review_complete:complete(sql,fence,source)
    sql(f"set role service_role; select public.defer_lifetime_memoir_lane_policy('{lane}','{OLD}','{OWNER}',"
        f"{literal(identity['project_id'])},'{identity['conversation_id']}'); reset role;")
    state=json.loads(sql("select jsonb_build_object('ready',available_at<=clock_timestamp(),'error',error,"
        "'released',token is null and lease_until is null and run_deadline is null,'pending',pending) from public.user_memoir_lane;").stdout)
    assert state==dict(ready=review_complete,error=None if review_complete else 'LIFETIME_POLICY_PENDING',released=True,pending=True)


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
