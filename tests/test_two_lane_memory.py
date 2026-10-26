"""Issue 70: real local SQL, bounded fake provider, no paid dispatch."""
import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import httpx
import pytest

from apps.api.lifetime_memory_continuity import governed_collector_schema, validate_governed_collector_result
from test_name_only_opening import proposal
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database
from test_agent_commit_postgres import database as base_database, OWNER, OTHER, OLD, as_user
from test_shared_memory_events_postgres import rpc, literal
from split_lane_fixtures import service, publish_questions, canonical_service
from controlled_interview_guidance import choose_prepared


@pytest.fixture(scope='module')
def database():
    yield from base_database.__wrapped__(publication_tcp=True)


@pytest.fixture(autouse=True)
def enable_only_disposable_database_rollout(sql):
    # This fixture owns a fresh local PostgreSQL cluster. Never configure a
    # shared service, deploy a migration, or activate a production flag here.
    sql('update public.lifetime_two_lane_rollout set enabled=true,strategy_enabled=false,strategy_shadow=true;')


TEXT = 'I grew up in Hobart and walked by the river.'
PLACE = {'place':'Hobart','hierarchy':['Earth','Australia','Tasmania','Hobart'],
         'granularity':'city','latitude':None,'longitude':None}
QUESTION = {'question':'What do you remember about those walks?', 'topic':'river walks', 'quote':'walked by the river'}


def anchor_question(output, source, quote, start=None, end=None):
    evidence = {'source_id': source['id'], 'version': source['version'], 'quote': quote,
                'char_start': start, 'char_end': end, 'attribution': None}
    if 'plan' in output:
        output['plan']['candidates'][0]['context']['evidence'] = evidence
    else:
        output['question_evidence'] = evidence


def test_two_lane_extraction_includes_place_skill_without_conflicting_output_instruction():
    from apps.api.two_lane_memory import extraction_contract
    from apps.api.model_request import instruction_manifest
    instructions, schema = extraction_contract()
    sources = {item['name'] for item in instruction_manifest(instructions, schema)['artifacts']}
    assert {'memoir/skills/memoir-place-journey/extraction',
            'memoir/skills/memoir-author-timeline/derived-hints'} <= sources
    assert {'events', 'place_journeys'} <= set(schema['required'])
    assert not {'prepared_questions', 'strategy_proposal'} & schema['properties'].keys()


def test_extraction_diagnostic_names_schema_field_without_story_content():
    from pydantic import ValidationError
    from apps.api.lifetime_memory_composer import extraction_issue
    from apps.api.two_lane_memory import DerivedHints
    try:
        DerivedHints.model_validate({'place_journeys': [{'place': 'private story text'}],
                                     'prepared_questions': []})
    except ValidationError as error:
        issue = extraction_issue(error)
    assert issue.startswith('place_journeys.0.')
    assert 'private story text' not in issue
    assert extraction_issue(KeyError('place_journeys')) == 'missing_place_journeys'


def accept(sql, text=TEXT, project=None, turn=None):
    identity=rpc(sql,'resolve_lifetime_conversation',literal(project) if project else 'null')
    accepted=rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{turn or uuid4()}',{literal(text)}")
    return identity,accepted


def lane(sql, identity):
    # Acceptance atomically wakes the existing timeline lane even if the
    # separate composer receipt has not completed its bounded coverage scan.
    return sql(f"select id from public.user_memoir_lane where user_id='{OWNER}' and project_id={literal(identity['project_id'])} and skill='timeline';").stdout.strip()



def test_flag_is_off_and_foreground_optional_place_schema_is_removed_only_when_enabled(monkeypatch):
    from apps.api.two_lane_memory import two_lanes_enabled
    monkeypatch.delenv('MEMOIR_TWO_LANES',raising=False)
    assert not two_lanes_enabled()
    assert 'place_journeys' in governed_collector_schema()['required']
    context={'two_lane_memory':True,'source':{'id':str(uuid4()),'version':1,'text':TEXT,'status':'active'}}
    assert 'place_journeys' not in governed_collector_schema(context)['properties']
    output=proposal(mode='extract',name=None)
    output['place_journeys']=[{'bad':'optional data must not invalidate the public reply'}]
    assert validate_governed_collector_result(output,context)['place_journeys']==[]


def test_acceptance_is_idempotent_and_a_failed_reply_blocks_a_different_turn(sql):
    turn=str(uuid4())
    identity,accepted=accept(sql,turn=turn)
    again=rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{turn}',{literal(TEXT)}")
    assert again['source']['id']==accepted['source']['id']
    failed=rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{uuid4()}','another turn'",check=False)
    assert failed.returncode!=0
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_two_lane_source;').stdout.strip()=='1'


def test_background_places_and_candidates_use_separate_fenced_writers(sql):
    identity,accepted=accept(sql)
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['two_lane']['schema_version']==1
    assert page['source']['id']==accepted['source']['id']
    result={'events':[],'place_journeys':[{k:v for k,v in {**PLACE,'schema_version':1}.items() if v is not None}], 'prepared_questions':[QUESTION]}
    saved=service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',0,{literal(result)}")
    assert saved['status']=='page_saved'
    places=rpc(sql,'read_lifetime_place_journeys',literal(identity['project_id']))
    assert places[0]['place']=='Hobart'
    candidates=rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")
    assert candidates[0]['question']==QUESTION['question']
    assert candidates[0]['source_version']==1 and candidates[0]['source_id']==accepted['source']['id']
    assert candidates[0]['topic']=='river walks'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
    guided,generated=sql.guidance_publication
    replay=canonical_service(sql,'commit_lifetime_interview_guidance',
        f"'{guided['lane_id']}','{guided['token']}',{literal(guided['page_digest'])},{literal(generated)}")
    assert replay['replayed'] is True
    assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'",owner=OTHER,check=False).returncode!=0


def test_confirmations_rank_first_and_survive_the_ordinary_hint_expiry(sql):
    identity, accepted = accept(sql)
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    confirmation = {**QUESTION, 'question': 'Did you mean Hobart in Tasmania?', 'requires_confirmation': True}
    result = {'events': [], 'place_journeys': [], 'prepared_questions': [QUESTION, confirmation]}
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane_id}','{page['token']}',0,{literal(result)}")
    assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")[0]['requires_confirmation']
    for _ in range(3):
        rpc(sql, 'accept_user_narrator_source', f"{literal(identity['project_id'])},'{uuid4()}','I remember another walk.'")
    pending = rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
    assert [q['question'] for q in pending] == [confirmation['question']]
    rpc(sql, 'change_user_narrator_source',
        f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'withdraw',null")
    assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'") == []


def test_confirmation_from_an_earlier_source_window_stays_queued(sql):
    identity, _ = accept(sql, text=TEXT + ' More memories.' * 300)
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    question = {**QUESTION, 'requires_confirmation': True}
    from split_lane_fixtures import canonical_service, publish
    result = {'events': [], 'place_journeys': []}
    canonical_service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane_id}','{page['token']}',0,{literal(result)}")
    second = canonical_service(sql, 'read_lifetime_memoir_lane_page', f"'{lane_id}','{page['token']}'")
    assert second['source']['id'] == page['source']['id']
    assert second['source']['char_start'] > 0
    canonical_service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane_id}','{page['token']}',{second['page_number']},{literal(result)}")
    publish(sql, page, [question])
    pending = rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
    assert [q['question'] for q in pending] == [QUESTION['question']]


