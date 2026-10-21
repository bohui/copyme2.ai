"""Deterministic source, request and provenance checks; no language gold scoring."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from apps.api.model_request import prompt_manifest, instruction_manifest
from apps.api.prompt_artifact import prompt_path
from apps.api.policy_review import PolicyReview, validate_review
from apps.api.lifetime_memory_policy import PolicyUnavailable
from apps.api.lifetime_memory_continuity import governed_collector_schema
from apps.api.trajectory_evaluation import TrajectoryRecorder, evaluate_trajectory
from apps.api.place_photo_browser import _research


def test_manifest_identifies_components_and_schema_without_request_testimony():
    from apps.api.memory_events import extraction_instructions, extraction_schema
    instructions, schema = extraction_instructions(), extraction_schema()
    manifest = instruction_manifest(instructions,schema,variant='extract')
    assert manifest['artifacts']
    assert manifest['prompt_sha256']==hashlib.sha256(instructions.encode()).hexdigest()
    assert any(item['name']=='memoir/skills/memoir-author-timeline/instructions' for item in manifest['artifacts'])
    changed=deepcopy(schema);changed['title']='Changed structural contract'
    assert instruction_manifest(instructions,changed)['schema_sha256'] != manifest['schema_sha256']
    assert all(item['version'] is None for item in manifest['artifacts'] if item['status']=='unpublished')


def test_manifest_ignores_catalog_sources_not_shipped_to_runtime(monkeypatch):
    from apps.api.prompt_catalog import PROMPT_PATHS
    from apps.api.memory_events import extraction_instructions, extraction_schema

    monkeypatch.setitem(PROMPT_PATHS, 'memoir/evaluation/not-shipped',
                        'tests/evaluation/not-shipped.md')

    manifest = instruction_manifest(extraction_instructions(), extraction_schema(), variant='extract')

    assert 'memoir/evaluation/not-shipped' not in {item['name'] for item in manifest['artifacts']}


def test_behavioral_schema_descriptions_are_not_a_second_prompt_store():
    schema = governed_collector_schema({'sources':[],'events':[],'photos':[]})
    def visit(value):
        if isinstance(value,dict):
            assert not isinstance(value.get('description'),str)
            for item in value.values(): visit(item)
        elif isinstance(value,list):
            for item in value: visit(item)
    visit(schema)


def test_semantic_quality_is_absent_without_a_live_judge():
    recorder=TrajectoryRecorder();recorder.finish('approximately 1976')
    scores=evaluate_trajectory(recorder.payload())
    assert 'final_response_quality' not in {item['name'] for item in scores}
    assert next(item['value'] for item in scores if item['name']=='completion_contract')==1


@pytest.mark.parametrize('binding', [{'base_url': ''}, {'api_key': ''}])
def test_explicit_missing_provider_binding_never_falls_back_to_environment(monkeypatch, binding):
    import asyncio
    import httpx
    from apps.api.model_request import complete_json
    monkeypatch.setenv('MEMORY_SPARK_LLM_BASE_URL', 'https://environment.invalid/v1')
    monkeypatch.setenv('MEMORY_SPARK_LLM_API_KEY', 'environment-fixture-key')
    calls = []
    async def run():
        return await complete_json('memoir/skills/memoir-interviewer/policy-review', {}, {}, model='fixture-model',
            transport=httpx.MockTransport(lambda request: calls.append(request)), **binding)
    with pytest.raises(ValueError, match='not configured'):
        asyncio.run(run())
    assert calls == []


def test_structured_request_forwards_skill_trace_identity(monkeypatch):
    import asyncio
    import httpx
    from apps.api import llm_tracing
    from apps.api.model_request import complete_json

    class Observation:
        def __init__(self, fields):
            self.fields = fields

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    class Client:
        def __init__(self):
            self.observations = []

        def start_as_current_observation(self, **fields):
            observation = Observation(fields)
            self.observations.append(observation)
            return observation

    client = Client()
    monkeypatch.setattr(llm_tracing, '_client_cache', client)
    captured = {}

    def provider(request):
        captured.update(json.loads(request.content))
        return httpx.Response(200, json={
            'id': 'fixture-response',
            'status': 'completed',
            'output': [{'type': 'message', 'content': [{
                'type': 'output_text',
                'text': '{"complete":true,"restrictions":[]}',
            }]}],
        })

    asyncio.run(complete_json(
        'memoir/skills/memoir-interviewer/policy-review', {}, {},
        model='fixture-model', transport=httpx.MockTransport(provider),
        base_url='https://fixture.invalid/v1', api_key='fixture-key',
        trace_name='memoir-interviewer'))

    assert captured['metadata']['generation_name'] == 'memoir-interviewer'
    assert captured['metadata']['trace_name'] == 'memoir-interviewer'
    assert client.observations[0].fields['name'] == 'memoir-interviewer'


@pytest.mark.parametrize('fault',['span','duplicate','kind','incomplete'])
def test_policy_proposal_validation_cannot_invent_evidence_or_permissions(fault):
    source={'text':'An exact original.'}
    row=dict(kind='excluded_topic',quote=source['text'],char_start=0,char_end=len(source['text']))
    output=dict(complete=True,restrictions=[row])
    if fault=='span':row['char_start']=1
    if fault=='duplicate':output['restrictions']*=2
    if fault=='kind':row['kind']='allow_publication'
    if fault=='incomplete':output['complete']=False
    with pytest.raises((ValueError,PolicyUnavailable)):
        validate_review(output,source)


def test_live_semantic_dataset_is_data_not_a_default_model_dispatch():
    path=Path(__file__).parent/'evaluation/llm-boundaries.json'
    cases=json.loads(path.read_text())['cases']
    assert len({case['id'] for case in cases})==len(cases)
    assert all(case['contract'] in {'policy','collector','extract'} and case['expectation'] for case in cases)


def test_research_window_keeps_original_offsets_after_a_source_window_boundary():
    from apps.api.place_journey import grounded_place_journeys
    text='Sydney in 1980.';offset=700
    window=dict(year_start=1980,year_end=1980,anchor_year=1980,basis='explicit_period',
        quote=text,char_start=offset,char_end=offset+len(text))
    place=dict(place='Sydney',hierarchy=['Earth','Australia','Sydney'],granularity='city',research=window)
    assert grounded_place_journeys([place],text,source_offset=offset)==[place]
    with pytest.raises(ValueError,match='evidence'):
        grounded_place_journeys([place],text)
