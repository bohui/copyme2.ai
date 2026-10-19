"""Pinned, independent skill judges; drafts may be planned but never dispatched."""
import hashlib
import json
from pathlib import Path
import re

from apps.api.prompt_artifact import load_prompt_artifact
from apps.api.prompt_catalog import PENDING_EVALUATION_PROMPTS
from scripts.memoir_skill_inventory import skill_inventory

ROOT = Path(__file__).resolve().parents[1]
PREFIX = 'memoir/evaluation/judges/'
VERDICTS = ('pass', 'partial', 'fail', 'unavailable', 'not_applicable')
DATA_VARIABLE = re.compile(r'\{\{(input|output|expected_output)\}\}')


def judge_prompt(skill, *, root=ROOT, preview=False):
    if skill not in skill_inventory():
        raise ValueError('unknown_judge_skill')
    parts, receipts = [], []
    for name in (PREFIX + 'shared-policy', PREFIX + skill):
        path = root / PENDING_EVALUATION_PROMPTS[name]
        if preview:
            parts.append(path.read_text(encoding='utf-8'))
            state = 'pending'
            if path.with_name(path.name + '.langfuse.json').is_file():
                try:
                    load_prompt_artifact(path)
                    state = 'pinned'
                except ValueError:
                    state = 'invalid_pin'
            receipts.append(dict(name=name, sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                 publication=state))
        else:
            parts.append(load_prompt_artifact(path))
            receipt = json.loads(path.with_name(path.name + '.langfuse.json').read_text())
            if receipt['name'] != name:
                raise ValueError('wrong_judge_prompt_pin')
            receipts.append(receipt)
    if parts[0].count('{{skill_rubric}}') != 1:
        raise ValueError('invalid_judge_composition')
    compiled = parts[0].replace('{{skill_rubric}}', parts[1])
    if set(DATA_VARIABLE.findall(compiled)) != {'input', 'output', 'expected_output'}:
        raise ValueError('invalid_judge_variables')
    return compiled, dict(prompts=receipts, compiled_sha256=hashlib.sha256(compiled.encode()).hexdigest())


def evaluator_plan(*, root=ROOT):
    result = []
    for skill in skill_inventory():
        _, provenance = judge_prompt(skill, root=root, preview=True)
        result.extend([
            dict(name=f'memoir/evaluators/{skill}/contract', type='code',
                 dataset=f'memoir/evaluation/skills/{skill}', publication='not_checked'),
            dict(name=f'memoir/evaluators/{skill}/quality', type='llm_as_judge',
                 dataset=f'memoir/evaluation/skills/{skill}', publication='not_checked',
                 prompt=PREFIX + skill, provenance=provenance,
                 variables=['input', 'output', 'expected_output'],
                 output_definition=dict(dataType='CATEGORICAL',
                     reasoning=dict(description='Concise evidence-based justification with witness IDs.'),
                     score=dict(description='Quality within the declared scope; unavailable is an abstention.',
                                categories=list(VERDICTS), shouldAllowMultipleMatches=False)))])
    return result


class SkillJudge:
    def __init__(self, provider, *, root=ROOT, max_input_bytes=100_000):
        self.provider, self.root, self.max_input_bytes = provider, root, max_input_bytes

    async def evaluate(self, row, result):
        if row['input']['kind'] == 'controlled_application_checks' or row['input']['kind'] == 'deterministic':
            return dict(score='not_applicable', reason='controlled_or_numeric_check', calibration='pending')
        if 'artifact' not in result:
            return dict(score='unavailable', reason='missing_evaluated_artifact', calibration='pending')
        template, provenance = judge_prompt(row['input']['skill'], root=self.root)
        evidence_ids = ['input', 'artifact', 'contract']
        packet = dict(input=row['input'], expected_output=row['expected_output'], output=dict(
            artifact=result['artifact'], witnesses=dict(
                input=row['input'].get('packet'), contract=result['status'])))
        encoded = {name: json.dumps(value, ensure_ascii=False, sort_keys=True) for name, value in packet.items()}
        if sum(len(text.encode()) for text in encoded.values()) > self.max_input_bytes:
            return dict(score='unavailable', reason='judge_evidence_budget_exhausted', calibration='pending')
        instructions = DATA_VARIABLE.sub(lambda match: encoded[match[1]], template)
        schema = dict(type='object', additionalProperties=False, required=['score', 'reasoning'], properties=dict(
            score=dict(type='string', enum=list(VERDICTS)),
            reasoning=dict(type='string', minLength=1, maxLength=3000)))
        value, response = await self.provider.call('judge-' + row['input']['case_id'],
            'evaluation-judge', instructions, {}, schema)
        citations = [key for key in evidence_ids if '[' + key + ']' in value['reasoning']]
        if value['score'] in {'pass', 'partial', 'fail'} and not citations:
            raise ValueError('judge_verdict_needs_evidence')
        return {**value, 'evidence_ids': citations, 'response_id': response['id'], 'provenance': provenance,
                'calibration': 'pending', 'role': 'advisory'}