@pytest.mark.parametrize('strategy_selector', [False, True])
@pytest.mark.parametrize('paraphrased', [False, True])
def test_late_background_confirmation_does_not_repeat_an_answered_question(
        sql, tmp_path, monkeypatch, strategy_selector, paraphrased):
    from test_interview_strategy_runtime import client_fixture
    from test_interview_strategy import wire
    from controlled_collector import worker_reply

    confirmation = '您说的“林姨”，就是前面提到的陈小明的妈妈吗？'
    questions = [confirmation, '您说的“我们”具体是指哪些孩子？',
                 '您和陈小明、李小刚平时都玩些什么？']
    texts = ['小时候，陈小明的妈妈林姨会编小笼子，我们一起玩。', '是的',
             '有，8个孩子，我和陈小明、李小刚是最好的朋友。']
    calls = []

    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        question = questions[len(calls) - 1]
        if strategy_selector:
            output = wire(question=question, acknowledgement='明白了。',
                          selection_reason='latest_story', used_strategy='explore')
        else:
            output = proposal(mode='extract', name=None, question=question)
            output.update(acknowledgement='明白了。', selection_reason='latest_story')
        if len(calls) == 1:
            anchor_question(output, body['interview_context']['source'], texts[0])
        if paraphrased and len(calls) == 3:
            context = body['interview_context']
            answer = next(item['response'] for item in context['recent_dialogue']
                          if item['question']['text'] == confirmation)
            resolved = [{'question_id': context['prepared_questions'][0]['id'],
                'source_id': answer['id'], 'source_version': answer['version'],
                'char_start': 0, 'char_end': len(answer['text']), 'quote': answer['text']}]
            target = output if strategy_selector else output['plan']
            target['resolved_questions'] = resolved
        return worker_reply(request, {'reply': json.dumps(output, ensure_ascii=False),
                                      'thread_id': 'confirmation-replay', 'artifacts': []})

    client = client_fixture(sql, tmp_path, monkeypatch, provider)
    if not strategy_selector:
        monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY', '0')
        sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
    with client:
        first = client.post('/v1/agent/turn', json={'text': texts[0], 'language': 'zh-CN',
                                                 'client_turn_id': str(uuid4())})
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        payload = {'project_id': project, 'language': 'zh-CN'}
        second = client.post('/v1/agent/turn', json={**payload, 'text': texts[1],
                                                   'client_turn_id': str(uuid4())})
        assert second.status_code == 200, second.text
        assert second.json()['reply'].endswith(questions[1])
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(project))
        context = rpc(sql, 'read_lifetime_interview_context', f"'{identity['conversation_id']}'")
        exchange = next(item for item in context['recent_dialogue']
                        if item['question']['text'] == confirmation)
        assert exchange['question']['personal_testimony'] is False
        assert exchange['question']['delivered'] is True
        assert exchange['response']['text'] == '是的'
        assert exchange['response']['id'] == second.json()['accepted_source_id']
        assert exchange['status'] == 'responded'

        # Background extraction finishes after the narrator has already answered
        # the foreground question, so its source-derived ID is different.
        lane_id = lane(sql, identity)
        page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
        assert any(item['question']['text'] == confirmation and item['response']['text'] == '是的'
                   for item in page['attribution_context']['recent_dialogue'])
        result = {'events': [], 'place_journeys': [], 'prepared_questions': [{
            'question': '林姨是陈小明的母亲，对吗？' if paraphrased else confirmation, 'topic': '林姨的身份',
            'quote': page['source']['text'], 'requires_confirmation': True}]}
        if strategy_selector:
            result['strategy_proposal'] = {'strategy': 'shape', 'objective': 'clarify_identity',
                                           'focus_event_ids': []}
        service(sql, 'commit_lifetime_memoir_lane_page',
                f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")
        if not paraphrased:
            assert json.loads(sql('select questions from public.user_lifetime_prepared_question;').stdout or '[]') == []

        third = client.post('/v1/agent/turn', json={**payload, 'text': texts[2],
                                                  'client_turn_id': str(uuid4())})
        assert third.status_code == 200, third.text
        replies = [response.json()['reply'] for response in (first, second, third)]
        assert sum(confirmation in reply for reply in replies) == 1, replies
        assert replies[-1].endswith(questions[-1])
        assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'") == []
        assert json.loads(sql('select questions from public.user_lifetime_prepared_question;').stdout or '[]') == []
        if not paraphrased:
            assert calls[-1]['interview_context']['prepared_questions'] == []
        assert len(calls) == 3


def test_unasked_foreground_alternative_remains_an_eligible_confirmation(sql, tmp_path, monkeypatch):
    from test_interview_strategy_runtime import client_fixture
    from controlled_collector import worker_reply

    question = {**QUESTION, 'question': 'Did you mean Hobart in Tasmania?', 'requires_confirmation': True}
    output = proposal(mode='extract', name=None, question=QUESTION['question'])
    output['plan']['candidates'].append({**output['plan']['candidates'][0],
        'id': 'unasked-alternative', 'question': question['question'], 'order': 1})

    def provider(request):
        return worker_reply(request, {'reply': json.dumps(output), 'thread_id': 'unasked', 'artifacts': []})

    client = client_fixture(sql, tmp_path, monkeypatch, provider)
    monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY', '0')
    sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
    with client:
        response = client.post('/v1/agent/turn', json={'text': TEXT, 'client_turn_id': str(uuid4())})
        assert response.status_code == 200, response.text
        assert question['question'] not in response.json()['reply']
    identity = rpc(sql, 'resolve_lifetime_conversation', literal(response.json()['project_id']))
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    result = {'events': [], 'place_journeys': [], 'prepared_questions': [question]}
    service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")
    pending = rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
    assert [candidate['question'] for candidate in pending] == [question['question']]


@pytest.mark.parametrize('strategy_selector', [False, True])
@pytest.mark.parametrize('pending_before_delivery', [False, True])
def test_identical_clarification_wording_remains_available_for_a_different_memory(
        sql, tmp_path, monkeypatch, strategy_selector, pending_before_delivery):
    from test_interview_strategy_runtime import client_fixture
    from test_interview_strategy import wire
    from controlled_collector import worker_reply

    question = 'Who do you mean by “we”?'
    school_story = ('I would prefer to talk about school. ' if pending_before_delivery else '') + 'At school, we played cricket after class.'
    work_story = ('At work, we travelled together.' if pending_before_delivery else
                  'My classmates Ben and Mia. Years later at work, we travelled together.')
    calls = []

    def provider(request):
        context = json.loads(request.content)['interview_context']
        calls.append(context)
        pending = context['prepared_questions']
        school_turn = context['source']['text'] == school_story
        selected = pending[0] if pending and not school_turn else None
        wording = question if school_turn or selected else 'What stood out about those trips?'
        reason = ('user_redirect' if school_turn and pending_before_delivery else
                  'prepared_candidate' if selected else 'latest_story')
        if strategy_selector:
            output = wire(question=wording, selected_candidate_id=selected['id'] if selected else None,
                          selection_reason=reason)
        else:
            output = {**proposal(mode='extract', name=None, question=wording),
                      'selection_reason': 'latest_story' if selected else reason}
        if selected:
            choose_prepared(output,selected)
        if school_turn:
            anchor_question(output, context['source'], school_story)
        return worker_reply(request, {'reply': json.dumps(output), 'thread_id': 'different-groups', 'artifacts': []})

    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        if not strategy_selector:
            monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY', '0')
            sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
        first = client.post('/v1/agent/turn', json={'text': work_story if pending_before_delivery else school_story,
                                                 'client_turn_id': str(uuid4())})
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(project))
        lane_id = lane(sql, identity)

        def publish(page, topic):
            result = {'events': [], 'place_journeys': [], 'prepared_questions': [{
                'question': question, 'topic': topic, 'quote': page['source']['text'], 'requires_confirmation': True}]}
            if strategy_selector:
                result['strategy_proposal'] = {'strategy': 'explore', 'objective': 'follow_story', 'focus_event_ids': []}
            service(sql, 'commit_lifetime_memoir_lane_page',
                    f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")

        if pending_before_delivery:
            page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
            publish(page, 'work group')
        second = client.post('/v1/agent/turn', json={'project_id': project,
            'text': school_story if pending_before_delivery else work_story, 'client_turn_id': str(uuid4())})
        assert second.status_code == 200, second.text
        school, work = (second, first) if pending_before_delivery else (first, second)
        if not pending_before_delivery:
            page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
            publish(page, 'school group')
            assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'") == []
            publish_questions(sql,page,{work.json()['accepted_source_id']:[dict(question=question,topic='work group',quote=work_story,requires_confirmation=True)]},
                dict(strategy='explore',objective='follow_story',focus_event_ids=[]) if strategy_selector else None)

        pending = rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
        stored = json.loads(sql(f"select questions from public.user_lifetime_prepared_question "
            f"where source_id='{work.json()['accepted_source_id']}';").stdout)
        assert [item['question'] for item in stored] == [question]
        assert [(item['question'], item['source_id']) for item in pending] == [(question, work.json()['accepted_source_id'])]
        if strategy_selector:
            state = rpc(sql, 'read_lifetime_strategy_context', f"'{identity['conversation_id']}'")
            assert [item['question'] for item in state['plan']['candidates']] == [question]
        continued = client.post('/v1/agent/turn', json={'project_id': project,
            'text': 'At university, we joined a choir.', 'client_turn_id': str(uuid4())})
        assert continued.status_code == 200, continued.text
        assert school.json()['reply'].endswith(question) and continued.json()['reply'].endswith(question)
        assert calls[-1]['prepared_questions'][0]['source_id'] == work.json()['accepted_source_id']
        assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'") == []
        assert sql("select count(*) from public.user_lifetime_prepared_question where questions<>'[]'::jsonb;").stdout.strip() == '0'

        # The old work hint was delivered on the university turn. Its delivery
        # source must not become the identity of an unrelated university hint.
        pending_page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
        source_id=continued.json()['accepted_source_id']
        from split_lane_fixtures import publish as finish_and_publish
        finish_and_publish(sql,pending_page,[])
        publish_questions(sql,pending_page,{source_id:[dict(question=question,topic='university group',
            quote='At university, we joined a choir.',requires_confirmation=True)]})
        pending = rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
        assert [(item['question'], item['source_id']) for item in pending] == [(question, continued.json()['accepted_source_id'])]


@pytest.mark.parametrize('strategy_selector', [False, True])
@pytest.mark.parametrize('anchored', [False, True])
@pytest.mark.parametrize('repeated_quote', [False, True])
def test_same_message_clarifications_keep_their_referenced_passages(
        sql, tmp_path, monkeypatch, strategy_selector, anchored, repeated_quote):
    from test_interview_strategy_runtime import client_fixture
    from test_interview_strategy import wire
    from controlled_collector import worker_reply

    school = 'At school, we played cricket.'
    work = 'At work, we travelled together.'
    text = school + ' ' + work
    question = 'Who do you mean by “we”?'
    quotes = ['we', 'we'] if repeated_quote else [school, work]
    starts = [text.index(quotes[0]), len(school) + 1 + work.index(quotes[1])]
    def provider(request):
        output = (wire(question=question, selection_reason='latest_story') if strategy_selector else
                  {**proposal(mode='extract', name=None, question=question), 'selection_reason': 'latest_story'})
        if anchored:
            source = json.loads(request.content)['interview_context']['source']
            anchor_question(output, source, quotes[0], starts[0], starts[0] + len(quotes[0]))
        return worker_reply(request, {'reply': json.dumps(output), 'thread_id': 'two-passages', 'artifacts': []})
    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        if not strategy_selector:
            monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY', '0')
            sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
        response = client.post('/v1/agent/turn', json={'text': text, 'client_turn_id': str(uuid4())})
        assert response.status_code == 200, response.text
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(response.json()['project_id']))
        lane_id = lane(sql, identity)
        page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
        result = {'events': [], 'place_journeys': [], 'prepared_questions': [{
            'question': question, 'topic': topic, 'quote': quote, 'requires_confirmation': True,
            'char_start': start, 'char_end': start + len(quote)}
            for topic, quote, start in zip(('school group', 'work group'), quotes, starts)]}
        if strategy_selector:
            result['strategy_proposal'] = {'strategy': 'explore', 'objective': 'follow_story', 'focus_event_ids': []}
        service(sql, 'commit_lifetime_memoir_lane_page',
                f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")
        pending = rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
        expected = starts[1:] if anchored else starts
        assert [item['char_start'] for item in pending] == expected
        assert len({item['id'] for item in pending}) == len(expected)
        if strategy_selector:
            state = rpc(sql, 'read_lifetime_strategy_context', f"'{identity['conversation_id']}'")
            assert [item['char_start'] for item in state['plan']['candidates']] == expected


def test_database_cannot_retarget_a_hint_id_to_a_different_passage(sql):
    question = 'Who do you mean by we?'
    school, work = 'At school we played.', 'At work we travelled.'
    turn = str(uuid4())
    identity, accepted = accept(sql, text=school + ' ' + work, turn=turn)
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    result = {'events': [], 'place_journeys': [], 'prepared_questions': [
        {'question': question, 'topic': topic, 'quote': quote, 'requires_confirmation': True}
        for topic, quote in (('school', school), ('work', work))]}
    service(sql, 'commit_lifetime_memoir_lane_page', f"'{lane_id}','{page['token']}',0,{literal(result)}")
    pending = rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'")
    work_hint = next(item for item in pending if item['topic'] == 'work')
    evidence = {'source_id': accepted['source']['id'], 'version': 1,
                'quote': school, 'char_start': 0, 'char_end': len(school)}
    plan = {'candidates': [{'id': work_hint['id'], 'question': question, 'order': 0,
                           'bridge': '', 'context': {'evidence': evidence}}],
            'chosen_id': work_hint['id'], 'active_event_id': None}
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    def save(check=True):
        return rpc(sql, 'save_user_interview_plan', f"{literal(identity['project_id'])},'{turn}',"
            f"{literal(plan)},'[]','{OLD}',{literal(question)},'[]','passage-test'", check=check)
    rejected = save(check=False)
    assert rejected.returncode != 0 and 'cannot change its referenced passage' in rejected.stderr
    assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'") == pending
    evidence.update(quote=work, char_start=len(school) + 1, char_end=len(school) + 1 + len(work))
    assert save()['plan']['candidates'][0]['context']['evidence'] == evidence


@pytest.mark.parametrize('strategy_selector', [False, True])
@pytest.mark.parametrize('padding,streaming', [('',False),(' ',False),('\n',False),('\t\r\n',False),('\u00a0\u3000',False),(' \n\t',True)])
def test_whitespace_padded_confirmation_is_delivered_once(sql,tmp_path,monkeypatch,strategy_selector,padding,streaming):
    from test_interview_strategy_runtime import client_fixture
    from test_interview_strategy import wire
    question='Did you mean Hobart in Tasmania?'
    def provider(request):
        pending=json.loads(request.content)['interview_context']['prepared_questions']
        output=(wire(question=pending[0]['question'].strip() if pending else 'What happened next?',
                     selected_candidate_id=pending[0]['id'] if pending else None,
                     selection_reason='prepared_candidate' if pending else 'latest_story') if strategy_selector else
                {**proposal(mode='extract',name=None,question='What happened next?'),'selection_reason':'latest_story'})
        if pending:choose_prepared(output,pending[0])
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'whitespace-confirmation','artifacts':[]})
    with client_fixture(sql,tmp_path,monkeypatch,provider) as client:
        if not strategy_selector:
            monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY','0')
            sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
        first=client.post('/v1/agent/turn',json={'text':TEXT,'client_turn_id':str(uuid4())})
        assert first.status_code==200,first.text
        project=first.json()['project_id']
        identity=rpc(sql,'resolve_lifetime_conversation',literal(project))
        lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        result={'events':[],'place_journeys':[],'prepared_questions':[{'question':padding+question+padding,
            'topic':'place','quote':page['source']['text'],'requires_confirmation':True}]}
        if strategy_selector:
            result['strategy_proposal']={'strategy':'shape','objective':'clarify_identity','focus_event_ids':[]}
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")
        turn=str(uuid4())
        second=client.post('/v1/agent/turn',json={'project_id':project,'text':'Please go on.','client_turn_id':turn},
            headers={'accept':'application/x-ndjson'} if streaming else {})
        assert second.status_code==200,second.text
        if streaming:
            events=[json.loads(line) for line in second.text.splitlines()]
            assert events[-1]['type']=='result',second.text
            saved=events[-1]['data']
        else:saved=second.json()
        assert saved['reply'].endswith(question)
        assert sql(f"select count(*) from public.user_memory_delivered_context where client_turn_id='{turn}';").stdout.strip()=='1'
        pending=rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")
        third=client.post('/v1/agent/turn',json={'project_id':project,'text':'The water was clear.','client_turn_id':str(uuid4())})
        assert third.status_code==200,third.text
        assert not third.json()['reply'].endswith(question),'The delivered confirmation repeated on the next turn'
        assert pending==[],'The delivered confirmation stayed queued'
        if strategy_selector:
            state=rpc(sql,'read_lifetime_strategy_context',f"'{identity['conversation_id']}'")
            assert state['plan']['candidates']==[]


