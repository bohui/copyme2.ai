"""Public CLI/app regressions from independent review; only HTTP/DNS are faked."""
import json
import pytest
from test_llm_place_photos import search_world, discover_image_metadata, set_image_metadata

@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('fields', [{'dateCreated': '1983-10-01', 'caption': 'Chengde street; capture date unknown'}, {'caption': 'Chengde street, probably taken 1983'}, {'caption': 'Chengde street, taken 1983?'}, {'dateCreated': '1983-10-01', 'caption': 'Chengde street taken 1983-1-1'}, {'caption': 'Chengde street; digitized 1983'}], ids=['unknown-caption', 'probably', 'question-mark', 'nonpadded-conflict', 'digitized-only'])
def test_uncertain_or_non_capture_assertions_are_excluded(search_world, tmp_path, capsys, surface, fields):
    helper, world = search_world
    set_image_metadata(world, fields)
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []

@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('fields', [{'dateCreated': '1983-10-01', 'description': 'Chengde street. Published 2025-01-01'}, {'dateCreated': '1983-10-01', 'caption': 'Chengde street taken 1983-10-01; published 2025-01-01'}], ids=['publication-prefix', 'capture-and-publication'])
def test_publication_clauses_do_not_erase_valid_capture_evidence(search_world, tmp_path, capsys, surface, fields):
    helper, world = search_world
    set_image_metadata(world, fields)
    assert len(discover_image_metadata(helper, tmp_path, capsys, surface)) == 1

@pytest.mark.parametrize('surface', ['skill', 'app'])
def test_bad_jsonld_source_keeps_sibling(search_world, tmp_path, capsys, surface):
    helper, world = search_world
    world['pages']['https://archive.example/bad'] = '<script type="application/ld+json">' + json.dumps({'@graph': None}) + '</script>'
    world['response']['output'][0]['action']['sources'].insert(0, {'url': 'https://archive.example/bad'})
    assert len(discover_image_metadata(helper, tmp_path, capsys, surface)) == 1

@pytest.mark.parametrize('surface', ['skill', 'app'])
def test_duplicate_image_assertions_conflict(search_world, tmp_path, capsys, surface):
    helper, world = search_world
    records = [{'@type': 'Photograph', 'name': 'Chengde street', 'contentUrl': 'https://images.example/street.jpg', 'dateCreated': day} for day in ['1983-01-01', '1983-10-01']]
    world['pages']['https://archive.example/photo'] = '<script type="application/ld+json">' + json.dumps(records) + '</script>'
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []

@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('caption', ['Chengde street, likely taken 1983', 'Chengde street taken about 1983', 'Chengde street; published 2025; probably taken 1983', 'Chengde street; published 2025, probably taken 1983', 'Chengde street; taken ca. 1983', 'Chengde street; taken 1983-123-1', 'Chengde street; taken 1983-Q1'])
def test_uncertainty_and_unsupported_precision_do_not_degrade_to_year(search_world, tmp_path, capsys, surface, caption):
    helper, world = search_world
    set_image_metadata(world, {'caption': caption})
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []

@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('fields,expected', [({'caption': 'Chengde street taken 1983-1-1'}, ('1983-01-01', '1983-01-01', 'day')), ({'caption': 'Chengde street taken 1983/1/1'}, ('1983-01-01', '1983-01-01', 'day')), ({'caption': 'Chengde street taken 1983-1'}, ('1983-01-01', '1983-01-31', 'month')), ({'caption': 'Chengde street taken 1983; uploaded 2025'}, ('1983-01-01', '1983-12-31', 'year')), ({'caption': 'Chengde street uploaded 2025; taken 1983'}, ('1983-01-01', '1983-12-31', 'year')), ({'caption': 'Chengde street published 2025 and taken 1983'}, ('1983-01-01', '1983-12-31', 'year')), ({'caption': 'Chengde street taken 1983 and digitized 2025'}, ('1983-01-01', '1983-12-31', 'year')), ({'dateCreated': '1983-10-01', 'description': 'Chengde street. Digitized 2025-01-01'}, ('1983-10-01', '1983-10-01', 'day'))])
def test_capture_events_survive_other_date_events_with_original_provenance(search_world, tmp_path, capsys, surface, fields, expected):
    helper, world = search_world
    set_image_metadata(world, fields)
    photo, = discover_image_metadata(helper, tmp_path, capsys, surface)
    scene = photo['scene_date'] if surface == 'skill' else photo['scene_date_range']
    assert (scene['start'], scene['end'], scene['precision']) == expected
    if surface == 'skill':
        evidence = [json.loads(line) for line in (tmp_path / 'evidence.jsonl').read_text().splitlines()]
        excerpt = next((row['excerpt'] for row in evidence if row['kind'] == 'scene_date'))
    else:
        excerpt = photo['location_evidence']
    for field, value in fields.items():
        assert f'{field}: {value}' in excerpt

