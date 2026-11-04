"""Historical guidance validation and rejection of the retired model capability."""
from copy import deepcopy

import pytest

from apps.api.interview_guidance import validate_guidance_result


def context():
    sources = [dict(id='earlier',version=1,text='My uncle was called Chen.',char_start=0,char_end=25,
                    status='active',kind='narrator_chat'),
               dict(id='current',version=1,text='I also called that uncle Ming. I cannot remember the date. Helping family mattered to me.',
                    char_start=0,char_end=57,status='active',kind='narrator_chat')]
    sources[1]['char_end']=len(sources[1]['text'])
    return {'source':sources[1],'events':[], 'guidance_context':{'source_windows':sources,
        'recent_dialogue':[{'question':{'id':f'q{i}','delivered':True,'role':'assistant'},
                            'response':{'id':'earlier','role':'user','complete':True}} for i in range(3)],
        'news_clues':[{'id':'news-'+'a'*24}],'minimum_detail_rounds':3}}


def ref(source='current',quote='Ming'):
    return dict(source_id=source,version=1,quote=quote,char_start=None,char_end=None,attribution=None)


def result(kind='clarification'):
    return {'signals':[{'kind':kind,'source_refs':[ref()], 'detail_question_ids':[], 'recall_limit_quote':None}],
        'prepared_questions':[dict(question='Were Chen and Ming the same uncle?',topic='Uncle',quote='Ming',
            char_start=None,char_end=None,requires_confirmation=kind in {'conflict','clarification'},
            scope='broader' if kind in {'historical_news','topic_transition','life_essence'} else 'detail',
            source_id='current',source_version=1,trigger=kind,historical_clue_id=None,bridge='')],
        'acknowledgement_guidance':None,'strategy_proposal':None}


def test_identity_clarification_generates_a_question_without_merging_people():
    raw=result();before=deepcopy(raw)
    output=validate_guidance_result(raw,context())
    assert output['prepared_questions'][0]['trigger']=='clarification'
    assert output['prepared_questions'][0]['requires_confirmation'] is True
    assert output['prepared_questions'][0]['char_start']==25
    assert raw==before
    assert not {'events','people','family_links'} & output.keys()


def test_conflict_always_precedes_other_triggered_questions():
    raw=result('historical_news');raw['prepared_questions'][0]['historical_clue_id']='news-'+'a'*24
    raw['prepared_questions'][0]['question']='Does this public historical clue remind you of that time?'
    urgent=result('conflict');urgent['signals'][0]['source_refs'].append(ref('earlier','Chen'))
    raw['signals']+=urgent['signals'];raw['prepared_questions']+=urgent['prepared_questions']
    assert validate_guidance_result(raw,context())['prepared_questions'][0]['trigger']=='conflict'


@pytest.mark.parametrize('kind',['historical_news','topic_transition','life_essence'])
def test_each_broader_trigger_has_its_own_eligibility(kind):
    raw=result(kind)
    if kind=='historical_news':raw['prepared_questions'][0]['historical_clue_id']='news-'+'a'*24
    if kind=='topic_transition':raw['signals'][0]['detail_question_ids']=['q0','q1','q2']
    if kind=='life_essence':raw['acknowledgement_guidance']={'text':'Helping family seems to be a thread worth exploring.','source_refs':[ref(quote='Helping family mattered to me.')]}
    output=validate_guidance_result(raw,context())
    assert output['prepared_questions'][0]['scope']=='broader'
    assert output['prepared_questions'][0]['requires_confirmation'] is False


def test_recall_limit_permits_a_broader_direction_before_detail_cadence():
    raw=result('topic_transition');raw['signals'][0]['recall_limit_quote']='I cannot remember the date.'
    current=context();current['guidance_context']['recent_dialogue']=[]
    assert validate_guidance_result(raw,current)['prepared_questions'][0]['scope']=='broader'


@pytest.mark.parametrize('failure',['foreign_source','wrong_quote','unavailable_news','fabricated_detail_rounds','unsupported_reflection'])
def test_guidance_keeps_original_and_public_context_boundaries(failure):
    raw=result()
    if failure=='foreign_source':raw['prepared_questions'][0]['source_id']='another-owner'
    elif failure=='wrong_quote':raw['signals'][0]['source_refs'][0]['quote']='not present'
    elif failure=='unavailable_news':
        raw=result('historical_news');raw['prepared_questions'][0]['historical_clue_id']='news-'+'b'*24
    elif failure=='fabricated_detail_rounds':
        raw=result('topic_transition');raw['signals'][0]['detail_question_ids']=['q0','q1','invented']
    else:raw['acknowledgement_guidance']={'text':'A possible theme.','source_refs':[ref('another-owner','Ming')]}
    with pytest.raises(ValueError):validate_guidance_result(raw,context())


def test_no_trigger_preserves_the_existing_pool_and_does_not_invent_a_reflection():
    assert validate_guidance_result({'signals':[],'prepared_questions':[],
        'acknowledgement_guidance':None,'strategy_proposal':None},context())['prepared_questions']==[]


def test_retired_guidance_cannot_dispatch_a_model_or_register_a_prompt():
    from apps.api.background_skills import SKILLS
    from apps.api.codex_worker_service import WorkerTurnInput
    from apps.api.lifetime_memory_lane_engine import lane_contract, build_bounded_lane_input
    from apps.api.prompt_catalog import PROMPT_PATHS
    from test_lifetime_memory_lane_engine import page, BUDGET
    assert 'memoir-interview-guidance' not in SKILLS
    assert 'memoir/skills/interview-guidance/instructions' not in PROMPT_PATHS
    current=page('guidance')
    with pytest.raises(ValueError):
        build_bounded_lane_input(current,phase='guidance',packet={},budget=BUDGET)
    with pytest.raises(ValueError,match='Unsupported lane phase'):
        lane_contract('guidance','en-AU')
    with pytest.raises(ValueError):
        WorkerTurnInput(user_id=current['user_id'],project_id=current['project_id'],
            agent_role='interview_guidance')


def test_ready_research_without_a_guidance_selection_is_not_a_question():
    from apps.api.conversation_reply import reply_schema
    from test_historical_news import ready_context
    assert 'hint' not in reply_schema(dict(ready_context(),two_lane_memory=True))['properties']


def test_unique_original_quotes_repair_model_offset_counts_without_guessing_repeated_passages():
    current=context()
    raw=result('clarification')
    raw['signals'][0]['source_refs'][0].update(char_start=0,char_end=999)
    raw['prepared_questions'][0].update(char_start=0,char_end=999)
    saved=validate_guidance_result(raw,current)
    ref=saved['signals'][0]['source_refs'][0]
    source=next(s for s in current['guidance_context']['source_windows'] if s['id']==ref['source_id'])
    assert source['text'][ref['char_start']:ref['char_end']]==ref['quote']
    source['text']='Ming and Ming'
    source['char_end']=len(source['text'])
    with pytest.raises(ValueError,match='one exact'):
        validate_guidance_result(raw,current)
