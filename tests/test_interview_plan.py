"""Private collector result contract: no model or external HTTP needed."""
import json
import pytest

from apps.api.interview_plan import (CollectorVisibleStream, validate_collector_result,
    collector_instructions, collector_schema)

SOURCE = {'id':'source-1','version':1,'status':'active','text':'小时候还经常去离宫，这张照片就是丽正门的照片'}
PHOTO = {'photo_id':'reference:one','kind':'public_reference','title':'Generic source title','image_url':'https://images.example/one.jpg'}
CONTEXT = {'source':SOURCE,'photo_context':[PHOTO],'sources':[SOURCE],'events':[], 'plan':None,'associations':[]}


def proposal():
    return {'acknowledgement':'您确认这张照片拍的是丽正门，并回忆起小时候常去离宫。',
      'plan':{'candidates':[
        {'id':'parents','question':'那时您通常和谁一起去？','context':{'event_id':None,'photo_id':PHOTO['photo_id'],'life_stage':None,'year':None},'order':0,'bridge':''},
        {'id':'visit-detail','question':'在那里有什么特别鲜明的回忆？','context':{'event_id':None,'photo_id':PHOTO['photo_id'],'life_stage':None,'year':None},'order':1,'bridge':''}],
        'chosen_id':'parents','active_event_id':None},
      'associations':[{'photo_id':PHOTO['photo_id'],'event_id':None,'source_id':SOURCE['id'],'source_version':1,'quote':'小时候还经常去离宫，这张照片就是丽正门的照片','description':'您确认照片拍的是丽正门。','provenance':'narrator_metadata'}],
      'response_photo_ids':[PHOTO['photo_id']],'stopped':False}


def test_recognised_photo_result_renders_one_question_without_private_planning():
    result = validate_collector_result(proposal(), CONTEXT)
    assert result['reply'].count('？')==1
    assert '丽正门' in result['reply']
    assert 'visit-detail' not in result['reply']
    assert result['response_photos']==[PHOTO]
    assert result['associations'][0]['source_version']==1


@pytest.mark.parametrize('mutation', ['foreign_photo','foreign_event','wrong_source_version','fabricated_quote','pixels_not_seen','extra_question','missing_chosen','duplicate_question','too_many','unfounded_year'])
def test_untrusted_collector_cannot_forge_scope_evidence_or_visible_questions(mutation):
    p=proposal()
    if mutation=='foreign_photo':p['associations'][0]['photo_id']='upload:someone-else'
    if mutation=='foreign_event':p['associations'][0]['event_id']='event-someone-else'
    if mutation=='wrong_source_version':p['associations'][0]['source_version']=2
    if mutation=='fabricated_quote':p['associations'][0]['quote']='My parents appear in the picture'
    if mutation=='pixels_not_seen':p['associations'][0]['provenance']='visual_inspection'
    if mutation=='extra_question':p['acknowledgement']='Really? Tell me more?'
    if mutation=='missing_chosen':p['plan']['chosen_id']='gone'
    if mutation=='duplicate_question':p['plan']['candidates'][1]['question']=p['plan']['candidates'][0]['question']
    if mutation=='too_many':p['plan']['candidates']*=3
    if mutation=='unfounded_year':p['plan']['candidates'][0]['context']['year']=1934
    with pytest.raises(ValueError):validate_collector_result(p,CONTEXT)


def test_photo_only_action_can_ask_without_fabricating_testimony():
    p=proposal();p['associations']=[];p['acknowledgement']='What comes to mind when you look at this photo.'
    context={**CONTEXT,'source':None,'sources':[]}
    assert validate_collector_result(p,context)['associations']==[]
    p['associations']=proposal()['associations']
    with pytest.raises(ValueError):validate_collector_result(p,context)


def test_stop_has_no_candidates_and_no_question():
    p=proposal();p.update(stopped=True,acknowledgement='我们先休息。',associations=[],response_photo_ids=[])
    p['plan'].update(candidates=[],chosen_id=None,active_event_id=None)
    assert validate_collector_result(p,CONTEXT)['reply']=='我们先休息。'