@pytest.mark.parametrize('strategy_selector', [False, True])
@pytest.mark.parametrize('hint_after_failure', [False, True])
@pytest.mark.parametrize('padding', ['', ' \n\t'])
def test_confirmation_is_consumed_only_after_delivery_and_retry_preserves_its_identity(
        sql, tmp_path, monkeypatch, strategy_selector, hint_after_failure, padding):
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.lifetime_memory_runtime import lifetime_http_turn
    from memoir_postgres_workflow import PostgresRest
    from test_interview_strategy_runtime import client_fixture
    from test_interview_strategy import wire
    from controlled_collector import worker_reply

    calls = []
    question = {**QUESTION, 'question': padding+'Did you mean Hobart in Tasmania?'+padding, 'requires_confirmation': True}
    narration = 'The river walks near Hobart were in summer.'

    def provider(request):
        body = json.loads(request.content)
        calls.append(body)
        pending = body['interview_context']['prepared_questions']
        text = question['question'] if len(calls) == 2 else 'What do you remember about the river?'
        if strategy_selector:
            output = wire(question=text, selected_candidate_id=pending[0]['id'] if pending else None,
                          selection_reason='prepared_candidate' if pending else 'latest_story')
        else:
            output = proposal(mode='extract', name=None, question=text)
            output['selection_reason'] = 'latest_story'
        if pending and len(calls)==2:
            choose_prepared(output,pending[0])
        if hint_after_failure and len(calls) == 2:
            anchor_question(output, body['interview_context']['source'], narration)
        return worker_reply(request, {'reply': json.dumps(output), 'thread_id': 'delivery-retry', 'artifacts': []})

    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        if not strategy_selector:
            monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY', '0')
            sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
        first = client.post('/v1/agent/turn', json={'text': TEXT, 'client_turn_id': str(uuid4())})
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(project))

        def publish_confirmation():
            lane_id = lane(sql, identity)
            page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
            result = {'events': [], 'place_journeys': [], 'prepared_questions': []}
            if hint_after_failure:
                service(sql, 'commit_lifetime_memoir_lane_page',
                        f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")
                page = service(sql, 'read_lifetime_memoir_lane_page', f"'{lane_id}','{page['token']}'")
                assert page['source']['text'] == narration
            result['prepared_questions'] = [{**question, 'quote': page['source']['text']}]
            if strategy_selector:
                result['strategy_proposal'] = {'strategy':'shape','objective':'clarify_identity','focus_event_ids':[]}
            service(sql, 'commit_lifetime_memoir_lane_page',
                    f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")

        if not hint_after_failure:
            publish_confirmation()
        turn = str(uuid4())
        options = {'project_id': project, 'client_turn_id': turn}
        runtime = CodexRuntime(home_root=tmp_path, worker_url='http://controlled.invalid',
            worker_secret='synthetic', worker_transport=httpx.MockTransport(provider))

        async def failed_send():
            response = await lifetime_http_turn(runtime, PostgresRest(sql, OWNER).storage(),
                narration, accept='application/json', options=options)
            assert [q['question'] for q in rpc(sql, 'read_lifetime_prepared_questions',
                f"'{identity['conversation_id']}'")] == ([] if hint_after_failure else [question['question']])
            async def receive(): return {'type': 'http.disconnect'}
            async def send(message):
                if message['type'] == 'http.response.body': raise OSError('synthetic closed socket')
            with pytest.raises(OSError):
                await response({'type': 'http', 'asgi': {'spec_version': '2.4'}}, receive, send)
            assert not response.delivered

        asyncio.run(failed_send())
        assert sql(f"select count(*) from public.user_memory_delivered_context where client_turn_id='{turn}';").stdout.strip() == '0'
        if hint_after_failure:
            publish_confirmation()
        assert [q['question'] for q in rpc(sql, 'read_lifetime_prepared_questions',
            f"'{identity['conversation_id']}'")] == [question['question']]
        retry = client.post('/v1/agent/turn', json={**options, 'text': narration})
        assert retry.status_code == 200 and retry.json()['cached'], retry.text
        assert retry.json()['reply'].endswith(question['question'].strip())
        assert len(calls) == 2
        assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'") == []
        assert sql("select count(*) from public.user_lifetime_prepared_question where questions<>'[]'::jsonb;").stdout.strip() == '0'
        assert sql(f"select count(*) from public.user_memory_delivered_context where client_turn_id='{turn}';").stdout.strip() == '1'


def test_pending_hint_recovers_an_older_answer_and_withdrawal_invalidates_it(sql, tmp_path, monkeypatch):
    from test_interview_strategy_runtime import client_fixture
    from controlled_collector import worker_reply

    confirmation = 'Did you mean Hobart in Tasmania?'
    calls = []
    def provider(request):
        calls.append(request)
        context = json.loads(request.content)['interview_context']
        output = proposal(mode='extract', name=None, question=confirmation if len(calls) == 1
                          else f'What do you recall about detail {len(calls)}?')
        output['selection_reason'] = 'latest_story'
        if context['prepared_questions']:
            answer = next(item['response'] for item in context['recent_dialogue']
                          if item['question']['text'] == confirmation)
            output['plan']['resolved_questions'] = [{'question_id': context['prepared_questions'][0]['id'],
                'source_id': answer['id'], 'source_version': answer['version'],
                'char_start': 0, 'char_end': 4, 'quote': 'Yes.'}]
        return worker_reply(request, {'reply': json.dumps(output), 'thread_id': 'old-dialogue', 'artifacts': []})

    with client_fixture(sql, tmp_path, monkeypatch, provider) as client:
        monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY', '0')
        sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
        first = client.post('/v1/agent/turn', json={'text': TEXT, 'client_turn_id': str(uuid4())})
        assert first.status_code == 200, first.text
        project = first.json()['project_id']
        identity = rpc(sql, 'resolve_lifetime_conversation', literal(project))
        answer = client.post('/v1/agent/turn', json={'project_id': project, 'text': 'Yes.', 'client_turn_id': str(uuid4())})
        assert answer.status_code == 200, answer.text
        for n in range(9):
            later = client.post('/v1/agent/turn', json={'project_id': project,
                'text': 'I also remember the Hobart river.' if n==8 else f'Another memory about detail {n}.', 'client_turn_id': str(uuid4())})
            assert later.status_code == 200, later.text

    recent = json.loads(sql(f"select public.lifetime_question_dialogue('{OWNER}',{literal(project)});").stdout)
    assert all(item['question']['text'] != confirmation for item in recent)
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    result = {'events': [dict(kind='event',title='Hobart river walks',source_refs=[dict(source_id=page['source']['id'],version=page['source']['version'],quote=TEXT)])], 'place_journeys': [], 'prepared_questions': [{**QUESTION,
        'question': 'Was that Hobart, Tasmania?', 'requires_confirmation': True}]}
    from apps.api.lifetime_memory_composer import extraction_events
    result['events']=extraction_events({'events':result['events']},page)
    service(sql, 'commit_lifetime_memoir_lane_page',
            f"'{lane_id}','{page['token']}',{page['page_number']},{literal(result)}")
    context = rpc(sql, 'read_lifetime_interview_context', f"'{identity['conversation_id']}'")
    exchange = next(item for item in context['recent_dialogue'] if item['question']['text'] == confirmation)
    assert exchange['response']['id'] == answer.json()['accepted_source_id']
    assert exchange['response']['text'] == 'Yes.'
    sequences = [item['question']['sequence'] for item in context['recent_dialogue']]
    assert sequences == sorted(sequences)
    assert len(context['recent_dialogue']) <= 14
    assert rpc(sql, 'read_lifetime_interview_context', f"'{identity['conversation_id']}'", owner=OTHER, check=False).returncode != 0
    cold_client = client_fixture(sql, tmp_path, monkeypatch, provider)
    monkeypatch.setenv('MEMOIR_INTERVIEW_STRATEGY', '0')
    sql('update public.lifetime_two_lane_rollout set strategy_enabled=false;')
    with cold_client:
        continued = cold_client.post('/v1/agent/turn', json={'project_id': project,
            'text': 'The riverbank was sandy.', 'client_turn_id': str(uuid4())})
        assert continued.status_code == 200, continued.text
        assert 'Was that Hobart' not in continued.json()['reply']
    assert rpc(sql, 'read_lifetime_prepared_questions', f"'{identity['conversation_id']}'") == []

    rpc(sql, 'change_user_narrator_source',
        f"{literal(project)},'{answer.json()['accepted_source_id']}',1,'withdraw',null")
    changed = rpc(sql, 'read_lifetime_interview_context', f"'{identity['conversation_id']}'")
    assert all(item['question']['text'] != confirmation for item in changed['recent_dialogue'])


@pytest.mark.parametrize('flag', ['true', 1, None])
def test_sql_rejects_untyped_confirmation_flags(sql, flag):
    identity, _ = accept(sql)
    lane_id = lane(sql, identity)
    page = service(sql, 'claim_memoir_lane', f"'{lane_id}',300")
    from split_lane_fixtures import publish
    publish(sql,page,[{**QUESTION,'requires_confirmation':True}])
    guided,result=sql.guidance_publication
    # Make a fresh fenced page, then corrupt its well-typed controlled output.
    sql(f"update public.user_memoir_lane set pending=true,guidance_revision=guidance_revision+1 where skill='guidance';")
    guided=canonical_service(sql,'claim_memoir_lane',f"'{guided['lane_id']}',300")
    before=rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")
    result['prepared_questions'][0]['requires_confirmation']=flag
    with pytest.raises(AssertionError):
        canonical_service(sql,'commit_lifetime_interview_guidance',
            f"'{guided['lane_id']}','{guided['token']}',{literal(guided['page_digest'])},{literal(result)}")
    # The failed write cannot overwrite the previous valid candidate.
    assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")==before


@pytest.mark.parametrize('change',['policy','source','generation','lease','rollout'])
def test_background_cas_rejects_stale_results_and_candidate_reads(sql,change):
    identity,accepted=accept(sql)
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    if change=='policy':
        sql(as_user("update public.user_profile set profile=jsonb_build_object('memory_preferences',jsonb_build_object('excluded_topics',jsonb_build_array('river')));"))
    elif change=='source':
        rpc(sql,'change_user_narrator_source',f"{literal(identity['project_id'])},'{accepted['source']['id']}',1,'withdraw',null")
    elif change=='generation':
        sql('update public.user_lifetime_conversation set execution_generation=execution_generation+1;')
    elif change=='rollout':
        sql('update public.lifetime_two_lane_rollout set enabled=false;')
    else:
        sql('update public.user_memoir_lane set lease_until=clock_timestamp()-interval \'1 second\';')
    result={'events':[],'place_journeys':[{k:v for k,v in {**PLACE,'schema_version':1}.items() if v is not None}], 'prepared_questions':[QUESTION]}
    failed=sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane_id}','{page['token']}',0,{literal(result)},'{page['page_digest']}');",check=False)
    assert failed.returncode!=0
    assert sql('select count(*) from public.user_lifetime_place_journey;').stdout.strip()=='0'
    assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")==[]


def test_worker_capacity_reserves_an_interactive_slot_and_bounds_queue():
    from apps.api.two_lane_memory import RuntimeCapacity
    async def scenario():
        capacity=RuntimeCapacity(total=2,background=1,queue_limit=1)
        entered=asyncio.Event();release=asyncio.Event()
        async def background():
            async with capacity.slot(interactive=False):
                entered.set();await release.wait()
        running=asyncio.create_task(background());await entered.wait()
        waiting=asyncio.create_task(background());await asyncio.sleep(0)
        with pytest.raises(Exception,match='capacity'):
            async with capacity.slot(interactive=False):pass
        async with asyncio.timeout(1):
            async with capacity.slot(interactive=True):pass
        waiting.cancel();await asyncio.gather(waiting,return_exceptions=True)
        release.set();await running
        assert capacity.waiting==0
    asyncio.run(scenario())


@pytest.mark.parametrize('background_outcome',['blocked','failed'])
def test_actual_ndjson_a_is_saved_while_b_provider_is_blocked_or_failed(sql,tmp_path,monkeypatch,background_outcome):
    from types import SimpleNamespace
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.lifetime_memory_composer import _extract
    from apps.api.lifetime_memory_lane_engine import LanePublication
    from apps.api.lifetime_memory_publication import TransactionalPublication
    from apps.api.lifetime_memory_runtime import LifetimePublicationContext
    from apps.api.lifetime_memory_transport import governed_turn_events, GovernedStreamingResponse
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1')
    monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setenv('MEMORY_SPARK_SHOW_THINKING_STEPS','1')
    turn=str(uuid4());identity,accepted=accept(sql,turn=turn)
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    async def scenario():
        storage=PostgresRest(sql,OWNER).storage()
        started=asyncio.Event();release=asyncio.Event();calls=[];events=[]
        class Broker:
            async def rpc(self,name,**args):
                query=','.join(k+'=>'+literal(v) for k,v in args.items())
                return await asyncio.to_thread(lambda:json.loads(sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.strip() or 'null'))
        async def provider(request):
            body=json.loads(request.content);calls.append(body)
            if body.get('bounded_lane'):
                started.set();await release.wait()
                if background_outcome=='failed':return httpx.Response(503)
                return httpx.Response(200,json={'reply':json.dumps({'events':[],'place_journeys':[PLACE],'prepared_questions':[QUESTION]}),'thread_id':'b','artifacts':[]})
            assert body['thread_id'] is None
            assert body['interview_context']['two_lane_memory'] is True
            assert 'place_journeys' not in governed_collector_schema(body['interview_context'])['properties']
            output=proposal(mode='extract',name=None,question='What would you like to remember about those walks?')
            output['plan']['conversation_phase']='explore'
            return httpx.Response(200,headers={'Content-Type':'application/x-ndjson'},content=json.dumps({'type':'result','data':{'reply':json.dumps(output),'thread_id':'a','artifacts':[]}})+'\n')
        transport=httpx.MockTransport(provider)
        worker=SimpleNamespace(broker=Broker(),worker_url='http://controlled.invalid',worker_secret='synthetic',
            worker_transport=transport,lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))
        b=asyncio.create_task(_extract(page,worker))
        runtime=CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=transport)
        publication=LifetimePublicationContext()
        async def run(emit):
            publication.emitter=emit
            return await runtime.turn(storage,TEXT,project_id=identity['project_id'],client_turn_id=turn,
                lifetime_context=publication,on_delta=emit,on_event=emit.event)
        async def cleanup():
            await publication.close()
        response=GovernedStreamingResponse(governed_turn_events(run,cleanup=cleanup),
            publisher=TransactionalPublication(sql.publication_dsn,authenticated_owner=OWNER))
        async def send(message):
            if message.get('body'):
                for line in message['body'].splitlines():events.append(json.loads(line))
        try:
            async with asyncio.timeout(5):await started.wait()
            async with asyncio.timeout(10):await response.stream_response(send)
            assert not b.done(), 'The blocked B provider must still be waiting at the A save barrier'
            assert response.delivered
            saved=next(e['data'] for e in events if e['type']=='conversation_saved')
            result=next(e['data'] for e in events if e['type']=='result')
            assert saved['conversation_saved'] and saved['accepted_source_id']==accepted['source']['id']
            assert result['reply_id'] and result['reply_id']!=result['accepted_source_id']
            assert next(e['data'] for e in events if e['type']=='reply_complete')['reply_id']==result['reply_id']
            assert result['reply'].endswith('What would you like to remember about those walks?')
            assert ''.join(e['text'] for e in events if e['type']=='text_delta')==result['reply']
            assert not [e for e in events if e['type']=='error']
            assert len(calls)==2, 'One A call and one conditional B call; no classifier'
            assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
            release.set()
            if background_outcome=='failed':
                with pytest.raises(httpx.HTTPStatusError):await b
            else:
                hints=await b
                # A changed the phase while B was in flight: that old page is
                # invalid; it must be retried from current authoritative pins.
                stale=sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane_id}','{page['token']}',0,{literal(hints)},'{page['page_digest']}');",check=False)
                assert stale.returncode!=0
            assert sql('select count(*) from public.user_lifetime_place_journey;').stdout.strip()=='0'
        finally:
            release.set()
            if not b.done():b.cancel()
            await asyncio.gather(b,return_exceptions=True)
            await publication.close();storage.client.close()
    asyncio.run(scenario())


