"""Photo discovery acceptance tests; only external HTTP and DNS are faked."""
import io
import hashlib
import http.client as http_client
import json
import socket
from urllib import request as http
from urllib.error import HTTPError
from urllib.parse import urlsplit

import httpx
import pytest
from PIL import Image

from apps.api import place_photo_browser as browser
from apps.api import place_photos as photos


@pytest.fixture
def search_world(monkeypatch):
    helper = browser._research()
    source = 'https://archive.example/photo'
    image = 'https://images.example/street.jpg'
    photo = {'@type': 'Photograph', 'name': 'Chengde street',
             'dateCreated': '1983-10-01', 'contentUrl': image}
    world = {'calls': [], 'pages': {source: '<title>Chengde archive</title>'
             + '<script type="application/ld+json">' + json.dumps(photo) + '</script>'},
             'response': {'id': 'resp_fixture', 'output': [{
                 'type': 'web_search_call', 'id': 'ws_fixture', 'status': 'completed',
                 'action': {'type': 'search', 'sources': [{'type': 'url', 'url': source}]},
             }]}}
    for key, value in {'MEMORY_SPARK_PHOTO_WEB_SEARCH': '1',
                       'MEMORY_SPARK_LLM_BASE_URL': 'https://gateway.example/v1',
                       'MEMORY_SPARK_LLM_MODEL': 'search-model',
                       'MEMORY_SPARK_LLM_API_KEY': 'fixture-private-key',
                       'FLICKR_API_KEY': 'fixture-flickr-key',
                       'GOOGLE_CSE_ID': '', 'GOOGLE_CSE_URL': ''}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k:
                        [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 443))])

    def responses(req, timeout=None):
        world['calls'].append(json.loads(req.data))
        value = world['response']
        if isinstance(value, Exception):
            raise value
        return io.BytesIO(json.dumps(value).encode())

    def source_page(self, url, max_bytes, hosts, **kwargs):
        if url not in world['pages'] and urlsplit(url).path.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
            # Fingerprinting now fetches the discovered public image as well
            # as its source page. Keep that HTTP boundary fully synthetic.
            encoded = io.BytesIO()
            color = tuple(hashlib.sha256(url.encode()).digest()[:3])
            Image.new('RGB', (8, 8), color).save(encoded, format='PNG')
            return 200, url, {'content-type': 'image/png'}, encoded.getvalue()
        value = world['pages'][url]
        if isinstance(value, Exception):
            raise value
        return 200, url, {'content-type': 'text/html; charset=utf-8'}, value.encode()

    monkeypatch.setattr(http, 'urlopen', responses)
    monkeypatch.setattr(helper.Fetcher, 'fetch', source_page)
    monkeypatch.setattr(httpx, 'get', lambda url, **kwargs:
                        httpx.Response(200, json={'stat': 'ok', 'photos': {'photo': []}},
                                       request=httpx.Request('GET', url)))
    return helper, world


def start_run(helper, tmp_path, capsys, period='1980s'):
    args = ['init', '--place', 'Chengde', '--out', str(tmp_path), '--as-of', '2026-10-04']
    if period:
        args += ['--period', period]
    assert helper.main(args) == 0
    capsys.readouterr()


def test_skill_discovers_a_source_verified_historical_photo(search_world, tmp_path, capsys):
    helper, world = search_world
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    candidate, = helper.read_json(tmp_path / 'candidates.json')
    assert summary['qualifying'] == 1
    assert candidate['scene_date']['start'] == '1983-10-01'
    assert candidate['discovery_origins'][0]['tool_call_id'] == 'ws_fixture'
    assert candidate['rights']['license_id'] == 'unknown'
    assert candidate['allowed_actions']['download'] is False
    assert (tmp_path / 'report.md').is_file()
    request, = world['calls']
    assert 'Chengde' in request['input'] and '1980' in request['input'] and '1989' in request['input']
    assert request['tool_choice'] == 'required'


def test_app_returns_photos_discovered_by_llm_search(search_world):
    _, world = search_world
    found = photos.search_place_photos('Chengde', '1980s')
    assert len(found) == 1
    assert found[0]['image_url'] == 'https://images.example/street.jpg'
    assert found[0]['date_expression'] == '1983-10-01'
    assert found[0]['discovery_origins'][0]['response_id'] == 'resp_fixture'
    assert found[0]['period_match'] == 'requested'
    assert found[0]['allowed_actions']['print'] is False