def test_unrelated_selection_remains_a_deferred_candidate_without_association():
    p=proposal();p['associations']=[];p['acknowledgement']='You caught insects beside the gate.'
    p['plan']['candidates'][0].update(question='What did you keep them in?',context={'event_id':None,'photo_id':None,'life_stage':None,'year':None})
    p['plan']['candidates'][1].update(question='What does that earlier photo bring to mind?',bridge='You also picked a photograph earlier.')
    result=validate_collector_result(p,CONTEXT)
    assert 'What did you keep them in?' in result['reply']
    assert result['associations']==[] and result['response_photos']==[PHOTO]


def test_returning_to_another_event_requires_concrete_bridge():
    p=proposal();p['associations']=[]
    p['plan']['candidates'][0]['context']['event_id']='event-2'
    context={**CONTEXT,'events':[{'id':'event-1','status':'active'},{'id':'event-2','status':'active'}],
             'plan':{'active_event_id':'event-1'}}
    with pytest.raises(ValueError):validate_collector_result(p,context)
    p['plan']['candidates'][0]['bridge']='You mentioned moving after those visits.'
    assert 'You mentioned moving' in validate_collector_result(p,context)['reply']


def test_partial_json_never_exposes_plan_or_unselected_questions():
    raw=json.dumps(proposal(),ensure_ascii=False)
    for size in [1,2,7,41,len(raw)]:
        stream=CollectorVisibleStream();out=''
        for offset in range(0,len(raw),size):out+=stream.feed(raw[offset:offset+size])
        out+=stream.feed('',final=True)
        assert out==proposal()['acknowledgement']
        assert 'candidates' not in out and 'visit-detail' not in out


def test_stream_does_not_leak_malformed_prefix_or_acknowledgement_questions():
    for raw in ['private plan: '+json.dumps(proposal()), '{"plan":{"candidates":[]},"acknowledgement":"Hello"}', '{"acknowledgement":"Who? More?","plan":{}}']:
        assert CollectorVisibleStream().feed(raw,final=True)==''


def test_schema_and_instruction_keep_source_and_metadata_distinct():
    schema=collector_schema()
    assert schema['additionalProperties'] is False
    assert schema['properties']['plan']['$ref']
    instruction=collector_instructions(CONTEXT)
    assert 'untrusted' in instruction and 'metadata' in instruction


def test_broad_quote_cannot_bind_a_photo_to_an_unrelated_event_in_same_answer():
    p=proposal();p['associations'][0]['event_id']='residence'
    context={**CONTEXT,'events':[{'id':'residence','status':'active','source_refs':[{'source_id':SOURCE['id'],'version':1,'quote':'小时候'}]}]}
    with pytest.raises(ValueError):validate_collector_result(p,context)


def test_photo_only_cannot_bind_new_image_to_old_testimony():
    p=proposal();context={**CONTEXT,'source':None}
    with pytest.raises(ValueError):validate_collector_result(p,context)


def test_repeated_quote_cannot_resolve_event_without_occurrence_evidence():
    p=proposal();p['associations'][0].update(event_id='visit',quote='小时候')
    source={**SOURCE,'text':'小时候去了离宫。小时候住在市区。'}
    context={**CONTEXT,'source':source,'sources':[source], 'events':[{'id':'visit','status':'active','source_refs':[{'source_id':source['id'],'version':1,'quote':'小时候去了离宫'}]}]}
    with pytest.raises(ValueError):validate_collector_result(p,context)


def test_reference_capture_year_in_narrator_text_is_not_a_supported_life_year():
    p=proposal();p['associations']=[];p['plan']['candidates'][0]['context']['year']=1930
    source={**SOURCE,'text':'This public photo was taken in 1930, before I was born.'}
    with pytest.raises(ValueError):validate_collector_result(p,{**CONTEXT,'source':source,'sources':[source]})