@pytest.mark.parametrize('surface', ['skill', 'app'])
def test_consistent_duplicate_image_records_preserve_all_assertions(search_world, tmp_path, capsys, surface):
    helper, world = search_world
    records = [{'@type': 'Photograph', 'name': 'Chengde street', 'contentUrl': 'https://images.example/street.jpg', 'dateCreated': day} for day in ['1983', '1983-10-01']]
    world['pages']['https://archive.example/photo'] = '<script type="application/ld+json">' + json.dumps(records) + '</script>'
    photo, = discover_image_metadata(helper, tmp_path, capsys, surface)
    scene = photo['scene_date'] if surface == 'skill' else photo['scene_date_range']
    assert scene['start'] == scene['end'] == '1983-10-01'
    assert {row['value'] for row in scene['assertions']} == {'1983', '1983-10-01'}
    assert {row['record'] for row in scene['assertions']} == {0, 1}

@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('caption', ['Chengde street, c. 1983', 'Chengde street; capture date not known', 'Chengde street; no capture date', 'Chengde street; capture date never recorded'])
def test_unknown_capture_aliases_cannot_be_overridden_by_metadata(search_world, tmp_path, capsys, surface, caption):
    helper, world = search_world
    set_image_metadata(world, {'dateCreated': '1983-10-01', 'caption': caption})
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('qualifier', [
    'estimated', 'around', 'before', 'after', 'uncertain', 'unknown',
    'unrecorded', 'circa', 'approx', 'approximately', 'likely', 'maybe',
])
def test_all_uncertainty_is_preserved_at_capture_transitions(search_world, tmp_path, capsys, surface, qualifier):
    helper, world = search_world
    set_image_metadata(world, {'caption': f'Chengde street; published 2025, {qualifier} taken 1983'})
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('label', ['digitized', 'upload date', 'publication date', 'scanned', 'digitization'])
def test_postposed_non_capture_labels_cannot_date_the_scene(search_world, tmp_path, capsys, surface, label):
    helper, world = search_world
    set_image_metadata(world, {'caption': f'Chengde street; 1983 ({label})'})
    assert discover_image_metadata(helper, tmp_path, capsys, surface) == []


@pytest.mark.parametrize('surface', ['skill', 'app'])
@pytest.mark.parametrize('caption,expected_year', [
    ('Chengde street 1983, published 2025', '1983'),
    ('Chengde street 1983 (digitized 2025)', '1983'),
    ('Chengde street 1983 (digitized); taken 1984', '1984'),
    ('Chengde street; 2025 (publication date), taken 1983', '1983'),
    ('Chengde street taken 1983; digitized', '1983'),
    ('Chengde street; published 2025, taken 1983', '1983'),
])
def test_event_association_keeps_independent_capture_dates(search_world, tmp_path, capsys, surface, caption, expected_year):
    helper, world = search_world
    set_image_metadata(world, {'caption': caption})
    photo, = discover_image_metadata(helper, tmp_path, capsys, surface)
    scene = photo['scene_date'] if surface == 'skill' else photo['scene_date_range']
    assert scene['start'] == expected_year + '-01-01'
    assert scene['end'] == expected_year + '-12-31'
