"""Place cues respect the same accepted passage attribution as timeline events."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import httpx
import pytest
from test_conversation_attribution import Conversation, empty, episode, reference
from test_background_profile_workflow import database
from test_lifetime_memory_postgres import sql, event_database, private_database, attachment_database  # noqa: F401

from apps.api.lifetime_memory_composer import _extract, execute_lifetime_lane
from test_lifetime_composer_capacity import page
from test_memory_context_transport import Publisher


def extract_places(monkeypatch, text, raw, *, offset=0, commit=False, chosen_name=None):
    current = page(text=text)
    current['preferences']['chosen_name'] = chosen_name
    current['source'].update(char_start=offset, char_end=offset + len(text), original_length=offset + len(text))
    current['two_lane'] = dict(schema_version=1, task_version='two-lane-v1', execution_generation=1,
        phase_revision=0, work_mode='extract', reply_contract='reply-v2')
    current['attribution_context'] = dict(schema_version=1, decision='extract', reason='new_testimony', delivered_event=None)
    original = {**current['source'], 'text':'x' * offset + text}
    calls, commits = [], []
    async def worker(request):
        calls.append(json.loads(request.content))
        output = {key:deepcopy(value) for key,value in raw.items() if key not in {'prepared_questions','strategy_proposal'}}
        def bind(value):
            if isinstance(value, dict):
                if 'source_id' in value:
                    value.update(source_id=current['source']['id'], version=current['source']['version'])
                for item in value.values(): bind(item)
            elif isinstance(value, list):
                for item in value: bind(item)
        bind(output)
        return httpx.Response(200, json=dict(thread_id='controlled-place', reply=json.dumps(output), artifacts=[]))
    class Broker:
        async def rpc(self, name, **params):
            if commit and name == 'read_lifetime_profile_page':
                return None
            if commit and name == 'commit_lifetime_memoir_lane_page':
                commits.append(deepcopy(params['p_result']))
                return {'status': 'captured_commit'}
            assert name == 'read_lifetime_lane_policy_source'
            return original
    scope = SimpleNamespace(broker=Broker(), worker_url='https://worker.invalid', worker_secret='fixture',
        worker_transport=httpx.MockTransport(worker), lane_publisher=Publisher())
    result = asyncio.run(execute_lifetime_lane(current, scope) if commit else _extract(current, scope))
    if commit:
        assert result == {'status': 'captured_commit'}
        result, = commits
    assert len(calls) == 1
    return result


def test_reported_father_place_is_not_a_narrator_map_cue(monkeypatch):
    text = '父亲说他小时候在承德修自行车。我没有做过这件事。'
    raw = dict(events=[], place_journeys=[dict(place='承德', hierarchy=['Earth','中国','河北省','承德'],
        granularity='city', latitude=None, longitude=None, research=None)], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[dict(disposition='non_story',
        reason='no_supported_event', source_ref=dict(source_id='source',version=1,quote=text,char_start=0,char_end=len(text)))])
    result = extract_places(monkeypatch, text, raw)
    assert result['events'] == []
    assert result['place_journeys'] == [], 'A non-story passage became a narrator place cue'
    assert result['passage_dispositions'][0]['source_ref']['quote'] == text


def place(label):
    return dict(place=label, hierarchy=['Earth', 'Australia' if label == 'Hobart' else '中国', label],
        granularity='city', latitude=None, longitude=None, research=None)


def ref(quote):
    return dict(source_id='source', version=1, quote=quote, char_start=None, char_end=None)


@pytest.mark.parametrize('offset', [0, 1792])
def test_research_quote_can_cross_masked_attribution(monkeypatch, offset):
    father = '父亲说他小时候在承德修自行车。'
    narrator = '后来我在承德学会了做陶器。'
    text = father + narrator
    research = dict(year_start=1980, year_end=1989, anchor_year=1983, basis='birth_decade',
        quote=text, char_start=0, char_end=len(text))
    raw = dict(events=[dict(kind='event', title='Learning pottery', source_refs=[ref(narrator)])],
        place_journeys=[dict(place='承德', hierarchy=['Earth', '中国', '河北省', '承德'],
            granularity='city', latitude=None, longitude=None, research=research)],
        prepared_questions=[], event_places=[], continuity_updates=[], passage_dispositions=[
            dict(disposition='non_story', reason='no_supported_event', source_ref=ref(father))])
    result = extract_places(monkeypatch, text, raw, offset=offset, commit=True)
    assert [place['place'] for place in result['place_journeys']] == ['承德']
    assert result['place_journeys'][0]['research']['quote'] == text
    assert result['place_journeys'][0]['research']['char_start'] == offset
    assert result['events'][0]['source_refs'][0]['quote'] == narrator


@pytest.mark.parametrize('offset', [0, 1792])
@pytest.mark.parametrize('disposition', ['withheld', 'unresolved', 'policy'])
@pytest.mark.parametrize('research_scope', ['restricted', 'crossing', 'allowed'])
def test_restricted_research_is_removed_before_commit(monkeypatch, offset, disposition, research_scope):
    restricted = 'In 1984 I lived in Hobart with a secret family.'
    control = '' if disposition == 'unresolved' else ' Do not record this event.'
    allowed = 'In 2004 I learned pottery in Hobart.'
    text = restricted + control + '\n' + allowed
    quote = {'restricted': restricted, 'crossing': text, 'allowed': allowed}[research_scope]
    start = offset + text.index(quote)
    year = 2004 if research_scope == 'allowed' else 1984
    research = dict(year_start=year, year_end=year, anchor_year=year, basis='explicit_period',
        quote=quote, char_start=start, char_end=start + len(quote))
    dispositions = [] if disposition == 'policy' else [dict(disposition=disposition,
        reason='privacy_withheld' if disposition == 'withheld' else 'uncertain_attribution',
        source_ref=ref(restricted))]
    raw = dict(events=[dict(kind='event', title='Learning pottery', source_refs=[ref(allowed)])],
        place_journeys=[{**place('Hobart'), 'research': research}], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=dispositions)
    result = extract_places(monkeypatch, text, raw, offset=offset, commit=True)
    assert [item['place'] for item in result['place_journeys']] == ['Hobart']
    assert result['events'][0]['source_refs'][0]['quote'] == allowed
    accepted = result['place_journeys'][0].get('research')
    if research_scope == 'allowed':
        assert accepted == research
    else:
        assert accepted is None, 'Restricted testimony reached the place research commit payload'


@pytest.mark.parametrize('offset', [0, 1792])
def test_repeated_allowed_research_keeps_its_own_span(monkeypatch, offset):
    quote = 'In 2004 I learned pottery in Hobart.'
    text = quote + '\n' + quote
    start = len(quote) + 1
    research = dict(year_start=2004, year_end=2004, anchor_year=2004, basis='explicit_period',
        quote=quote, char_start=offset + start, char_end=offset + len(text))
    raw = dict(events=[dict(kind='event', title='Learning pottery', source_refs=[
        dict(ref(quote), char_start=start, char_end=len(text))])],
        place_journeys=[{**place('Hobart'), 'research': research}], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[dict(disposition='unresolved',
            reason='uncertain_attribution', source_ref=dict(ref(quote), char_start=0, char_end=len(quote)))])
    result = extract_places(monkeypatch, text, raw, offset=offset, commit=True)
    assert result['place_journeys'][0]['research'] == research


@pytest.mark.parametrize('offset', [0, 1792])
def test_research_still_requires_an_exact_original_quote(monkeypatch, offset):
    text = 'In 2004 I learned pottery in Hobart.'
    quote = 'Invented Hobart testimony.'
    research = dict(year_start=2004, year_end=2004, anchor_year=2004, basis='explicit_period',
        quote=quote, char_start=offset, char_end=offset + len(quote))
    raw = dict(events=[dict(kind='event', title='Learning pottery', source_refs=[ref(text)])],
        place_journeys=[{**place('Hobart'), 'research': research}], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[dict(disposition='unresolved',
            reason='uncertain_attribution', source_ref=ref(text))])
    with pytest.raises(ValueError, match='Question evidence needs one exact passage'):
        extract_places(monkeypatch, text, raw, offset=offset, commit=True)


@pytest.mark.parametrize('offset', [0, 2048])
@pytest.mark.parametrize('same_place', [False, True])
@pytest.mark.parametrize('reported_as', ['non_story', 'event', 'evidence'])
def test_mixed_attribution_keeps_only_narrator_occurrences(monkeypatch, offset, same_place, reported_as):
    label = '承德' if same_place else 'Hobart'
    father = '🌱父亲在承德修自行车。'
    narrator = f'我在{label}学会了做陶器。'
    text = father + '\n' + narrator
    events = [dict(kind='event', title='Learning pottery', source_refs=[ref(narrator)])]
    dispositions = []
    if reported_as == 'non_story':
        dispositions.append(dict(disposition='non_story', reason='no_supported_event', source_ref=ref(father)))
    else:
        reported = dict(kind='event', title="Father's bicycle repair", source_refs=[ref(father)])
        if reported_as == 'event': reported['attribution'] = 'father'
        else: reported['source_refs'][0]['attribution'] = 'father'
        events.append(reported)
    raw = dict(events=events, place_journeys=[place('承德'), *([] if same_place else [place(label)])],
        prepared_questions=[], event_places=[], continuity_updates=[], passage_dispositions=dispositions)
    result = extract_places(monkeypatch, text, raw, offset=offset)
    assert [p['place'] for p in result['place_journeys']] == [label]
    accepted = result['events'][0]['source_refs'][0]
    assert accepted['char_start'] == offset + text.index(narrator)
    assert accepted['char_end'] == offset + len(text)


@pytest.mark.parametrize('subject', [None, 'narrator', 'self', '本人'])
def test_ordinary_narrator_place_remains_available(monkeypatch, subject):
    text = 'I learned pottery in Hobart.'
    event = dict(kind='event', title='Learning pottery', source_refs=[ref(text)])
    if subject: event['attribution'] = subject
    raw = dict(events=[event], place_journeys=[place('Hobart')], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[])
    result = extract_places(monkeypatch, text, raw)
    assert [p['place'] for p in result['place_journeys']] == ['Hobart']


@pytest.mark.parametrize('event_subject,ref_subject', [('慧博', None), (None, '慧博'), ('慧博', '慧博')])
def test_named_narrator_keeps_places_in_the_first_response(monkeypatch, event_subject, ref_subject):
    text = '我叫慧博，现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院'
    evidence = {**ref(text), 'attribution':ref_subject}
    event = dict(kind='event', title='出生于承德市', attribution=event_subject, source_refs=[evidence])
    places = [dict(place=label, hierarchy=['Earth', country, label], granularity='city',
        latitude=None, longitude=None, research=None) for label, country in [('悉尼', '澳大利亚'), ('承德市', '中国')]]
    raw = dict(events=[event], place_journeys=places, prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[])
    result = extract_places(monkeypatch, text, raw, chosen_name='慧博', commit=True)
    assert [p['place'] for p in result['place_journeys']] == ['悉尼', '承德市']


def test_profile_place_cue_does_not_require_an_event(monkeypatch):
    text = 'My hometown is Hobart.'
    raw = dict(events=[], place_journeys=[place('Hobart')], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[dict(disposition='non_story',
        reason='profile_introduction', source_ref=ref(text))])
    result = extract_places(monkeypatch, text, raw)
    assert result['events'] == []
    assert [p['place'] for p in result['place_journeys']] == ['Hobart']


@pytest.mark.parametrize('scenario', ['father_only', 'mixed', 'same_place', 'ordinary', 'named_narrator',
    'withheld_research', 'unresolved_research'])
def test_reported_places_replay_from_sql_api_to_client(sql, tmp_path, monkeypatch, scenario):
    from pathlib import Path
    import subprocess
    if scenario == 'named_narrator':
        monkeypatch.setenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', 'reply-v2')
    father = '父亲说他小时候在承德修自行车。我没有做过这件事。'
    label = '承德' if scenario == 'same_place' else 'Hobart'
    own = f'我在{label}学会了做陶器。'
    restricted_research = scenario in {'withheld_research', 'unresolved_research'}
    if restricted_research:
        father = 'In 1984 I lived in Hobart with a secret family.'
        if scenario == 'withheld_research':
            father += ' Do not record this event.'
        own = 'In 2004 I learned pottery in Hobart.'
    text = (father if scenario == 'father_only' else '我叫慧博，' + own if scenario == 'named_narrator'
        else own if scenario == 'ordinary' else father + own)
    expected = [] if scenario == 'father_only' else [label]
    def extract(packet):
        events = [] if scenario == 'father_only' else [episode(packet, own, title='Learning pottery')]
        if scenario == 'named_narrator':
            events[0]['attribution'] = events[0]['source_refs'][0]['attribution'] = '慧博'
        cues = ([place(label if restricted_research else '承德')] if scenario != 'ordinary' else [])
        if label not in [p['place'] for p in cues] and events: cues.append(place(label))
        if restricted_research:
            cues[0]['research'] = dict(year_start=2004, year_end=2004, anchor_year=2004,
                basis='explicit_period', quote=text, char_start=0, char_end=len(text))
        dispositions = [] if scenario in {'ordinary', 'named_narrator', 'withheld_research'} else [dict(
            disposition='unresolved' if scenario == 'unresolved_research' else 'non_story',
            reason='uncertain_attribution' if scenario == 'unresolved_research' else 'no_supported_event',
            source_ref=reference(packet, father))]
        return {**empty(packet), 'events':events, 'place_journeys':cues,
            'event_places':[], 'passage_dispositions':dispositions}
    conversation = Conversation(sql, tmp_path, monkeypatch, extract,
        name='慧博' if scenario == 'named_narrator' else None)
    with conversation.client:
        accepted = conversation.say(text)
        conversation.drain()
        response = conversation.client.get('/v1/story/readiness', params={'project_id':conversation.project})
        assert response.status_code == 200, response.text
        ready = response.json()
        assert [p['place'] for p in ready['derived_workspace']['places']] == expected
        if restricted_research:
            assert all(p.get('research') is None for p in ready['derived_workspace']['places'])
        coverage = conversation.attribution(accepted['accepted_source_id'])
        assert coverage['complete']
        assert len([phase for phase, _ in conversation.admissions if phase == 'extract']) == 1
        packet = dict(ready=ready, expected_places=expected, expect_no_research=restricted_research)
        replay = Path(__file__).parent/'js/helpers/replay-reported-places.mjs'
        result = subprocess.run(['node',str(replay)],input=json.dumps(packet),text=True,capture_output=True,timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize('event_subject,ref_subject', [('father','narrator'),('self','father')])
def test_conflicting_attribution_cannot_promote_a_reported_place(monkeypatch, event_subject, ref_subject):
    text = 'My father repaired bicycles in Hobart.'
    evidence = {**ref(text), 'attribution':ref_subject}
    event = dict(kind='event', title="Father's bicycle repair", attribution=event_subject, source_refs=[evidence])
    raw = dict(events=[event], place_journeys=[place('Hobart')], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[])
    assert extract_places(monkeypatch, text, raw)['place_journeys'] == []


@pytest.mark.parametrize('disposition', ['withheld', 'unresolved'])
def test_profile_reason_cannot_override_a_withheld_or_unresolved_passage(monkeypatch, disposition):
    text = 'My hometown is Hobart.'
    raw = dict(events=[], place_journeys=[place('Hobart')], prepared_questions=[],
        event_places=[], continuity_updates=[], passage_dispositions=[dict(disposition=disposition,
        reason='profile_introduction', source_ref=ref(text))])
    assert extract_places(monkeypatch, text, raw)['place_journeys'] == []


@pytest.mark.parametrize('with_city_history', [False, True])
def test_map_cards_replay_canonical_places_at_city_and_event_scale(sql, tmp_path, monkeypatch, with_city_history):
    from pathlib import Path
    import subprocess
    from apps.api import place_groups
    quotes = ['At age 6 I attended school in Newtown, Sydney.',
              'At age 25 I worked in Pyrmont, Sydney.']
    labels = ['Newtown', 'Pyrmont']
    centres = {'Newtown':(-33.898, 151.178), 'Pyrmont':(-33.872, 151.195)}
    def geocode(query, language=None):
        label = next(label for label in labels if label in query)
        latitude, longitude = centres[label]
        return dict(latitude=latitude, longitude=longitude, city='Sydney', region='New South Wales',
            country='Australia', partial_match=False)
    monkeypatch.setattr(place_groups, 'search_place_details', geocode)

    def extract(packet):
        events, links = [], []
        for index, (quote, label) in enumerate(zip(quotes, labels)):
            evidence = reference(packet, quote)
            events.append(dict(episode(packet, quote, title=['Starting school', 'My first job'][index]),
                life_stage=['childhood', 'young_adulthood'][index], stage_evidence=[evidence],
                temporal=dict(expression=f'age {[6, 25][index]}', precision='age', basis=[evidence])))
            links.append(dict(event_index=index, role='setting', source_ref=evidence,
                place=dict(place=label, hierarchy=['Earth', 'Australia', 'Sydney', label], granularity='suburb')))
        return {**empty(packet), 'events':events, 'event_places':links}

    conversation = Conversation(sql, tmp_path, monkeypatch, extract)
    with conversation.client:
        conversation.say(' '.join(quotes))
        conversation.drain()
        response = conversation.client.get('/v1/story/events', params={'project_id':conversation.project})
        assert response.status_code == 200, response.text
        events = response.json()['events']
        assert len(events) == 2, 'The controlled Lane B extraction must persist both events'
        locations = {}
        grouping = {}
        for event in events:
            response = conversation.client.get(f'/v1/story/events/{conversation.project}/{event["id"]}/places')
            assert response.status_code == 200, response.text
            locations[event['id']] = response.json()
            linked = response.json()['items'][0]['place']
            response = conversation.client.post(f'/v1/agent/places/{conversation.project}/groups',
                json={'places':[linked], 'language':'en-AU'})
            assert response.status_code == 200, response.text
            grouping[linked['place']] = response.json()
        city = dict(place='Sydney', hierarchy=['Earth', 'Australia', 'Sydney'], granularity='city',
            latitude=-33.8688, longitude=151.2093)
        # These locations are deliberately absent from saved place history.
        places = [city] if with_city_history else []
        replay = Path(__file__).parent/'js/helpers/replay-map-memory-events.mjs'
        result = subprocess.run(['node', str(replay)], input=json.dumps(dict(events=events,
            locations=locations, places=places, grouping=grouping)), text=True, capture_output=True, timeout=10)
        assert result.returncode == 0, result.stdout + result.stderr
