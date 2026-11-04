import json
from types import SimpleNamespace as NS

import pytest

from scripts.snapshot_prompt_evaluations import cursor_pages, pages, snapshot


def test_offset_and_cursor_pagination_are_complete_and_repeated_cursors_fail():
    def fetch(page,limit):return NS(data=[page],meta=NS(total_pages=2))
    assert pages(fetch)==[1,2]
    def cursor(cursor,limit):return NS(data=[cursor],meta=NS(cursor='first' if cursor is None else None))
    assert cursor_pages(cursor)==[None,'first']
    with pytest.raises(ValueError,match='Repeated cursor'):
        cursor_pages(lambda **kw:NS(data=[],meta=NS(cursor='same')))


def test_wrong_project_is_rejected_before_reading_prompt_or_dataset_data():
    client=NS(api=NS(projects=NS(get=lambda:NS(data=[NS(id='other-project')]))))
    with pytest.raises(ValueError,match='requested Memoir project'):
        snapshot(client,'requested-project')


def test_metadata_snapshot_has_counts_and_hashes_without_private_case_io():
    def offset(data):return lambda **kw:NS(data=data,meta=NS(total_pages=1))
    def cursor(data):return lambda **kw:NS(data=data,meta=NS(cursor=None))
    item=NS(id='case',status='ACTIVE',input={'case_id':'synthetic','story':'private-case-text'},
        expected_output={'answer':'private-expected-output'})
    client=NS(api=NS(projects=NS(get=lambda:NS(data=[NS(id='project')])) ,
        prompts=NS(list=offset([NS(name='memoir/prompt',versions=[1],labels=[],tags=[])])),
        datasets=NS(list=offset([NS(id='dataset',name='memoir/dataset',metadata={'api_key':'never-export','synthetic':True})])),
        dataset_items=NS(list=offset([item])),
        experiments=NS(list=cursor([NS(id='experiment',name='synthetic-run')]),
            list_items=cursor([NS(scores=[1]),NS(scores=[])]))))
    observed=snapshot(client,'project')
    encoded=json.dumps(observed)
    assert all(value not in encoded for value in ('private-case-text','private-expected-output','never-export'))
    dataset=observed['datasets'][0]
    assert dataset['experiment_items']==2 and dataset['scored_experiment_items']==1
    assert len(dataset['items'][0]['input_sha256'])==64
