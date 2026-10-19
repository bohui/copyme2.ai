"""Drive real production orchestration through the evaluation CLI seam."""
import asyncio
from copy import deepcopy

import pytest

from scripts import memoir_skill_eval_suite as suite


class HistoryFixture:
    def __init__(self):
        self.requests = []

    async def call(self, request):
        self.requests.append(deepcopy(request))
        assert 'gold' not in request and 'expected' not in request
        from scripts.memoir_live_skill_cases import scenario_cases
        fixture = next(c['task']['service_fixture'] for c in scenario_cases() if c['id'] == request['item_id'])
        if request['kind'] == 'discovery':
            assert 'Alex' not in request['input']['public_query']
            output = deepcopy(fixture['discovery'])
        else:
            if fixture['unavailable_sources']: raise OSError('controlled source outage')
            output = deepcopy(fixture['pages'][request['input']['url']])
        return dict(output=output, response_id='service-fixture', model=None, usage=None)


def test_historical_production_discovery_inspection_privacy_and_budget(tmp_path):
    provider = HistoryFixture()
    planned = suite.plan(skill=['memoir-historical-news-research'], case=[
        'memoir-historical-news-research/private-query/en-AU'])
    receipt = asyncio.run(suite.run(planned, tmp_path, history_provider=provider, max_skill_calls=3))
    row, = receipt['results']
    assert row['execution'] == 'completed' and row['contract']['status'] == 'pass'
    assert row['output']['clues'][0]['evidence_status'] == 'inspected'
    assert all('Alex' not in q for q in row['witnesses']['queries'])
    assert receipt['budgets']['skill']['dispatched'] == len(provider.requests) == 3
    assert row['output']['accounting']['cost'] is None
    assert row['quality']['status'] == 'unavailable'


@pytest.mark.parametrize('case', ['inspected-source', 'private-query', 'personal-separation', 'conflicting-sources',
                                  'publication-date', 'unsupported-claim', 'unavailable-source', 'prompt-injection'])
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_historical_adversarial_fixtures_exercise_real_source_validation(tmp_path, case, locale):
    provider = HistoryFixture()
    receipt = asyncio.run(suite.run(suite.plan(case=[f'memoir-historical-news-research/{case}/{locale}']),
        tmp_path, history_provider=provider))
    row, = receipt['results']
    assert row['contract']['status'] == ('unavailable' if case == 'unavailable-source' else 'pass'), row
    if case in {'conflicting-sources', 'publication-date', 'unsupported-claim'}:
        assert row['output']['clues'] == []
        assert not row['positive_delivery']
    if case == 'prompt-injection':
        assert 'Ignore the rubric' in row['witnesses']['inspected_pages'][0]['text']
        assert 'Ignore the rubric' not in row['output']['clues'][0]['summary']


def test_historical_uninspected_lead_does_not_pass(tmp_path):
    class Uninspected(HistoryFixture):
        async def call(self, request):
            result = await super().call(request)
            if request['kind'] == 'inspect': result['output']['text'] = 'Unrelated page.'
            return result
    receipt = asyncio.run(suite.run(suite.plan(case=[
        'memoir-historical-news-research/inspected-source/en-AU']), tmp_path,
        history_provider=Uninspected()))
    assert receipt['results'][0]['contract']['status'] == 'fail'
    assert not receipt['results'][0]['positive_delivery']


@pytest.mark.parametrize('case', ['first-checkpoint', 'preserve-unchanged', 'new-evidence',
                                  'corrected-event', 'withdrawal', 'independent-review', 'publication-boundary'])
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_composer_production_checkpoint_uses_external_model_fixture(tmp_path, case, locale):
    from test_progressive_composer import draft_all
    class Composer:
        async def call(self, request):
            payload = request['input']['payload']
            if request['phase'] == 'prepare':
                partition = payload['partition']
                output = dict(event_id=partition['id'], context='Original bicycle memories.', source_refs=partition['source_refs'])
            elif request['phase'] == 'draft': output = draft_all(payload)
            else: output = dict(ready_for_user_review=True, publication_approved=False, findings=[])
            return dict(output=output, response_id='composer-fixture', model='controlled-model', usage=None)
    receipt = asyncio.run(suite.run(suite.plan(case=[
        'memoir-composer/' + case + '/' + locale]), tmp_path, composer_provider=Composer(), max_skill_calls=12))
    row, = receipt['results']
    assert row['contract']['status'] == 'pass', row
    assert row['witnesses']['checkpoint_count'] == (2 if case in {'preserve-unchanged', 'new-evidence', 'corrected-event', 'withdrawal'} else 1)
    assert row['witnesses']['persisted_canonical_state'] is False
    assert row['witnesses']['browser_observed'] is False
    assert receipt['budgets']['skill']['dispatched'] > 0