def test_skill_reuses_public_search_receipts_without_repeating_search(search_world, tmp_path, capsys):
    helper, world = search_world
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    capsys.readouterr()
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    assert len(world['calls']) == 1
    assert summary['cache'] == 'hit'
    assert summary['qualifying'] == 1
    assert 'fixture-private-key' not in ''.join(file.read_text() for file in tmp_path.rglob('*.json'))


@pytest.mark.parametrize('surface', ['skill', 'app'])
def test_an_unavailable_source_cannot_hide_sibling_photos(search_world, tmp_path, capsys, surface):
    helper, world = search_world
    world['pages']['https://archive.example/blocked'] = OSError('fixture-private-key')
    sources = world['response']['output'][0]['action']['sources']
    sources.insert(0, {'type': 'url', 'url': 'https://archive.example/blocked'})
    if surface == 'skill':
        start_run(helper, tmp_path, capsys)
        assert helper.main(['discover', '--run', str(tmp_path)]) == 0
        assert json.loads(capsys.readouterr().out)['qualifying'] == 1
    else:
        assert len(photos.search_place_photos('Chengde', '1980s')) == 1


def test_skill_dates_album_photos_from_each_caption(search_world, tmp_path, capsys):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<title>Chengde archive published 1983</title>'
        '<figure><img src="https://images.example/one.jpg"><figcaption>Chengde street 1983</figcaption></figure>'
        '<figure><img src="https://images.example/two.jpg"><figcaption>Chengde market 1985</figcaption></figure>'
        '<figure><img src="https://images.example/undated.jpg"><figcaption>Chengde street</figcaption></figure>'
        '<figure><img src="https://images.example/wrong.jpg"><figcaption>Chengdu street 1983</figcaption></figure>')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 2
    assert [item['scene_date']['start'] for item in helper.read_json(tmp_path / 'candidates.json')] == [
        '1983-01-01', '1985-01-01']


@pytest.mark.parametrize('response', [
    {'id': 'resp_fake', 'output': [{'type': 'message', 'content': [{'type': 'output_text',
        'text': 'Chengde 1983 https://archive.example/photo', 'annotations': [
            {'type': 'url_citation', 'url': 'https://archive.example/photo'}]}]}]},
    {'output': None}, [],
    {'output': [{'type': 'web_search_call', 'status': 'completed', 'id': 'ws_fake', 'action': None}]},
])
def test_skill_rejects_unproven_or_malformed_search(search_world, tmp_path, capsys, response):
    helper, world = search_world
    world['response'] = response
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 2
    assert helper.read_json(tmp_path / 'candidates.json') == []
    assert 'llm_search_' in capsys.readouterr().err


@pytest.mark.parametrize('option,value', [('--source-limit', '0'), ('--provider-timeout', '121'), ('--cache-ttl', '-1')])
def test_skill_enforces_discovery_limits_before_network_access(search_world, tmp_path, capsys, option, value):
    helper, world = search_world
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path), option, value]) == 2
    assert world['calls'] == []


def test_skill_reports_all_sources_unavailable_instead_of_no_match(search_world, tmp_path, capsys):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = OSError('fixture-private-key')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 2
    assert 'llm_sources_unavailable' in capsys.readouterr().err
    assert helper.read_json(tmp_path / 'discovery-summary.json')['status'] == 'unavailable'


def test_skill_accepts_native_citations_only_with_completed_search_receipts(search_world, tmp_path, capsys):
    helper, world = search_world
    world['response']['output'][0]['action'].pop('sources')
    world['response']['output'].append({'type': 'message', 'content': [{'type': 'output_text',
        'text': 'Ignored model claims', 'annotations': [{'type': 'url_citation',
            'url': 'https://archive.example/photo', 'title': 'Chengde 1983'}]}]})
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 1


def test_skill_never_persists_credentials_echoed_in_provider_receipts(search_world, tmp_path, capsys):
    helper, world = search_world
    world['response']['id'] = 'fixture-private-key'
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 2
    assert 'fixture-private-key' not in ''.join(file.read_text() for file in tmp_path.rglob('*') if file.is_file())