def test_complete_checkpoint20_tail21_tombstone22_current23_keeps_cursor_domains_separate():
    from uuid import UUID
    from apps.api.lifetime_memory_context import ContextCheckpoint,TailCoverage,build_context
    from apps.api.lifetime_memory_contracts import SourceManifest
    from test_lifetime_memory_context import IDENTITY,PINS,BUDGET,source
    checkpoint=ContextCheckpoint(checkpoint_id=UUID(int=700),identity=IDENTITY,policy_epoch=1,coverage_end=20,
        model=BUDGET.model,prompt_version='lifetime-v1',pinned=PINS,
        manifest=SourceManifest(identity=IDENTITY,policy_epoch=1,source_revision=20,sources=[]))
    result=build_context(identity=IDENTITY,policy_epoch=1,pinned=PINS,instructions='Current policy is authoritative.',
        current=source(23),tail=[source(21)],retrieved=[],budget=BUDGET,checkpoint=checkpoint,
        tail_coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=20,through_sequence=22,complete=True,tombstones=[22]))
    assert result['coverage_end']==20 and [t['sequence'] for t in result['tail']]==[21]
    assert result['current']['sequence']==23 and result['current']['narrator']['version']==1
    assert not {'summary_source','summary_offset','summarised_through_seq'} & result.keys()
    with pytest.raises(ValueError,match='coverage'):
        build_context(identity=IDENTITY,policy_epoch=1,pinned=PINS,instructions='safe',current=source(23),
            tail=[],retrieved=[],budget=BUDGET,checkpoint=checkpoint,
            tail_coverage=TailCoverage(identity=IDENTITY,policy_epoch=1,after_sequence=20,through_sequence=22,complete=True,tombstones=[22]))