def test_empty_composer_checkpoint_uses_no_model(tmp_path):
    class Forbidden:
        async def call(self, request): raise AssertionError('empty checkpoint dispatched a model')
    receipt = asyncio.run(suite.run(suite.plan(case=[
        'memoir-composer/empty-checkpoint/en-AU']), tmp_path, composer_provider=Forbidden()))
    row, = receipt['results']
    assert row['contract']['status'] == 'pass', row
    assert not row['positive_delivery']
    assert receipt['budgets']['skill']['dispatched'] == 0


class PhotoFixture:
    async def call(self, request):
        import json
        if request['kind'] == 'discovery':
            output = dict(provider='configured_catalogue', status='completed', urls=['https://archive.example/photo'])
        else:
            photo = dict(**{'@type': 'Photograph'}, dateCreated='1983-10-01',
                contentUrl='https://images.example/street.jpg', creator=dict(name='Synthetic Photographer'))
            output = dict(url=request['input']['url'], html='<title>Sydney street</title><script type="application/ld+json">'
                          + json.dumps(photo) + '</script>')
        return dict(output=output, response_id=None, model=None, usage=None)


def test_configured_photo_discovery_needs_no_native_model_search(tmp_path):
    receipt = asyncio.run(suite.run(suite.plan(case=[
        'memoir-place-photo-research/capture-period/en-AU']), tmp_path, photo_provider=PhotoFixture()))
    row, = receipt['results']
    assert row['contract']['status'] == 'pass', row
    assert row['witnesses']['provider'] == 'configured_catalogue'
    assert row['output']['items'][0]['allowed_actions']['publish'] is False
    assert receipt['budgets']['skill']['dispatched'] == 2
    assert all(c['model'] is None for c in receipt['budgets']['skill']['calls'])


def test_photo_without_capture_evidence_cannot_pass(tmp_path):
    class UploadDate(PhotoFixture):
        async def call(self, request):
            result = await super().call(request)
            if request['kind'] == 'inspect':
                result['output']['html'] = result['output']['html'].replace('dateCreated', 'uploadDate')
            return result
    receipt = asyncio.run(suite.run(suite.plan(case=[
        'memoir-place-photo-research/capture-period/en-AU']), tmp_path, photo_provider=UploadDate()))
    assert receipt['results'][0]['contract']['status'] == 'fail'
    assert not receipt['results'][0]['positive_delivery']


def test_place_extraction_is_embedded_in_one_real_timeline_packet(tmp_path):
    from scripts.memoir_skill_scenarios import place
    requests = []
    class Timeline:
        async def call(self, request):
            requests.append(request)
            assert request['skill'] == 'memoir-author-timeline'
            assert request['execution'] == 'embedded'
            assert 'window_contract' in request['input']
            assert 'gold' not in request and 'rubric' not in request
            places = [place('Sydney', 'en-AU'), place('Perth', 'en-AU')]
            return dict(output=dict(events=[], place_journeys=places, prepared_questions=[]),
                        response_id='timeline-fixture', model='controlled-model', usage=None)
    receipt = asyncio.run(suite.run(suite.plan(case=[
        'memoir-place-journey/two-cities/en-AU']), tmp_path, skill=Timeline()))
    assert receipt['results'][0]['contract']['status'] == 'pass', receipt['results'][0]
    assert len(requests) == receipt['budgets']['skill']['dispatched'] == 1