def test_app_preserves_year_precision_from_source_captions(search_world):
    _, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<figure><img src="https://images.example/street.jpg">'
        '<figcaption>Chengde street 1983</figcaption></figure>')
    found, = photos.search_place_photos('Chengde', '1980s')
    assert found['date_expression'] == '1983'
    assert found['scene_date_range']['precision'] == 'year'


@pytest.mark.parametrize('surface', ['skill', 'app'])
def test_omitted_period_finds_recent_photos_without_inheriting_history(search_world, tmp_path, capsys, surface):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = world['pages']['https://archive.example/photo'].replace(
        '1983-10-01', '2025-10-01')
    if surface == 'skill':
        start_run(helper, tmp_path, capsys, period=None)
        assert helper.main(['discover', '--run', str(tmp_path)]) == 0
        assert json.loads(capsys.readouterr().out)['qualifying'] == 1
    else:
        found, = photos.search_place_photos('Chengde')
        assert found['date_expression'] == '2025-10-01'
    assert '1983' not in world['calls'][0]['input']


@pytest.mark.parametrize('gateway_error', [
    HTTPError('https://gateway.example/v1/responses', 400, 'fixture-private-key', None, None),
    http_client.BadStatusLine('fixture-private-key'),
], ids=['http_status', 'protocol'])
def test_app_keeps_catalogue_results_when_gateway_rejects_search(search_world, monkeypatch, gateway_error):
    _, world = search_world
    world['response'] = gateway_error
    record = {'id': 'https://www.loc.gov/item/fixture/', 'title': 'Chengde street photograph',
              'date': '1983', 'image_url': ['https://tile.loc.gov/fixture.jpg'],
              'item': {'medium': ['photograph'], 'rights': ['No known restrictions on publication']}}
    def catalogues(url, **kwargs):
        data = {'results': [record]} if 'loc.gov' in url else {'stat': 'ok', 'photos': {'photo': []}}
        return httpx.Response(200, json=data, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', catalogues)
    found, = photos.search_place_photos('Chengde', '1980s')
    assert found['asset_id'] == 'loc-fixture'


def test_app_accepts_a_dated_candidate_for_unspecified_historical_period(search_world):
    _, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<figure><img src="https://images.example/street.jpg">'
        '<figcaption>Chengde street 1983</figcaption></figure>')
    found, = photos.search_place_photos('Chengde', 'historical')
    assert found['date_expression'] == '1983'
    assert found['scene_date_range']['precision'] == 'year'


def test_app_keeps_catalogue_results_when_source_protocol_fails(search_world, monkeypatch):
    _, world = search_world
    world['pages']['https://archive.example/photo'] = http_client.IncompleteRead(b'partial')
    record = {'id': 'https://www.loc.gov/item/fixture/', 'title': 'Chengde street photograph',
              'date': '1983', 'image_url': ['https://tile.loc.gov/fixture.jpg'],
              'item': {'medium': ['photograph'], 'rights': ['No known restrictions on publication']}}
    def catalogues(url, **kwargs):
        data = {'results': [record]} if 'loc.gov' in url else {'stat': 'ok', 'photos': {'photo': []}}
        return httpx.Response(200, json=data, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', catalogues)
    found, = photos.search_place_photos('Chengde', '1980s')
    assert found['asset_id'] == 'loc-fixture'


def test_search_is_opt_in_and_sends_no_llm_requests_when_disabled(search_world, tmp_path, capsys, monkeypatch):
    helper, world = search_world
    monkeypatch.setenv('MEMORY_SPARK_PHOTO_WEB_SEARCH', '0')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 2
    assert photos.search_place_photos('Chengde', '1980s') == []
    assert world['calls'] == []


def test_skill_excludes_authenticated_image_urls(search_world, tmp_path, capsys):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = world['pages']['https://archive.example/photo'].replace(
        'street.jpg', 'street.jpg?token=private-credential')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 0
    assert helper.read_json(tmp_path / 'candidates.json') == []


def test_app_reports_source_outages_as_unavailable(search_world):
    _, world = search_world
    world['pages']['https://archive.example/photo'] = OSError('fixture-private-key')
    with pytest.raises(photos.PhotoResearchUnavailable) as failure:
        photos.search_place_photos('Chengde', '1980s')
    assert {'provider': 'llm_web_search', 'reason': 'source_unavailable'} in failure.value.failures


def test_resuming_a_run_does_not_count_wrong_period_alternatives(search_world, tmp_path, capsys):
    helper, _ = search_world
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    capsys.readouterr()
    candidate, = helper.read_json(tmp_path / 'candidates.json')
    candidate['id'] = 'fixture-alternative'
    candidate['image_url'] = 'https://images.example/alternative.jpg'
    candidate['scene_date'].update(start='1993-10-01', end='1993-10-01')
    helper.write_json(tmp_path / 'candidates.json', [candidate])
    request = helper.read_json(tmp_path / 'request.json')
    request['count'] = 1
    helper.write_json(tmp_path / 'request.json', request)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 1
    assert len(helper.read_json(tmp_path / 'candidates.json')) == 2


def test_skill_preserves_documented_capture_ranges(search_world, tmp_path, capsys):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<figure><img src="https://images.example/street.jpg">'
        '<figcaption>Chengde street 1982-1985</figcaption></figure>')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    candidate, = helper.read_json(tmp_path / 'candidates.json')
    assert (candidate['scene_date']['start'], candidate['scene_date']['end'], candidate['scene_date']['precision']) == (
        '1982-01-01', '1985-12-31', 'range')