def test_background_checkpoint_is_bounded_resumable_and_keeps_composer_fragment_cursor(sql):
    identity,accepted=accept(sql,text='A long memory '+('原文 '*3000))
    project=identity['project_id']
    # Accepted originals may outnumber completed rounds. Do not manufacture
    # replies merely to populate a checkpoint coverage test.
    for n in range(2,23):
        rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{uuid4()}',{literal(('Original words '*5000) if n==2 else 'Memory '+str(n))}")
    rpc(sql,'change_user_narrator_source',f"{literal(project)},'{accepted['source']['id']}',1,'withdraw',null")
    lane_id=lane(sql,identity)
    page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    before=sql('select jsonb_build_array(summary_source,summary_offset) from public.user_lifetime_lane_snapshot;').stdout.strip()
    result=service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    assert result['complete'] is False
    while not result['complete']:
        result=service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")
    assert result['coverage_end']==0 and result['summary_pending'] and not result['checkpoint_published']
    checkpoint=rpc(sql,'read_lifetime_checkpoint',f"'{identity['conversation_id']}',2,'gpt-5.6-luna-pooled','lifetime-v1'")
    assert checkpoint is None, 'A coverage proof cannot license silently dropped narrator evidence'
    assert sql('select count(distinct sequence) from public.user_lifetime_covered_evidence;').stdout.strip()=='22'
    assert sql("select count(*) from public.user_lifetime_covered_evidence where status in ('withdrawn','superseded');").stdout.strip()=='1'
    assert sql('select jsonb_build_array(summary_source,summary_offset) from public.user_lifetime_lane_snapshot;').stdout.strip()==before
    assert service(sql,'advance_two_lane_checkpoint',f"'{lane_id}','{page['token']}',1")['summary_pending']
    assert sql('select count(*) from public.user_lifetime_checkpoint;').stdout.strip()=='0'


