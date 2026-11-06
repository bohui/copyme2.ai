"""Shared, synthetic answer keys for the actual Memoir judge prompt contracts."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from apps.api.model_request import digest as request_digest
from apps.api.prompt_artifact import load_prompt_artifact
from scripts.langfuse_dataset_names import target_dataset
from scripts.memoir_skill_eval_suite import KNOWN, judge_definition, quality
from scripts.prompt_registry import prompt_registry

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'tests/evaluation/shared_judge_calibration.json'
TARGET='memoir/evaluators/shared/judge-calibration'
DATASET=target_dataset(TARGET,'calibration','shared-v2')
ORIGIN='synthetic-specification-answer-key'


def item_id(case):
    return str(uuid5(NAMESPACE_URL,DATASET+'/'+case['input']['case_id']))


def hosted_item(case):
    return dict(id=item_id(case),status='ACTIVE',input=deepcopy(case['input']),
        expected_output=deepcopy(case['expected_output']),metadata=dict(synthetic=True,label_origin=ORIGIN,
            human_reviewed=False,case_id=case['input']['case_id'],split=case['input']['split'],content_sha256=digest(case)))


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def judges():
    result={name:dict(kind='numeric',prompts=['memoir/evaluators/shared/'+name])
        for name in ('correctness','relevance','completeness','safety')}
    # Retain the original judges for the frozen shared answer key and past runs.
    for skill in sorted(KNOWN | {'memoir-place-groups', 'memoir-place-journey'}):
        definition=judge_definition(skill)
        result[skill]=dict(kind='skill',prompts=[c['name'] for c in definition['components']])
    result.update({
        'semantic-boundaries':dict(kind='semantic',prompts=['memoir/evaluators/shared/semantic-boundaries']),
        'mira-comparison':dict(kind='comparison',prompts=['memoir/evaluators/agents/mira/reply/comparison']),
        'trajectory':dict(kind='trajectory',prompts=['memoir/evaluators/shared/trajectory/system',
            'memoir/evaluators/shared/trajectory/rubric']),
        'five-case':dict(kind='trajectory',prompts=['memoir/evaluators/shared/trajectory/system',
            'memoir/evaluators/workflows/five-case-memoir/trajectory',
            'memoir/evaluators/workflows/five-case-memoir/guard'])})
    return result


def cases():
    source=json.loads(SOURCE.read_text())
    if source.get('human_reviewed') is not False or source.get('label_origin')!=ORIGIN:
        raise ValueError('Synthetic answer keys must not claim independent human review')
    catalog=judges();seen=set();coverage={name:set() for name in catalog}
    for case in source['cases']:
        value=case['input'];key=value['case_id']
        if key in seen or value['split'] not in {'development','holdout'}:
            raise ValueError('Duplicate calibration ID or invalid split')
        seen.add(key)
        if set(value['judge_ids'])!=set(case['expected_output']) or not value['judge_ids']:
            raise ValueError('Every applicable judge needs an explicit answer key')
        for name,expected in case['expected_output'].items():
            if name not in catalog or not expected.get('rationale'):
                raise ValueError('Unknown judge or missing answer-key rationale')
            coverage[name].add(value['split'])
    if any(splits!={'development','holdout'} for splits in coverage.values()):
        raise ValueError('Every judge needs development and held-out cases')
    return source['cases']


def request(judge_id, value):
    """Build only evaluated evidence/reference input; answer-key grades stay outside."""
    definition=judges()[judge_id]
    registry=prompt_registry()
    paths=[ROOT/registry[n] for n in definition['prompts']]
    texts=[load_prompt_artifact(path) for path in paths]
    instructions='\n\n'.join(texts);kind=definition['kind'];packet=deepcopy(value['packet'])
    schema=None;messages=None
    if kind=='numeric':
        for key,field in (('input','input'),('expected_output','reference'),('output','output')):
            instructions=instructions.replace('{{'+key+'}}',json.dumps(packet.get(field),ensure_ascii=False))
        schema=dict(type='object',additionalProperties=False,required=['score','comment'],properties=dict(
            score=dict(type=['number','null'],minimum=0,maximum=1),comment=dict(type='string')))
        packet=None
    elif kind=='skill':
        schema=dict(type='object',additionalProperties=False,required=['status','citations','rationale','critical_violations'],
            properties=dict(status=dict(type='string',enum=['pass','partial','fail','unavailable','not_applicable']),
                citations=dict(type='array',items=dict(type='string')),rationale=dict(type='string'),
                critical_violations=dict(type='array',items=dict(type='string'))))
    elif kind=='semantic':
        schema=dict(type='object',additionalProperties=False,required=['passed','notes'],
            properties=dict(passed=dict(type='boolean'),notes=dict(type='string')))
    elif kind=='comparison':
        from scripts.evaluate_mira_prompt import judge_schema
        schema=judge_schema()
    else:
        from apps.api.trajectory_evaluation import build_judge_prompt
        messages=[dict(role='system',content=texts[0]),dict(role='user',content=build_judge_prompt(
            packet,calibration_examples=[],prompt_names=tuple(definition['prompts'][1:])))]
    pins=[json.loads(path.with_name(path.name+'.langfuse.json').read_text()) for path in paths]
    manifest=dict(artifacts=[dict(name=p['name'],version=p['version'],sha256=p['sha256'],status='published') for p in pins],
        prompt_sha256=request_digest(instructions),schema_sha256=request_digest(schema),variant='shared-judge-calibration')
    manifest['manifest_sha256']=request_digest(manifest)
    return dict(kind=kind,instructions=instructions,packet=packet,schema=schema,messages=messages,manifest=manifest)


def normalize(judge_id, value, packet):
    kind=judges()[judge_id]['kind']
    if kind=='numeric':
        score=value.get('score')
        if score is not None and (type(score) not in (int,float) or not math.isfinite(score) or not 0<=score<=1):
            raise ValueError('Invalid numeric judge score')
        if not isinstance(value.get('comment'),str) or not value['comment'].strip():
            raise ValueError('A grade needs its rationale')
        return dict(score=score)
    if kind=='skill':
        value=quality({**value,'response_id':'transport-owned','model':'transport-owned'},packet['evidence'])
        return dict(status=value['status'],critical=bool(value['critical_violations']))
    if kind=='semantic':
        if type(value.get('passed')) is not bool or not value.get('notes'):
            raise ValueError('Invalid semantic verdict')
        return dict(passed=value['passed'])
    if kind=='comparison':
        from jsonschema import validate
        from scripts.evaluate_mira_prompt import judge_schema
        validate(value,judge_schema())
        if len(value['results'])!=1 or value['results'][0]['id']!=packet[0]['id']:
            raise ValueError('Foreign or incomplete comparison')
        row=value['results'][0]
        return dict(winner=row['winner'],critical={k:bool(row[k]['critical']) for k in ('A','B')})
    if judge_id=='five-case':
        from scripts.run_memoir_five_case_semantic_judge import validate_judge_result
        status,value=validate_judge_result(value)
        if status not in {'scored','unavailable'}:
            raise ValueError('Five-case consumer rejected the judgment')
    else:
        from scripts.run_memoir_agent_evaluation import validate_judgment
        value=validate_judgment(value)
        if value['status']!='unavailable' and value['scores']:value['status']='scored'
    return dict(status=value['status'],scores=value.get('scores',{}))


def grade(actual, expected):
    problems=[]
    for key in ('status','critical','passed','winner'):
        if key in expected and actual.get(key)!=expected[key]:problems.append(key)
    if 'score' in expected:
        score,wanted=actual.get('score'),expected['score']
        if wanted is None:
            if score is not None:problems.append('score_requires_abstention')
        elif type(score) not in (int,float) or not math.isfinite(score) or abs(score-wanted)>.05:
            problems.append('score')
    for key,wanted in expected.get('critical_sides',{}).items():
        if actual.get('critical',{}).get(key)!=wanted:problems.append('critical_'+key)
    for key,wanted in expected.get('scores',{}).items():
        score=actual.get('scores',{}).get(key)
        if type(score) not in (int,float) or not math.isfinite(score) or abs(score-wanted)>.05:
            problems.append('score_'+key)
    if any(k in actual.get('scores',{}) for k in expected.get('omit_scores',[])):
        problems.append('unobserved_category_scored')
    if expected.get('status')=='unavailable' and actual.get('scores'):problems.append('unavailable_with_scores')
    return dict(agreement=not problems,problems=problems)
