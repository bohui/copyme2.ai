"""Narrated public event places remain detailed through extraction and the map."""
from copy import deepcopy

import pytest

from apps.api.memory_events import validate_extraction
from apps.api.place_journey import validate_place_journey

CITY = dict(place='承德市', hierarchy=['Earth','中国','河北省','承德市'], granularity='city')
HOSPITAL = dict(place='承德市附属医院', hierarchy=[*CITY['hierarchy'],'承德市附属医院'], granularity='landmark')
TOWN = dict(place='大石庙镇', hierarchy=[*CITY['hierarchy'],'大石庙镇'], granularity='suburb')


@pytest.mark.parametrize('location', [HOSPITAL,TOWN])
def test_narrated_event_uses_detailed_named_location(location):
    text=f"我小时候在{location['place']}。"
    ref=dict(source_id='original',version=1,quote=text)
    event=dict(kind='event',title=text,source_refs=[ref],location=location,
               location_basis=[ref],locationConfidenceScore=.95)
    accepted=validate_extraction(dict(events=[event]),[dict(id='original',version=1,text=text)],[])
    assert accepted[0]['location']==location
    if location['granularity']=='landmark':
        assert validate_place_journey(location) is None, 'Workspace journeys remain coarse'


@pytest.mark.parametrize('label', ['医院','学校','家属院','承德师范家属院','10 King Road'])
def test_generic_place_is_not_a_named_landmark(label):
    place=dict(place=label,hierarchy=[*CITY['hierarchy'],label],granularity='landmark')
    ref=dict(source_id='original',version=1,quote=f'我在{label}。')
    event=dict(kind='event',title='小时候',source_refs=[ref],location=place,location_basis=[ref],locationConfidenceScore=1.)
    with pytest.raises(ValueError):
        validate_extraction(dict(events=[event]),[dict(id='original',version=1,text=ref['quote'])],[])


def test_a_detailed_place_cannot_be_invented_from_city_evidence():
    ref=dict(source_id='original',version=1,quote='我出生在承德市。')
    event=dict(kind='event',title='出生',source_refs=[ref],location=HOSPITAL,location_basis=[ref],locationConfidenceScore=.1,
               uncertainty='A guessed hospital')
    with pytest.raises(ValueError):
        validate_extraction(dict(events=[event]),[dict(id='original',version=1,text=ref['quote'])],[])

from test_conversation_attribution import Conversation, empty, episode, reference
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database  # noqa: F401


def test_detailed_places_and_later_town_clarification_replay_to_event_map(sql,tmp_path,monkeypatch):
    import json
    from pathlib import Path
    import subprocess
    from apps.api import place_groups
    from test_timeline_context_confidence import drain
    monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION','reply-v2')
    birth='我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院。'
    childhood='1988年，我在承德市学校家属院和朋友玩。'
    clarification='原来爸爸的学校叫做承德师范，当时在大石庙镇，学校建在山坡上，家属院就在学校的山脚下。'
    sydney=dict(place='悉尼',hierarchy=['Earth','澳大利亚','悉尼'],granularity='city')
    def extract(packet):
        text=packet['sources'][0]['text']
        location=HOSPITAL if text==birth else CITY if text==childhood else TOWN
        saved=next((event for event in packet['events'] if '家属院' in event['title']),None)
        event=episode(packet,text,title='在家属院和朋友玩' if text!=birth else '出生在承德市附属医院',
                      existing=saved if text not in {birth,childhood} else None)
        event.update(location=deepcopy(location),location_basis=[reference(packet,text)],locationConfidenceScore=1.,yearConfidenceScore=1.)
        if text in {birth,childhood}:
            year=1983 if text==birth else 1988
            event['temporal']=dict(expression=str(year),precision='year',year_start=year,year_end=year,basis=[reference(packet,text)])
        events=[event]
        if text==birth:
            events.append(dict(episode(packet,'现在生活在悉尼',title='现在悉尼生活'),location=sydney,
                location_basis=[reference(packet,'现在生活在悉尼')],locationConfidenceScore=1.,yearConfidenceScore=0.))
        return dict(empty(packet),events=events,event_places=[],passage_dispositions=[])
    def lookup(query,**options):
        hospital=query.startswith(HOSPITAL['place'])
        town=query.startswith(TOWN['place'])
        return dict(latitude=40.966 if hospital else 40.921 if town else -33.86,
                    longitude=117.95 if hospital else 117.962 if town else 151.2,
                    city='承德市' if hospital or town else '悉尼',country='中国' if hospital or town else '澳大利亚',
                    region='河北省' if hospital or town else '',partial_match=False)
    monkeypatch.setattr(place_groups,'search_place_details',lookup)
    conversation=Conversation(sql,tmp_path,monkeypatch,extract,family=False)
    with conversation.client:
        for text in [birth,childhood,clarification]:
            conversation.say(text,language='zh-CN');drain(conversation)
        response=conversation.client.get('/v1/story/map-events',params=dict(project_id=conversation.project))
        assert response.status_code==200,response.text
        page=response.json()
        assert len(page['events'])==3, 'The town detail must revise the childhood event, not duplicate it'
        locations={event['id']:conversation.client.get(f'/v1/story/map-events/{conversation.project}/{event["id"]}/places').json()
                   for event in page['events']}
        child=next(event for event in page['events'] if '家属院' in event['title'])
        assert child['location']==TOWN
        assert [link['place']['place'] for link in locations[child['id']]['items']]==['大石庙镇']
        grouping={}
        for location in [HOSPITAL,TOWN,sydney]:
            grouped=conversation.client.post(f'/v1/agent/places/{conversation.project}/groups',json=dict(places=[location],language='zh-CN'))
            assert grouped.status_code==200,grouped.text
            grouping[location['place']]=grouped.json()
        conversation.say('后来我们还在大石庙镇的河边捉昆虫。',language='zh-CN');drain(conversation)
        updated=conversation.client.get('/v1/story/map-events',params=dict(project_id=conversation.project)).json()
        revised=next(event for event in updated['events'] if event['id']==child['id'])
        assert revised['revision']>child['revision']
        replay=Path(__file__).parent/'js/helpers/replay-detailed-event-locations.mjs'
        result=subprocess.run(['node',str(replay)],input=json.dumps(dict(page=page,locations=locations,grouping=grouping,updated_page=updated,refresh_event_id=child['id'])),
                              text=True,capture_output=True,timeout=10)
        assert result.returncode==0,result.stdout+result.stderr