def test_skill_keeps_verified_photos_when_page_budget_is_exhausted(search_world, tmp_path, capsys):
    helper, world = search_world
    world['response']['output'][0]['action']['sources'].append({'url': 'https://archive.example/second'})
    start_run(helper, tmp_path, capsys)
    request = helper.read_json(tmp_path / 'request.json')
    request['budgets']['max_pages'] = 1
    helper.write_json(tmp_path / 'request.json', request)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 1
    assert len(helper.read_json(tmp_path / 'candidates.json')) == 1


@pytest.mark.parametrize('source_kind', ['json', 'figure'])
def test_skill_excludes_conflicting_caption_and_capture_dates(search_world, tmp_path, capsys, source_kind):
    helper, world = search_world
    if source_kind == 'json':
        world['pages']['https://archive.example/photo'] = world['pages']['https://archive.example/photo'].replace(
            'Chengde street', 'Chengde street 1920; date: 1983-10-01')
    else:
        world['pages']['https://archive.example/photo'] = (
            '<figure><img src="https://images.example/street.jpg">'
            '<figcaption>Chengde street 1920; date: 1983-10-01</figcaption></figure>')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 0


def test_skill_excludes_multiple_exact_capture_dates_in_one_caption(search_world, tmp_path, capsys):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<figure><img src="https://images.example/street.jpg">'
        '<figcaption>Chengde street taken 1983-01-01; taken 1983-10-01</figcaption></figure>')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 0


def test_skill_accepts_a_dated_candidate_for_unspecified_historical_period(search_world, tmp_path, capsys):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<figure><img src="https://images.example/street.jpg">'
        '<figcaption>Chengde street 1983</figcaption></figure>')
    start_run(helper, tmp_path, capsys, period='historical')
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    candidate, = helper.read_json(tmp_path / 'candidates.json')
    assert summary['qualifying'] == 1
    assert candidate['scene_date']['start'] == '1983-01-01'


