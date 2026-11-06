"""The evaluation must fail wrong outputs without granting delivery or authority."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest

from scripts import run_memoir_agent_evaluation as evaluation
from scripts.memoir_agent_eval_cases import background_cases, catalog
from scripts.memoir_skill_eval_suite import inventory, packet, validate


def test_catalog_covers_current_inventory_and_keeps_gold_outside_input():
    from scripts.langfuse_dataset_names import SKILL_TARGETS, dataset_target
    cases = catalog()
    assert set(inventory()) <= {c['skill'] for c in cases}
    assert {c['locale'] for c in cases if c['component'] == 'lane-b'} == {'en-AU', 'zh-CN'}
    assert {c['component'] for c in cases} == {'lane-a', 'lane-b', 'skills'}
    for name, rows in evaluation.dataset_rows(cases).items():
        assert {SKILL_TARGETS[row['input']['skill']] for row in rows} == {dataset_target(name)}
        for row in rows:
            assert not {'gold', 'expected_output', 'instructions', 'scenario'} & row['input'].keys()
            if row['input']['component'] == 'lane-a':
                assert 'instructions' not in row['input']['task']['view']


def test_current_target_campaigns_can_use_the_shared_dataset_publisher():
    from scripts.run_memoir_skill_evaluation import publish_datasets
    from scripts.langfuse_dataset_names import dataset_target
    case = next(c for c in catalog() if c['id'] == 'skills/memoir-memory-context/explicit-profile/en-AU')
    definitions = evaluation.dataset_rows([case])
    stored, metadata = {}, {}
    def create_dataset(**value):
        stored[value['name']] = []
        metadata[value['name']] = value['metadata']
    def create_item(**value):
        stored[value['dataset_name']].append(SimpleNamespace(id=value['id'], input=value['input'],
            expected_output=value['expected_output'], status='ACTIVE'))
    client = SimpleNamespace(api=SimpleNamespace(datasets=SimpleNamespace(list=lambda **kw:
        SimpleNamespace(data=[], meta=SimpleNamespace(total_pages=1)))), create_dataset=create_dataset,
        create_dataset_item=create_item, get_dataset=lambda name, **kw:SimpleNamespace(items=stored[name]))
    loaded, _ = publish_datasets(client, definitions)
    assert set(loaded) == set(definitions)
    for name in loaded:
        assert metadata[name]['target'] == dataset_target(name)
        assert loaded[name].items[0].input['case_id'] == case['id']


@pytest.mark.parametrize('kind', ['manual-value', 'manual-blank'])
@pytest.mark.parametrize('locale', ['en-AU', 'zh-CN'])
def test_manual_authority_probes_use_current_admitted_profile_fields(kind, locale):
    case = next(c['scenario'] for c in catalog() if c['id'] == f'skills/memoir-memory-context/{kind}/{locale}')
    request = packet(case)
    assert request['input']['profile_context']['targets'] == ['birth_place']
    assert 'name' not in request['input']['profile_context']['targets']
    assert 'birth_year' not in request['input']['profile_context']['targets']
    assert set(case['gold']['facts']) == {'birth_place'}


def background_output(case, skills=None):
    return dict(model_invoked=True, pending=False, reply='{"status":"finished"}',
        executions=[dict(lane='timeline', source_work=dict(skills=deepcopy(skills or [])))],
        skill_receipt=dict(skills_read=deepcopy(skills or [])))


def test_residence_does_not_justify_profile_and_wrong_selection_fails():
    case = next(c for c in background_cases() if c['id'] == 'lane-b/residence/en-AU')
    assert case['gold']['skills'] == ['memoir-author-timeline']
    assert 'memoir-place-journey' not in case['task']['work']['source_work']['available_skills']
    correct = background_output(case, case['gold']['skills'])
    assert all(evaluation.grade_background(case, correct).values())
    correct['executions'][0]['source_work']['skills'].append('memoir-memory-context')
    assert not evaluation.grade_background(case, correct)['skill_selection']
    correct['pending'] = True
    assert not evaluation.grade_background(case, correct)['completed']


def test_dependency_order_and_read_receipts_are_observed_not_model_claims():
    case = next(c for c in background_cases() if c['id'] == 'lane-b/dependencies/en-AU')
    output = background_output(case)
    output['executions'] = [dict(lane='composer'), dict(lane='timeline')]
    assert not evaluation.grade_background(case, output)['dependency_order']
    case = next(c for c in background_cases() if c['id'] == 'lane-b/introduction/en-AU')
    output = background_output(case, case['gold']['skills'])
    output['skill_receipt'] = dict(skills_read=[])
    assert not evaluation.grade_background(case, output)['read_before_execute']


def test_disposable_native_host_does_not_enforce_or_expose_gold(monkeypatch, tmp_path):
    case = next(c for c in background_cases() if c['id'] == 'lane-b/residence/en-AU')
    async def fake_agent(**kwargs):
        assert 'gold' not in kwargs['packet']
        # The host should permit this valid but semantically wrong selection.
        await kwargs['work']()
        assert await kwargs['process_source'](['memoir-memory-context']) == dict(status='finished')
        return dict(reply='{"status":"finished"}', skill_receipt=dict(skills_read=['memoir-memory-context']))
    monkeypatch.setattr('apps.api.memoir_skill_agent.run_skill_agent', fake_agent)
    config = dict(MEMORY_SPARK_LLM_BASE_URL='https://synthetic.invalid/v1', MEMORY_SPARK_LLM_API_KEY='not-real',
        MEMORY_SPARK_LLM_MODEL='synthetic-byte-bpe', MEMORY_SPARK_LLM_REASONING_EFFORT='low')
    output = asyncio.run(evaluation.background(case, config, tmp_path, 10))
    assert not evaluation.grade_background(case, output)['skill_selection']


def test_unavailable_and_semantic_scores_cannot_override_code_failure():
    row = dict(skill='memoir-interviewer', status='unavailable', checks={}, elapsed_seconds=1, semantic=None)
    values = {s.name.removeprefix('memoir/agents/mira/reply/'): s.value for s in evaluation.scores(output=row)}
    assert values['execution_available'] == 0
    assert 'contract_pass' not in values
    row.update(status='fail', semantic=dict(scores=dict(evidence_use=1), comments=dict(evidence_use='observed-1')))
    values = {s.name.removeprefix('memoir/agents/mira/reply/'): s.value for s in evaluation.scores(output=row)}
    assert values['contract_pass'] == 0 and values['advisory.evidence_use'] == 1


@pytest.mark.parametrize('mutation', ['unknown', 'nan', 'boolean', 'citation'])
def test_judge_requires_bounded_known_scores_and_evidence_comments(mutation):
    value = dict(status='scored', scores=dict(evidence_use=0.5), comments=dict(evidence_use='observed-1.output'))
    if mutation == 'unknown':
        value['scores'] = dict(invented=1)
    elif mutation == 'nan':
        value['scores']['evidence_use'] = float('nan')
    elif mutation == 'boolean':
        value['scores']['evidence_use'] = True
    else:
        value['comments'] = {}
    with pytest.raises(ValueError):
        evaluation.validate_judgment(value)


def test_advisory_selection_spans_components_and_is_reproducible():
    cases = catalog()
    selected = evaluation.judge_selection(cases, 12)
    assert len(selected) == 12 and selected == evaluation.judge_selection(list(reversed(cases)), 12)
    assert {c['component'] for c in cases if c['id'] in selected} == {'lane-a', 'lane-b', 'skills'}


def test_plan_does_not_read_credentials_or_construct_provider(monkeypatch, capsys):
    monkeypatch.setattr(evaluation, 'Runner', lambda *args, **kwargs: pytest.fail('provider during plan'))
    assert evaluation.main(['--case', 'lane-b/empty-work/zh-CN', '--env-file', '/does/not/exist']) == 0
    assert '"http_dispatches": 0' in capsys.readouterr().out


def test_current_pinned_judge_accepts_comment_list_but_requires_evidence():
    actual = dict(status='observed', scores=dict(stopping=1), comments=['observed-1 stopped at the narrator boundary.'])
    assert evaluation.validate_judgment(actual)['comments']['stopping'] == actual['comments'][0]
    actual['comments'] = ['Trust my assertion without any supplied witness.']
    with pytest.raises(ValueError):
        evaluation.validate_judgment(actual)


def caption_reply(case):
    return dict(acknowledgement='The caption supplies that description.', recall_limit_quote=None,
        reason='current_correction', strategy='comfort', quote=case['task']['context']['source']['text'],
        question=None, workspace_focus=None, historical_clue_id=None,
        associations=[], response_photo_ids=[])


def test_caption_correction_may_acknowledge_without_another_question():
    case = next(c for c in catalog() if c['id'] == 'lane-a/memoir-interviewer/photo-metadata/en-AU')
    assert not {'question', 'stopped'} & case['gold']['facts'].keys()
    assert all(evaluation.grade_reply(case, caption_reply(case)).values())


@pytest.mark.parametrize('changed_input', [False, True])
def test_retained_replay_regrades_without_a_model_and_rejects_input_changes(monkeypatch, tmp_path, changed_input):
    case = next(c for c in catalog() if c['id'] == 'lane-a/memoir-interviewer/photo-metadata/en-AU')
    data = next(iter(evaluation.dataset_rows([case]).values()))[0]
    async def forbidden(*args, **kwargs):
        pytest.fail('model called while regrading retained output')
    monkeypatch.setattr(evaluation.LiveProvider, 'call', forbidden)
    args = SimpleNamespace(timeout=5, seconds=30, max_calls=1, max_native_runs=0)
    runner = evaluation.Runner(args, {}, tmp_path)
    runner.by_id = {case['id']: case}
    runner.replay = {case['id']: dict(output=caption_reply(case), status='fail',
        input_sha256=evaluation.digest(data['input']), gold_sha256='old-gold')}
    if changed_input: data['input']['task']['view']['reply_language'] = 'changed'
    actual = asyncio.run(runner.task(item=SimpleNamespace(**data)))
    assert actual['status'] == ('fail' if changed_input else 'pass')
    assert actual['direct_http_calls'] == 0
    if not changed_input:
        assert actual['replay']['source_status'] == 'fail'
        assert actual['evidence_mode'] == 'retained_live_output_regraded'
        assert not actual['canonical_delivery']


def test_bilingual_scenario_variants_share_calibration_split():
    for case in catalog():
        if case['id'].endswith('/en-AU'):
            chinese = case['id'][:-len('en-AU')] + 'zh-CN'
            assert evaluation.review_split(case['id']) == evaluation.review_split(chinese)


@pytest.mark.parametrize('mutation', ['none', 'input', 'gold', 'output', 'missing_score', 'missing_item', 'duplicate'])
def test_hosted_readback_verifies_actual_evidence_and_scores(mutation):
    case = next(c for c in catalog() if c['id'] == 'skills/memoir-memory-context/explicit-profile/en-AU')
    rows = next(iter(evaluation.dataset_rows([case]).values()))
    result = dict(case_id=case['id'], skill=case['skill'], status='pass', checks=dict(actual_check=True), elapsed_seconds=1.25, semantic=None)
    item = SimpleNamespace(input=deepcopy(rows[0]['input']), expected_output=deepcopy(rows[0]['expected_output']),
        output=deepcopy(result), scores=evaluation.scores(output=result))
    if mutation in {'input', 'gold', 'output'}:
        if mutation == 'input': item.input['task'] = dict(altered=True)
        elif mutation == 'gold': item.expected_output = {}
        else: item.output['status'] = 'fail'
    if mutation == 'missing_score': item.scores = []
    items = [] if mutation == 'missing_item' else [item, item] if mutation == 'duplicate' else [item]
    client = SimpleNamespace(api=SimpleNamespace(experiments=SimpleNamespace(list_items=lambda **kw:
        SimpleNamespace(data=items, meta=SimpleNamespace(cursor=None)))))
    if mutation in {'input', 'gold', 'output', 'duplicate'}:
        with pytest.raises(ValueError):
            evaluation.verify_experiment(client, 'experiment', rows, [result], None)
    else:
        actual = evaluation.verify_experiment(client, 'experiment', rows, [result], None)
        assert actual['status'] == ('verified' if mutation == 'none' else 'pending')


def test_multicall_composer_workflow_has_a_separate_total_deadline(monkeypatch,tmp_path):
    """A completed phase may use its budget without consuming the whole workflow."""
    import time
    case=next(c for c in catalog() if c['skill']=='memoir-composer' and c['scenario']['case']=='first-checkpoint')
    runner=object.__new__(evaluation.Runner)
    runner.args=SimpleNamespace(seconds=1,timeout=.01,workflow_timeout=.2,max_calls=10)
    runner.started=time.monotonic();runner.by_id={case['id']:case};runner.replay=None;runner.judge_ids=set()
    runner.receipt={'calls':[],'results':[]};runner.directory=tmp_path;runner.persist=lambda:None
    async def workflow(item,adapter,budget):
        assert budget.timeout==.01
        await asyncio.sleep(.03)
        return {'complete':True},{'storage':'isolated_in_memory'}
    monkeypatch.setattr('scripts.memoir_skill_eval_workflows.composer',workflow)
    monkeypatch.setattr('scripts.memoir_skill_eval_suite.validate_workflow',lambda *a,**kw:None)
    row=asyncio.run(runner.task(item=SimpleNamespace(input=next(iter(evaluation.dataset_rows([case]).values()))[0]['input'],expected_output=case['gold'])))
    assert row['status']=='pass'


def test_direct_profile_output_is_regraded_without_new_dispatch_or_losing_provenance(tmp_path):
    import time
    case=next(c for c in catalog(full=True) if c['id']=='skills/memoir-memory-context/correction/en-AU')
    item=SimpleNamespace(**next(iter(evaluation.dataset_rows([case]).values()))[0])
    source=case['task']['page']['source']
    output={'profile_patch':[{'field':'birth_year','value':1962,'source_refs':[{
        'source_id':source['id'],'version':1,'quote':source['text'],'char_start':0,'char_end':41}]}]}
    runner=object.__new__(evaluation.Runner);runner.args=SimpleNamespace(seconds=1,timeout=1,workflow_timeout=1)
    runner.started=time.monotonic();runner.by_id={case['id']:case};runner.judge_ids=set();runner.directory=tmp_path
    runner.receipt={'calls':[],'results':[]};runner.persist=lambda:None
    runner.replay={case['id']:dict(input_sha256=evaluation.digest(item.input),gold_sha256=evaluation.digest(item.expected_output),
        output=output,status='fail',evidence_mode='live_skill_proposal')}
    original_call=dict(case_id=case['id']+'/proposal',provider_response_id='original-response',prompt_manifest={'artifacts':[]})
    runner.replay_calls={case['id']:[original_call]}
    row=asyncio.run(runner.task(item=item))
    assert row['status']=='pass' and row['direct_http_calls']==0 and runner.receipt['calls']==[]
    assert row['output']==output and row['replay']['source_status']=='fail'
    assert row['replay']['source_calls']==[original_call]


@pytest.mark.parametrize('status,response_id,expected',[(502,None,'unavailable'),(200,'observed-response','fail')])
def test_provider_failure_without_a_response_is_not_a_model_contract_failure(tmp_path,status,response_id,expected):
    import time
    case=next(c for c in catalog() if c['component']=='lane-a')
    runner=object.__new__(evaluation.Runner);runner.args=SimpleNamespace(seconds=1,timeout=1,workflow_timeout=1)
    runner.started=time.monotonic();runner.by_id={case['id']:case};runner.judge_ids=set();runner.directory=tmp_path
    runner.receipt={'calls':[],'results':[]};runner.persist=lambda:None;runner.replay=None
    async def unavailable(*args,**kwargs):
        runner.receipt['calls'].append(dict(case_id=case['id'],status='failed',http_status=status,provider_response_id=response_id))
        raise ValueError('provider_or_contract_error')
    runner.provider=SimpleNamespace(call=unavailable)
    item=SimpleNamespace(**next(iter(evaluation.dataset_rows([case]).values()))[0])
    row=asyncio.run(runner.task(item=item))
    assert row['status']==expected
    values={s.name.removeprefix('memoir/agents/mira/reply/'):s.value for s in evaluation.scores(output=row)}
    assert values['execution_available']==int(expected!='unavailable')
    assert ('contract_pass' in values)==(expected!='unavailable')
