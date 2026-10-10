import pytest

from apps.api.memory_events import validate_extraction


@pytest.mark.parametrize('start,end,joined', [
    ('age five', 'age eighteen', 'age five to age eighteen'),
    ('五岁', '十八岁', '五岁到十八岁'),
])
def test_period_date_expression_preserves_one_original_anchor(start, end, joined):
    sources = [{'id': 'start', 'version': 1, 'text': start},
               {'id': 'end', 'version': 1, 'text': end}]
    refs = [{'source_id': source['id'], 'version': 1, 'quote': source['text']}
            for source in sources]
    event = {'kind': 'period', 'title': 'School years', 'source_refs': refs,
             'temporal': {'expression': joined, 'precision': 'range', 'basis': refs}}
    with pytest.raises(ValueError, match='original date expression'):
        validate_extraction({'events': [event]}, sources, [])

    # Multiple anchors remain available without synthesizing a new quotation.
    event['temporal']['expression'] = start
    saved = validate_extraction({'events': [event]}, sources, [])
    assert saved[0]['temporal']['expression'] == start
    assert saved[0]['temporal']['basis'] == refs


def test_unknown_date_does_not_require_invented_evidence():
    ref = {'source_id': 'source', 'version': 1, 'quote': 'I remember the garden.'}
    event = {'kind': 'event', 'title': 'The garden', 'source_refs': [ref],
             'temporal': {'expression': 'unknown', 'precision': 'unknown', 'basis': []}}
    saved = validate_extraction({'events': [event]},
                                [{'id': 'source', 'version': 1, 'text': ref['quote']}], [])
    assert saved[0]['temporal'] == event['temporal']


@pytest.mark.parametrize('year,expression', [
    (1988, '一九八八年前后'),
    (1993, '一九九三年'),
    (2002, '二〇〇二年前后'),
])
def test_chinese_digit_years_support_numeric_temporal_evidence(year, expression):
    text = f'我记得大约在{expression}参加过一次考试。'
    ref = {'source_id': 'source', 'version': 1, 'quote': text}
    event = {'kind': 'event', 'title': '考试', 'source_refs': [ref],
             'temporal': {'expression': expression, 'precision': 'approximate',
                          'year_start': year, 'year_end': year, 'basis': [ref]}}
    saved = validate_extraction({'events': [event]},
                                [{'id': 'source', 'version': 1, 'text': text}], [])
    assert saved[0]['temporal']['year_start'] == year