def test_skill_reads_photo_metadata_with_multiple_schema_types(search_world, tmp_path, capsys):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = world['pages']['https://archive.example/photo'].replace(
        '"@type": "Photograph"', '"@type": ["Photograph", "ImageObject"]')
    start_run(helper, tmp_path, capsys)
    assert helper.main(['discover', '--run', str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)['qualifying'] == 1


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('field', ['name', 'caption', 'description', 'dateTaken'])
def test_all_image_fields_reconcile_exact_capture_dates(search_world, tmp_path, capsys, surface, field):
    helper, world = search_world
    record = {'@type': 'Photograph', 'name': 'Chengde street',
              'dateCreated': '1983-10-01', 'contentUrl': 'https://images.example/street.jpg',
              field: '1983-01-01' if field == 'dateTaken' else 'Chengde street taken 1983-01-01'}
    world['pages']['https://archive.example/photo'] = (
        '<script type="application/ld+json">' + json.dumps(record) + '</script>')
    if surface == 'skill':
        start_run(helper, tmp_path, capsys)
        assert helper.main(['discover', '--run', str(tmp_path)]) == 0
        assert json.loads(capsys.readouterr().out)['qualifying'] == 0
        assert helper.read_json(tmp_path / 'candidates.json') == []
    else:
        assert photos.search_place_photos('Chengde', '1980s') == []


def set_image_metadata(world, fields):
    record = {'@type': 'Photograph', 'name': 'Chengde street',
              'contentUrl': 'https://images.example/street.jpg', **fields}
    world['pages']['https://archive.example/photo'] = (
        '<script type="application/ld+json">' + json.dumps(record) + '</script>')


def discover_image_metadata(helper, tmp_path, capsys, surface):
    if surface == 'skill':
        start_run(helper, tmp_path, capsys)
        assert helper.main(['discover', '--run', str(tmp_path)]) == 0
        summary = json.loads(capsys.readouterr().out)
        found = helper.read_json(tmp_path / 'candidates.json')
        assert summary['qualifying'] == len(found)
        return found
    return photos.search_place_photos('Chengde', '1980s')


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('fields', [
    {'dateCreated': '1983-10-01', 'caption': 'Chengde street taken 1920'},
    {'dateCreated': '1983-10-01', 'description': 'Chengde street taken 1920'},
    {'dateTaken': '1983-10-01', 'dateCreated': '1920-01-01'},
    {'dateTaken': '1920-01-01', 'dateCreated': '1983-10-01'},
    {'name': 'Chengde street 1983', 'caption': 'Taken 1982', 'dateCreated': '1983-10-01'},
    {'name': 'Chengde street 1983', 'description': 'Taken 1982', 'dateCreated': '1983-10-01'},
    {'caption': 'Taken 1983-01-01', 'description': 'Taken 1983-10-01'},
    {'dateCreated': '1983', 'caption': 'Taken 1983-01-01; taken 1983-10-01'},
    {'dateCreated': '1983', 'description': 'Taken 1982-1984; taken 1920'},
    {'dateCreated': '1983-02-30'},
    {'dateCreated': 'circa 1983'},
    {'dateCreated': '1983', 'caption': 'Chengde street circa 1982'},
    {'dateCreated': '1983', 'dateTaken': 'unknown'},
    {'datePublished': '1983-10-01', 'uploadDate': '1983-10-01'},
    {'caption': 'Chengde street published 1983-10-01'},
    {},
], ids=['caption-cross-year', 'description-cross-year', 'metadata-cross-year', 'metadata-reverse',
        'name-caption', 'name-description', 'caption-description', 'multiple-exact-dates',
        'range-and-conflict', 'invalid-day', 'circa', 'uncertain-caption', 'unknown-capture-field',
        'publication-upload-only', 'publication-caption-only', 'missing'])
def test_image_metadata_conflicts_or_uncertainty_are_not_verified(search_world, tmp_path, capsys, surface, fields):
    helper, world = search_world
    set_image_metadata(world, fields)
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('fields,expected', [
    ({'dateCreated': '1983-10-01', 'dateTaken': '1983-10-01',
      'caption': 'Chengde street 1983', 'description': 'Taken 1983-10-01'},
     ('1983-10-01', '1983-10-01', 'day')),
    ({'dateCreated': '1983', 'caption': 'Chengde street taken 1983-10-01'},
     ('1983-10-01', '1983-10-01', 'day')),
    ({'caption': 'Chengde street 1983'}, ('1983-01-01', '1983-12-31', 'year')),
    ({'description': 'Chengde street 1982-1985'}, ('1982-01-01', '1985-12-31', 'range')),
    ({'dateCreated': '1982-1985', 'caption': 'Chengde street 1983'},
     ('1983-01-01', '1983-12-31', 'year')),
    ({'dateCreated': '1983-10-01', 'caption': 'Chengde street 1983-10-01; taken 1983-10-01'},
     ('1983-10-01', '1983-10-01', 'day')),
    ({'dateCreated': '1983-10-01', 'datePublished': '2025-01-01', 'uploadDate': '2026-01-01'},
     ('1983-10-01', '1983-10-01', 'day')),
    ({'dateCreated': '1983-10-01', 'description': 'Published 2025-01-01'},
     ('1983-10-01', '1983-10-01', 'day')),
], ids=['consistent-fields', 'narrow-to-day', 'ordinary-caption', 'documented-range',
        'narrow-range-to-year', 'identical-assertions', 'separate-publication-fields', 'publication-description'])
def test_consistent_image_metadata_keeps_precision_and_provenance(search_world, tmp_path, capsys, surface, fields, expected):
    helper, world = search_world
    set_image_metadata(world, fields)
    found, = discover_image_metadata(helper, tmp_path, capsys, surface)
    scene = found['scene_date'] if surface == 'skill' else found['scene_date_range']
    assert (scene['start'], scene['end'], scene['precision']) == expected
    assert scene['conflicting'] is False
    assert scene['basis'] == ('provider_date_taken' if fields.keys() & {'dateTaken', 'dateCreated'}
                              else 'source_caption')
    if surface == 'skill':
        evidence = [json.loads(line) for line in (tmp_path / 'evidence.jsonl').read_text().splitlines()]
        excerpt = next(row['excerpt'] for row in evidence if row['kind'] == 'scene_date')
    else:
        excerpt = found['location_evidence']
    for field, value in {'name': 'Chengde street', **fields}.items():
        assert f'{field}: {value}' in excerpt
    assert found['allowed_actions']['download'] is False


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('caption', [
    'Chengde street taken 1920; taken 1983-10-01',
    'Chengde street taken 1983-01-01; taken 1983-10-01',
])
def test_figure_conflicts_stay_excluded_on_both_interfaces(search_world, tmp_path, capsys, surface, caption):
    helper, world = search_world
    world['pages']['https://archive.example/photo'] = (
        '<figure><img src="https://images.example/street.jpg">'
        '<figcaption>' + caption + '</figcaption></figure>')
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('captured', ['2025-10-01', '2099-10-01'])
def test_unspecified_history_excludes_recent_and_future_photos(search_world, tmp_path, capsys, surface, captured):
    helper, world = search_world
    set_image_metadata(world, {'dateCreated': captured})
    if surface == 'skill':
        start_run(helper, tmp_path, capsys, period='historical')
        assert helper.main(['discover', '--run', str(tmp_path)]) == 0
        assert json.loads(capsys.readouterr().out)['qualifying'] == 0
    else:
        assert photos.search_place_photos('Chengde', 'historical') == []


def test_public_app_deduplicates_llm_and_catalogue_images(search_world, monkeypatch):
    _, world = search_world
    record = {'id': 'https://www.loc.gov/item/fixture/', 'title': 'Chengde street photograph',
              'date': '1983', 'image_url': ['https://images.example/street.jpg'],
              'item': {'medium': ['photograph'], 'rights': ['No known restrictions on publication']}}
    def catalogues(url, **kwargs):
        data = {'results': [record]} if 'loc.gov' in url else {'stat': 'ok', 'photos': {'photo': []}}
        return httpx.Response(200, json=data, request=httpx.Request('GET', url))
    monkeypatch.setattr(httpx, 'get', catalogues)
    found, = photos.search_place_photos('Chengde', '1980s')
    assert found['image_url'] == 'https://images.example/street.jpg'


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('fields,expected', [
    ({'dateCreated': '1983-10', 'caption': 'Chengde street taken 1983-01'}, None),
    ({'dateCreated': '1983-10-01', 'caption': 'Chengde street taken 1983-01'}, None),
    ({'dateCreated': '1983-10', 'caption': 'Chengde street 1983'}, ('1983-10-01', '1983-10-31', 'month')),
    ({'dateCreated': '1983-10', 'caption': 'Chengde street taken 1983-10-15'}, ('1983-10-15', '1983-10-15', 'day')),
])
def test_month_precision_cannot_hide_capture_conflicts(search_world, tmp_path, capsys, surface, fields, expected):
    helper, world = search_world
    set_image_metadata(world, fields)
    found = discover_image_metadata(helper, tmp_path, capsys, surface)
    if expected is None:
        assert found == []
    else:
        photo, = found
        scene = photo['scene_date'] if surface == 'skill' else photo['scene_date_range']
        assert (scene['start'], scene['end'], scene['precision']) == expected
        if surface == 'app' and expected[2] == 'month':
            assert photo['date_expression'] == '1983-10'