@pytest.mark.parametrize('requires_confirmation', [False, True])
def test_complete_vertical_slice_background_hint_consumed_next_turn_and_replay_deduplicates(sql,tmp_path,monkeypatch,requires_confirmation):
    from types import SimpleNamespace
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    from apps.api.lifetime_memory_lane_engine import LanePublication
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from fastapi.testclient import TestClient
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1');monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    question = {**QUESTION, 'requires_confirmation': requires_confirmation}
    if requires_confirmation:
        question['question'] = 'Did you mean Hobart in Tasmania?'
    packets=[]
    def provider(request):
        body=json.loads(request.content);context=body['interview_context'];packets.append(json.loads(body['governed']['packet']))
        output=proposal(mode='extract',name=None,question=(
            QUESTION['question'] if len(packets)>1 else 'What do you remember about Hobart?'))
        output['selection_reason']='latest_story'
        output['plan']['conversation_phase']='explore'
        if len(packets)>1:
            assert context['prepared_questions'][0]['source_id']==packets[0]['current']['narrator']['source_id']
            candidate=context['prepared_questions'][0]
            assert candidate.get('requires_confirmation', False) == requires_confirmation
            choose_prepared(output,candidate)
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'a-'+str(len(packets)),'artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    with TestClient(create_app(MemoryStore(),story_storage_factory=lambda _:PostgresRest(sql,OWNER).storage())) as client:
        first=client.post('/v1/agent/turn',json={'text':TEXT,'client_turn_id':str(uuid4())})
        assert first.status_code==200,first.text
        project=first.json()['project_id'];identity=rpc(sql,'resolve_lifetime_conversation',literal(project))
        lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
        class Broker:
            async def rpc(self,name,**args):
                query=','.join(k+'=>'+literal(v) for k,v in args.items())
                return await asyncio.to_thread(lambda:json.loads(sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.strip() or 'null'))
        def background(request):
            bounded=json.loads(request.content)['bounded_lane']
            phase=bounded['phase']
            if phase=='guidance':
                from controlled_interview_guidance import from_legacy_questions
                packet=json.loads(bounded['packet'])['payload']
                result=from_legacy_questions(packet,{page['source']['id']:[question]})
                return httpx.Response(200,json={'reply':json.dumps(result),'thread_id':'guidance','artifacts':[]})
            if phase=='profile':
                return httpx.Response(200,json={'reply':'{"profile_patch":[]}','thread_id':'profile','artifacts':[]})
            assert phase=='extract'
            return httpx.Response(200,json={'reply':json.dumps({'events':[],'place_journeys':[PLACE]}),'thread_id':'b','artifacts':[]})
        worker=SimpleNamespace(broker=Broker(),worker_url='http://controlled.invalid',worker_secret='synthetic',
            worker_transport=httpx.MockTransport(background),lane_publisher=LanePublication(sql.publication_dsn,authenticated_owner=OWNER))
        settled=asyncio.run(execute_lifetime_lane(page,worker))
        assert settled['retrieval_complete'] is True
        guidance_lane=sql("select id from public.user_memoir_lane where skill='guidance';").stdout.strip()
        guided=canonical_service(sql,'claim_memoir_lane',f"'{guidance_lane}',300")
        assert asyncio.run(execute_lifetime_lane(guided,worker))['status']=='finished'
        read=client.get('/v1/story/readiness',params={'project_id':project})
        assert read.status_code==200,read.text
        assert read.json()['derived_workspace']['places'][0]['place']=='Hobart'
        turn=str(uuid4());payload={'project_id':project,'client_turn_id':turn,'text':'I remember the water.'}
        second=client.post('/v1/agent/turn',json=payload)
        assert second.status_code==200,second.text
        assert second.json()['reply'].endswith(question['question'])
        retry=client.post('/v1/agent/turn',json=payload)
        assert retry.status_code==200,retry.text
        assert retry.json()['reply_id']==second.json()['reply_id'] and retry.json()['cached']
        assert len(packets)==2
        assert rpc(sql,'read_lifetime_prepared_questions',f"'{identity['conversation_id']}'")==[]
        assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='2'
        assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='2'
        retried_b=client.post('/v1/story/memory/retry',json={'project_id':project})
        assert retried_b.status_code==200,retried_b.text
        assert retried_b.json()['status']=='pending'
        assert sql("select count(*) from public.user_memoir_lane where skill='composer';").stdout.strip()=='0'


