#!/usr/bin/env python3
"""Explicit live semantic contract evaluations; default mode only lists cases."""
import argparse
import asyncio
import json
import hashlib
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DATASET = ROOT / 'tests/evaluation/llm-boundaries.json'


def contract(case):
    from apps.api.conversation_reply import reply_instructions
    from apps.api.lifetime_memory_continuity import governed_collector_schema
    from apps.api.policy_review import PolicyReview
    from apps.api.prompt_artifact import load_prompt_artifact, prompt_path
    from apps.api.two_lane_memory import extraction_contract
    source = dict(id='00000000-0000-4000-8000-000000000001', version=1, sequence=1,
                  status='active', kind='narrator_chat', text=case['source'], language=case['locale'], author_role='storyteller')
    context = dict(source=source, sources=[source], events=[], photos=[], photo_context=[],
                   interview_language=case['locale'], active_strategy='explore', strategy_selector=True,
                   two_lane_memory=True, reply_contract='reply-v2', prepared_questions=[],
                   reply_language=case['locale'], brief={'hints': []})
    if case['contract'] == 'policy':
        return load_prompt_artifact(prompt_path('memoir/agents/mira/policy-review')), PolicyReview.model_json_schema(), {'source': source}
    if case['contract'] == 'collector':
        return (reply_instructions(),
                governed_collector_schema(context), context)
    if case['contract'] == 'extract':
        instructions, schema = extraction_contract()
        return instructions, schema, {'schema_version':1,'sources':[{**source,'char_start':0,'char_end':len(source['text'])}], 'events': [], 'interview_language': case['locale']}
    raise ValueError(f"Unsupported semantic contract: {case['contract']}")


async def execute(cases, output):
    import httpx
    from apps.api.model_request import instruction_manifest, decode_json_response, complete_json
    results = []
    async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
        for case in cases:
            instructions, schema, payload = contract(case)
            manifest = instruction_manifest(instructions, schema, variant='semantic-contract-evaluation')
            response = await client.post(os.environ['MEMORY_SPARK_LLM_BASE_URL'].rstrip('/') + '/responses',
                headers={'Authorization': 'Bearer ' + os.environ['MEMORY_SPARK_LLM_API_KEY']}, json={
                    'model': os.environ['MEMORY_SPARK_LLM_MODEL'], 'instructions': instructions,
                    'input': json.dumps(payload, ensure_ascii=False), 'store': False,
                    'text': {'format': {'type': 'json_schema', 'name': 'proposal', 'strict': True, 'schema': schema}}})
            response.raise_for_status(); raw = response.json(); proposal = decode_json_response(raw)
            verdict, judge_receipt = await complete_json('memoir/evaluation/semantic-boundaries-judge',
                {'case': case, 'result': proposal}, {'type':'object','additionalProperties':False,
                    'required':['passed','notes'],'properties':{'passed':{'type':'boolean'},'notes':{'type':'string'}}})
            results.append({'case_id':case['id'],'proposal':proposal,'verdict':verdict,
                'receipt':{'response_id':raw['id'],'model':raw.get('model'),'prompt_manifest':manifest},'judge_receipt':judge_receipt})
            output.write_text(json.dumps({'scope':'live semantic contracts; not full application E2E','dataset_sha256':hashlib.sha256(DATASET.read_bytes()).hexdigest(),'results':results},ensure_ascii=False,indent=2)+'\n')


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true')
    parser.add_argument('--output',type=Path,default=Path('var/llm-boundary-evaluation.json'))
    args=parser.parse_args();cases=json.loads(DATASET.read_text())['cases']
    if not args.execute:
        print(json.dumps({'mode':'plan','model_calls':0,'cases':[{'id':c['id'],'contract':c['contract']} for c in cases]},indent=2));return
    args.output.parent.mkdir(parents=True,exist_ok=True)
    asyncio.run(execute(cases,args.output))


if __name__=='__main__':main()
