"""Photos and news share source-grounded coarse place/period selection."""
from copy import deepcopy

import pytest

from apps.api import historical_news as news


PLACES = [
    {'place': '悉尼', 'hierarchy': ['Earth', '澳大利亚', '悉尼'], 'granularity': 'city', 'source_sequence': 1},
    {'place': '承德市', 'hierarchy': ['Earth', '中国', '河北省', '承德市'], 'granularity': 'city', 'source_sequence': 1},
]
TEXT = '我现在生活在悉尼，但是我于1983年4月出生在河北省承德市附属医院'
# Controlled model proposal, not a host interpretation of the source string.
PLACES[1]['research'] = dict(year_start=1980, year_end=1989, anchor_year=1983,
    basis='birth_decade', quote=TEXT, char_start=0, char_end=len(TEXT))


def view(text=TEXT):
    return {'places': deepcopy(PLACES), 'sources': [
        {'id': 'source', 'version': 1, 'sequence': 1, 'status': 'active', 'text': text}], 'events': []}


def test_birth_decade_is_shared_research_context_without_dating_current_home():
    from apps.api.place_research import research_places
    value = view()
    places = research_places(value['places'], value['sources'])
    assert places[0]['research_period'] == ''
    assert places[1]['research_period'] == '1980s'
    assert places[1]['research_period_basis'] == 'birth_decade'
    assert places[1]['research_year'] == 1983
    assert places[0]['research_year'] is None
    hypothesis = news.accepted_hypothesis(value, current_year=2026)
    assert (hypothesis['place'], hypothesis['start'], hypothesis['end']) == ('承德, 中国', 1980, 1989)
    assert hypothesis['time_basis'] == 'birth_decade'
    assert all('1980–1989' in query for query in news.public_queries(hypothesis))
    assert '医院' not in str(news.public_queries(hypothesis))


def test_historical_hypothesis_requires_the_saved_country_hierarchy():
    from apps.api.place_research import research_hypothesis

    perth_scotland = {
        'place': 'Perth',
        'hierarchy': ['Earth', 'United Kingdom', 'Scotland', 'Perth'],
        'granularity': 'city',
        'research_period': '1982–1985',
        'research_period_basis': 'explicit_period',
    }
    assert research_hypothesis([perth_scotland], current_year=2026) is None

    perth_australia = {**perth_scotland,
                       'hierarchy': ['Earth', 'Australia', 'Western Australia', 'Perth']}
    hypothesis = research_hypothesis([perth_australia], current_year=2026)
    assert hypothesis['place'] == 'Perth, Australia'


@pytest.mark.parametrize('start,end,period', [(1980,1989,'1980s'),(1982,1985,'1982–1985'),(1980,1980,'1980')])
def test_fixed_normalized_window_projects_to_the_shared_search_period(start,end,period):
    from apps.api.place_research import research_places
    value = view()
    value['places'][1]['research'].update(year_start=start,year_end=end,anchor_year=start,basis='explicit_period')
    assert research_places(value['places'],value['sources'])[1]['research_period']==period


def test_withdrawn_or_unrelated_source_never_supplies_a_place_period():
    from apps.api.place_research import research_places
    value = view()
    value['sources'][0]['status'] = 'withdrawn'
    value['sources'].append({'id': 'other', 'sequence': 2, 'version': 1,
                            'status': 'active', 'text': '1980年代我住在悉尼。'})
    assert research_places(value['places'], value['sources'])[1]['research_period'] == ''


def test_skill_catalog_uses_one_place_selection_trigger():
    from apps.api.background_skills import SKILLS
    assert SKILLS['memoir-historical-news-research'].trigger == SKILLS['memoir-place-photo-research'].trigger


def test_selected_photo_request_uses_the_shared_period_and_triggers_news(monkeypatch):
    from types import SimpleNamespace
    from fastapi.testclient import TestClient
    from apps.api import agent_routes, place_photo_pages
    from apps.api.main import create_app
    from apps.api.store import MemoryStore
    from apps.api.place_research import research_places
    from test_place_photo_pages import picture

    calls = []
    class Storage:
        user_id = 'owner'
        client = SimpleNamespace(close=lambda: None)
        def memoir_project(self, project): return {'project_id': project}
        def research_places(self, project): return research_places(PLACES, view()['sources'])
        def historical_news_basis(self, project):
            return {**view(), 'news_snapshot': {'source_sequence': 1, 'context_revision': 'revision'}}
        def begin_historical_news(self, project, hypothesis, snapshot):
            calls.append(('news', hypothesis['place'], hypothesis['start'], hypothesis['end']))
            return {'id': 'job'}
        def finish_historical_news(self, *args): return True

    async def run(self, hypothesis): return {'status': 'empty', 'clues': []}
    def search(place, period, **kwargs):
        calls.append(('photos', place, period))
        return [picture(1980, date_expression='1980'), picture(1983, date_expression='1983')]
    monkeypatch.setenv('MEMORY_SPARK_HISTORICAL_NEWS', '1')
    monkeypatch.delenv('MEMORY_SPARK_PHOTO_WORKER_URL', raising=False)
    monkeypatch.delenv('MEMOIR_PUBLICATION_DATABASE_URL', raising=False)
    monkeypatch.setattr(agent_routes, 'authenticated_storage', lambda *a: Storage())
    monkeypatch.setattr(place_photo_pages, 'search_place_photos', search)
    monkeypatch.setattr(news.HistoricalResearch, 'run', run)
    with TestClient(create_app(MemoryStore())) as client:
        response = client.get('/v1/agent/places/project/photos', params={'place': '承德市'})
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['date_expression'] == '1983'
    assert calls[0] == ('photos', '承德市', '1980s')
    assert ('news', '承德, 中国', 1980, 1989) in calls
