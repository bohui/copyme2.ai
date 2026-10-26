"""Run retired combined-output fixtures through the two real native writers.

Old question-consumption tests still describe fixed extractor outputs. Adapt
those fixtures at the test boundary: commit facts, finish source extraction, then
publish the same grounded hints through the independent guidance lane. Product
code never accepts the retired combined output.
"""
import json
import re

from test_lifetime_composer_capacity import service as canonical_service
from test_shared_memory_events_postgres import literal
from controlled_interview_guidance import from_legacy_questions


def finish_timeline(sql,page):
    current=canonical_service(sql,'read_lifetime_memoir_lane_page',f"'{page['lane_id']}','{page['token']}'")
    for _ in range(64):
        if current['complete']:
            break
        result=dict(events=[],place_journeys=[])
        if (current.get('two_lane') or {}).get('reply_contract')=='reply-v2':result['continuity_updates']=[]
        canonical_service(sql,'commit_lifetime_memoir_lane_page',f"'{page['lane_id']}','{page['token']}',{current['page_number']},{literal(result)}")
        current=canonical_service(sql,'read_lifetime_memoir_lane_page',f"'{page['lane_id']}','{page['token']}'")
    else:raise AssertionError('Controlled timeline fixture exceeded page bound')
    canonical_service(sql,'complete_lifetime_memoir_lane',f"'{page['lane_id']}','{page['token']}'")


def publish(sql,page,questions,proposal=None):
    finish_timeline(sql,page)
    return publish_questions(sql,page,{page['source']['id']:questions},proposal)


def publish_questions(sql,page,by_source,proposal=None):
    """Publish a fresh guidance decision without re-extracting old sources."""
    lane=sql(f"select id from public.user_memoir_lane where user_id='{page['user_id']}' and project_id={literal(page['project_id'])} and skill='guidance';").stdout.strip()
    assert lane, 'Finish canonical extraction before publishing guidance'
    sql(f"update public.user_memoir_lane set pending=true,guidance_revision=guidance_revision+1,available_at=clock_timestamp() where id='{lane}';")
    guided=canonical_service(sql,'claim_memoir_lane',f"'{lane}',300")
    assert guided, 'Controlled guidance fixture must have an independent claim'
    result=from_legacy_questions(guided,by_source)
    result['strategy_proposal']=proposal
    saved=canonical_service(sql,'commit_lifetime_interview_guidance',f"'{lane}','{guided['token']}',{literal(guided['page_digest'])},{literal(result)}")
    sql.guidance_publication=(guided,result)
    return saved


def service(sql,name,args):
    if name!='commit_lifetime_memoir_lane_page':return canonical_service(sql,name,args)
    match=re.search(r",'((?:[^']|'')*)'$",args)
    raw=json.loads(match.group(1).replace("''", "'")) if match else {}
    if not {'prepared_questions','strategy_proposal'} & raw.keys():return canonical_service(sql,name,args)
    lane,token=re.findall(r"'([^']*)'",args)[:2]
    page=sql.lifetime_observed_pages[(lane,token)]
    questions=raw.pop('prepared_questions',[]);proposal=raw.pop('strategy_proposal',None)
    saved=canonical_service(sql,name,args[:match.start(1)]+literal(raw)[1:-1]+args[match.end(1):])
    if not saved.get('replayed') and questions:
        publish(sql,page,questions,proposal)
    return saved


def publish_ready_news(sql,identity,language='en-AU'):
    """Complete the fixed source fixture and publish an explicit B relevance choice."""
    from apps.api.historical_news import HISTORICAL_INVITATIONS
    from test_shared_memory_events_postgres import rpc
    lane=sql(f"select id from public.user_memoir_lane where project_id={literal(identity['project_id'])} and skill='timeline';").stdout.strip()
    page=canonical_service(sql,'claim_memoir_lane',f"'{lane}',300")
    assert page
    clues=rpc(sql,'read_user_historical_news',literal(identity['project_id']))['clues']
    question,bridge=HISTORICAL_INVITATIONS[language]
    hints=[dict(question=question,topic='Public history',quote=page['source']['text'],scope='broader',
        trigger='historical_news',historical_clue_id=clue['id'],bridge=bridge) for clue in clues]
    result=dict(events=[],place_journeys=[],prepared_questions=hints)
    if (page.get('two_lane') or {}).get('reply_contract')=='reply-v2':result['continuity_updates']=[]
    return service(sql,'commit_lifetime_memoir_lane_page',f"'{lane}','{page['token']}',{page['page_number']},{literal(result)}")