def test_commit_failure_reports_pending_source_blocks_overlap_and_retries_same_source(sql,tmp_path,monkeypatch):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from fastapi.testclient import TestClient
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1');monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    def provider(request):
        output=proposal(mode='extract',name=None);output['plan']['conversation_phase']='explore'
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'a','artifacts':[]})
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    sql("alter table public.user_memory add constraint issue70_save_failure check (kind<>'agent');")
    try:
        with TestClient(create_app(MemoryStore(),story_storage_factory=lambda _:PostgresRest(sql,OWNER).storage())) as client:
            payload={'text':TEXT,'client_turn_id':str(uuid4())}
            failed=client.post('/v1/agent/turn',json=payload)
            assert failed.status_code==503,failed.text
            assert failed.json()['detail']['state']=='source_accepted'
            source_id=failed.json()['detail']['accepted_source_id']
            assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
            assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'
            other=client.post('/v1/agent/turn',json={**payload,'client_turn_id':str(uuid4())})
            assert other.status_code in {409,503}
            assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='1'
            sql('alter table public.user_memory drop constraint issue70_save_failure;')
            retried=client.post('/v1/agent/turn',json=payload)
            assert retried.status_code==200,retried.text
            assert retried.json()['accepted_source_id']==source_id
            assert retried.json()['reply_id']!=source_id
    finally:
        sql('alter table public.user_memory drop constraint if exists issue70_save_failure;')


def test_name_only_reply_only_skips_the_background_model_and_does_not_mark_a_question_delivered(sql,tmp_path,monkeypatch):
    from apps.api.lifetime_memory_composer import _extract
    from types import SimpleNamespace
    identity,accepted=accept(sql,text='My name is Joan')
    # A's ordinary validator is the sole work-decision authority; represent its
    # already validated and saved plan, without running another classifier.
    output=proposal(name='Joan')
    sql(f"update public.user_interview_turn set collector=jsonb_build_object('plan',{literal(output['plan'])}::jsonb);")
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['two_lane']['work_mode']=='reply_only'
    assert asyncio.run(_extract(page,SimpleNamespace()))=={'events':[],'place_journeys':[]}
    assert sql('select count(*) from public.user_lifetime_reply;').stdout.strip()=='0'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_background_waits_for_the_single_collector_decision_and_recovers_after_a_failure(sql):
    from apps.api.lifetime_memory_composer import execute_lifetime_lane
    from types import SimpleNamespace
    sql(as_user(f"select public.acquire_user_agent_turn_lease('{OLD}');"))
    identity,accepted=accept(sql,text='My name is Joan')
    lane_id=lane(sql,identity);page=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert page['two_lane']['work_mode']=='pending'
    class Broker:
        async def rpc(self,name,**args):
            query=','.join(k+'=>'+literal(v) for k,v in args.items())
            return json.loads(sql('set role service_role;select to_jsonb(public.'+name+'('+query+'));').stdout.splitlines()[-1])
    assert asyncio.run(execute_lifetime_lane(page,SimpleNamespace(broker=Broker())))['status']=='pending'
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip()=='0'
    sql(as_user(f"select public.release_user_agent_turn_lease('{OLD}');"))
    resumed=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert resumed['two_lane']['work_mode']=='extract', 'Failed A still leaves a durable accepted source for B'


def test_burst_coalescing_concurrent_claim_crash_restart_and_old_token_are_idempotent(sql):
    from concurrent.futures import ThreadPoolExecutor
    turn=str(uuid4());identity,accepted=accept(sql,turn=turn)
    project=identity['project_id']
    for n in range(2,5):rpc(sql,'accept_user_narrator_source',f"{literal(project)},'{uuid4()}','Additional accepted original {n}'")
    # A retry wakes the same durable owner at the newest requested sequence.
    accept(sql,project=project,turn=turn)
    lane_id=lane(sql,identity)
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims=list(pool.map(lambda _:service(sql,'claim_memoir_lane',f"'{lane_id}',300"),range(2)))
    assert sum(page is not None for page in claims)==1
    first=next(page for page in claims if page)
    assert first['source_high_water']==4
    service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{first['token']}',0,{literal({'events':[],'place_journeys':[],'prepared_questions':[]})}")
    sql(f"update public.user_memoir_lane set lease_until=clock_timestamp()-interval '1 second' where id='{lane_id}';")
    resumed=service(sql,'claim_memoir_lane',f"'{lane_id}',300")
    assert resumed['token']!=first['token'] and resumed['page_number']==1
    assert resumed['source']['sequence']==2
    stale=sql(f"set role service_role;select public.commit_lifetime_memoir_lane_page('{lane_id}','{first['token']}',0,'{{\"events\":[]}}','{first['page_digest']}');",check=False)
    assert stale.returncode!=0
    while not resumed['complete']:
        service(sql,'commit_lifetime_memoir_lane_page',f"'{lane_id}','{resumed['token']}',{resumed['page_number']},'{json.dumps({'events':[]})}'")
        resumed=service(sql,'read_lifetime_memoir_lane_page',f"'{lane_id}','{resumed['token']}'")
    service(sql,'complete_lifetime_memoir_lane',f"'{lane_id}','{resumed['token']}'")
    assert sql(f"select target_source||':'||successful_source from public.user_memoir_lane where id='{lane_id}';").stdout.strip()=='4:4'
    assert sql('select count(*) from public.user_lifetime_source_extraction;').stdout.strip()=='4'
    assert sql("select count(*) from public.user_lifetime_memory_obligation where kind='source_projection';").stdout.strip()=='4'
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='0'


def test_database_rollout_guard_cannot_be_enabled_by_an_authenticated_rpc_caller(sql):
    sql('update public.lifetime_two_lane_rollout set enabled=false;')
    identity=rpc(sql,'resolve_lifetime_conversation','null')
    assert rpc(sql,'accept_two_lane_interview_turn',f"{literal(identity['project_id'])},'{uuid4()}','Must not be accepted'",check=False).returncode!=0
    assert sql(as_user('update public.lifetime_two_lane_rollout set enabled=true;'),check=False).returncode!=0
    assert sql('select count(*) from public.user_narrator_source;').stdout.strip()=='0'


@pytest.mark.parametrize('text,language,mode,name,stopped,restriction',[
    ('My name is Joan','en-AU','reply_only','Joan',False,None),
    ('我小时候住在承德，常和母亲一起去河边散步。','zh-CN','extract',None,False,None),
    ('Dad repaired things.','en-AU','extract',None,False,None),
    ('Please continue in English. 我记得花园。','en-AU','extract',None,False,None),
    ('What happens to my memories?','en-AU','reply_only',None,False,None),
    ('I would like to pause here. Please do not ask another question.','en-AU','reply_only',None,True,None),
    ('This is upsetting. Stop here for today.','en-AU','reply_only',None,True,None),
    ('这让我很难受。今天就到这里吧。','zh-CN','reply_only',None,True,None),
    ('My father repaired bicycles in Hobart. Stop here for today.','en-AU','extract',None,True,None),
    ('我父亲在霍巴特修自行车。今天就到这里吧。','zh-CN','extract',None,True,None),
    ("Don't discuss my school. I meant my mother, not my sister.",'en-AU','extract',None,False,"Don't discuss my school."),
])
def test_flag_on_single_collector_work_question_and_language_contract(sql,tmp_path,monkeypatch,text,language,mode,name,stopped,restriction,fixed_policy_controls):
    from apps.api import agent_routes
    from apps.api.codex_runtime import CodexRuntime
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from fastapi.testclient import TestClient
    from memoir_postgres_workflow import PostgresRest
    monkeypatch.setenv('MEMOIR_TWO_LANES','1');monkeypatch.setenv('MEMOIR_PUBLICATION_DATABASE_URL',sql.publication_dsn)
    if restriction:
        fixed_policy_controls.append(('excluded_topic', restriction))
    calls=[]
    def provider(request):
        body=json.loads(request.content);calls.append(body);packet=json.loads(body['governed']['packet'])
        assert packet['current']['narrator']['original']==text
        assert packet['pinned']['language']==language
        assert packet['interview_context']['two_lane_memory'] is True
        if restriction:assert packet['pinned']['excluded_topics']
        output=proposal(mode=mode,name=name,question='您还记得什么？' if language=='zh-CN' else 'What else do you remember?')
        output['plan']['conversation_phase']='comfort' if mode=='reply_only' else 'explore'
        output['stopped']=stopped
        if stopped:output['plan'].update(candidates=[],chosen_id=None)
        elif mode=='extract':
            extra=deepcopy(output['plan']['candidates'][0]);extra.update(id='q-extra',question='当时的什么让您印象深刻？' if language=='zh-CN' else 'What stood out then?',order=1)
            output['plan']['candidates'].append(extra)
        return httpx.Response(200,json={'reply':json.dumps(output),'thread_id':'controlled','artifacts':[]})
    monkeypatch.setattr(agent_routes,'authenticated_storage',lambda _:PostgresRest(sql,OWNER).storage())
    monkeypatch.setattr(agent_routes,'runtime',CodexRuntime(home_root=tmp_path,worker_url='http://controlled.invalid',worker_secret='synthetic',worker_transport=httpx.MockTransport(provider)))
    with TestClient(create_app(MemoryStore())) as client:
        response=client.post('/v1/agent/turn',json={'text':text,'client_turn_id':str(uuid4())})
        assert response.status_code==200,response.text
        assert response.json()['conversation_saved']
        assert len(calls)==1
    assert sql('select count(*) from public.user_completed_round;').stdout.strip()=='1'
    assert sql("select collector->'plan'->'work'->>'mode' from public.user_interview_turn;").stdout.strip()==mode
    if stopped:
        plan=json.loads(sql("select collector->'plan' from public.user_interview_turn;").stdout.strip())
        assert plan['candidates']==[] and plan['chosen_id'] is None
