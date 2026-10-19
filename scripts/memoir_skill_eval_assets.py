"""Offline asset reconciliation and hosted readback contracts.

This module deliberately has no Langfuse client/credentials. The installed
server's evaluator/rule API must be verified before a live adapter is added.
Tests supply a controlled store implementing snapshot/read/write operations.
"""
from copy import deepcopy
from datetime import datetime
import math

from scripts.memoir_skill_eval_suite import digest, identity

DATASET_PREFIX = 'memoir/evaluation/skills/'
SHARED = {'memoir/evaluation/workflows', 'memoir/evaluation/judge-calibration'}


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('snapshot_requires_timezone')
    return value


def stable_id(item):
    # Identity stays unchanged across corrected text, gold or witnesses.
    return digest(identity(item))[:32]


def dataset_rows(planned):
    rows = {name: [] for name in planned['datasets']}
    # Execution filters must never turn unselected cases into retirement writes.
    for item in planned['catalog_items']:
        rows[item['dataset']].append(dict(id=stable_id(item), status='ACTIVE',
            input={k: deepcopy(item[k]) for k in ('id', 'skill', 'case', 'locale', 'phase', 'action', 'scope', 'task')},
            expected_output=deepcopy(item['gold']), metadata=dict(synthetic=True,
                identity=item['id'], content_sha256=item['content_sha256'])))
    for key, dataset in (('workflow_items', 'memoir/evaluation/workflows'),
                         ('calibration_items', 'memoir/evaluation/judge-calibration')):
        for item in planned[key]:
            rows[dataset].append(dict(id=digest(item['id'])[:32], status='ACTIVE',
                input={k: deepcopy(v) for k, v in item.items() if k != 'expected_output'},
                expected_output=deepcopy(item['expected_output']), metadata=dict(synthetic=True,
                    identity=item['id'], content_sha256=digest(item))))
    return rows


def managed_assets(planned, *, executor):
    if executor not in {'sdk', 'managed'}: raise ValueError('unknown_judge_executor')
    definitions, rules = deepcopy(planned['evaluators']), []
    targets = {s: 'memoir/evaluation/skills/' + s for s in planned['inventory']}
    for definition in definitions:
        skill = definition['name'].split('/')[-2]
        if definition['kind'] == 'quality' and executor == 'sdk': continue
        rules.append(dict(name=definition['name'] + '/synthetic-experiments', enabled=False,
            evaluator_name=definition['name'], dataset=targets[skill], synthetic_only=True,
            evaluator_version=definition['hosted_evaluator_version']))
    return dict(definitions=definitions, rules=rules, executor=executor,
        status='blocked_until_merged_prompt_publication_and_deployed_api_verification')


def preflight(store, desired, *, snapshot):
    """Inspect every selected asset before producing any mutation plan."""
    timestamp(snapshot)
    operations, observed = [], {}
    for name, rows in sorted(desired.items()):
        if not (name.startswith(DATASET_PREFIX) or name in SHARED):
            raise ValueError('historical_dataset_out_of_scope')
        current = store.read_dataset(name, snapshot=snapshot)
        if current is not None and current.get('synthetic') is not True:
            raise ValueError('existing_dataset_ownership_conflict')
        if len({r['id'] for r in rows}) != len(rows): raise ValueError('duplicate_desired_item')
        if any(r.get('metadata', {}).get('synthetic') is not True for r in rows):
            raise ValueError('synthetic_items_required')
        observed[name] = deepcopy(current)
        if current is None:
            operations.append(dict(kind='create_dataset', dataset=name, value=dict(synthetic=True, items=[])))
        existing = (current or {}).get('items', [])
        if len({r['id'] for r in existing}) != len(existing): raise ValueError('duplicate_hosted_item')
        actual, wanted = ({r['id']: r for r in values} for values in (existing, rows))
        if any(r.get('metadata', {}).get('synthetic') is not True for r in existing):
            raise ValueError('existing_item_ownership_conflict')
        for key, value in wanted.items():
            prior = actual.get(key)
            if prior != value:
                operations.append(dict(kind='upsert_item', dataset=name, id=key, before_sha256=digest(prior), value=deepcopy(value)))
        for key in actual.keys() - wanted.keys():
            if actual[key]['status'] != 'ARCHIVED':
                value = {**deepcopy(actual[key]), 'status': 'ARCHIVED'}
                operations.append(dict(kind='archive_item', dataset=name, id=key,
                    before_sha256=digest(actual[key]), value=value))
    result = dict(snapshot=snapshot, observed=observed, operations=operations)
    result['review_sha256'] = digest(result)
    return result


def reconcile(store, reviewed, *, review_sha256):
    """Controlled boundary only. A reviewed diff is bound to exact prior content."""
    body = {k: v for k, v in reviewed.items() if k != 'review_sha256'}
    if review_sha256 != reviewed.get('review_sha256') or digest(body) != review_sha256:
        raise ValueError('reviewed_asset_diff_required')
    # Re-read CURRENT state, not the earlier snapshot; refuse intervening edits.
    for name, expected in reviewed['observed'].items():
        if store.read_dataset(name, snapshot=None) != expected: raise ValueError('asset_changed_since_review')
    receipts = []
    for operation in reviewed['operations']:
        name = operation['dataset']
        if operation['kind'] == 'create_dataset':
            store.create_dataset(name, deepcopy(operation['value']), expected_absent=True)
        else:
            store.upsert_item(name, operation['id'], deepcopy(operation['value']),
                              expected_sha256=operation['before_sha256'])
        current = store.read_dataset(name, snapshot=None)
        value = current if operation['kind'] == 'create_dataset' else next(
            (row for row in (current or {}).get('items', []) if row['id'] == operation['id']), None)
        if value != operation['value']: raise ValueError('asset_write_readback_conflict')
        receipts.append(dict(dataset=name, kind=operation['kind'], readback_sha256=digest(value)))
    return dict(status='verified', writes=receipts, snapshot=timestamp(store.snapshot()))


def score_readback(items, expected):
    """Every exact experiment item and named score must match; counts are insufficient."""
    if not expected or not items: return dict(status='incomplete', reason='empty_experiment')
    if len(items) != len(expected) or len({i.get('item_id') for i in items}) != len(items):
        return dict(status='incomplete', reason='experiment_item_count_or_duplicates')
    wanted = {row['item_id']: row for row in expected}
    if len(wanted) != len(expected): raise ValueError('duplicate_expected_item')
    for item in items:
        target = wanted.get(item.get('item_id'))
        if target is None: return dict(status='incomplete', reason='unexpected_experiment_item')
        for field in ('dataset', 'dataset_snapshot', 'input_sha256', 'output_sha256', 'trace_id', 'observation_id'):
            if not target.get(field) or item.get(field) != target[field]:
                return dict(status='incomplete', reason='experiment_identity_mismatch')
        if not target.get('evaluators'): return dict(status='incomplete', reason='missing_expected_evaluators')
        scores = item.get('scores', [])
        for evaluator in target['evaluators']:
            matches = [s for s in scores if s.get('name') == evaluator['name']]
            if len(matches) != 1: return dict(status='incomplete', reason='missing_or_duplicate_named_score')
            score = matches[0]
            if type(evaluator.get('version')) is not int or evaluator['version'] < 1:
                return dict(status='incomplete', reason='unpublished_evaluator')
            if (score.get('evaluator_version') != evaluator['version'] or score.get('compiled_sha256') != evaluator['compiled_sha256']
                or score.get('trace_id') != target['trace_id'] or score.get('observation_id') != target['observation_id']
                or score.get('output_sha256') != target['output_sha256']):
                return dict(status='incomplete', reason='score_identity_mismatch')
            actual_value, expected_value = score.get('value'), evaluator.get('value')
            numeric = type(actual_value) in (int, float) and type(expected_value) in (int, float)
            same_value = (math.isfinite(actual_value) and math.isfinite(expected_value) and actual_value == expected_value
                          if numeric else type(actual_value) is type(expected_value) and actual_value == expected_value)
            if 'value' not in evaluator or 'value' not in score or expected_value is None or not same_value:
                return dict(status='incomplete', reason='score_value_mismatch')
    return dict(status='verified', items=len(items))


def read_experiment_scores(client, experiment_id, expected, *, started_at, max_pages=4):
    """Read-only injected v4 SDK seam, adapted from PR93; never creates a client.

    Full IO, item metadata and score values augment the existing receipt/version
    bindings. Controlled SDK shape checks do not verify a deployed server release.
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 10 or not experiment_id:
        raise ValueError('invalid_experiment_readback_limit')
    if started_at.tzinfo is None or started_at.utcoffset() is None:
        raise ValueError('experiment_window_requires_timezone')
    if not expected: return dict(status='incomplete', reason='empty_experiment')
    def field(value, name, default=None):
        return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)
    wanted = {row['item_id']: row for row in expected}
    if len(wanted) != len(expected): raise ValueError('duplicate_expected_item')
    for row in expected:
        if any(key not in row or row.get(key + '_sha256') != digest(row[key]) for key in ('input', 'output')):
            return dict(status='incomplete', reason='expected_payload_binding_mismatch')
    normalized, cursor, seen = [], None, set()
    for _ in range(max_pages):
        try:
            result = client.api.experiments.list_items(experiment_id=experiment_id, from_start_time=started_at,
                fields='core,dataset,io,itemMetadata,experimentMetadata,scores', limit=100, score_limit=50,
                **({'cursor': cursor} if cursor else {}))
            for item in result.data:
                target = wanted.get(field(item, 'experiment_item_id'))
                if (target is None or field(item, 'experiment_id') != experiment_id
                    or field(item, 'experiment_dataset_id') != target['dataset_id']):
                    return dict(status='incomplete', reason='experiment_item_identity')
                if any(key not in target or digest(field(item, key)) != digest(target[key])
                       for key in ('input', 'expected_output', 'output')):
                    return dict(status='incomplete', reason='experiment_content_binding')
                if (not target.get('item_metadata')
                    or field(item, 'experiment_item_metadata') != target['item_metadata']):
                    return dict(status='incomplete', reason='experiment_metadata_binding')
                metadata, scores = field(item, 'experiment_metadata') or {}, []
                required_names = {e['name'] for e in target['evaluators']}
                for score in field(item, 'scores') or []:
                    if field(score, 'name') not in required_names: continue
                    subject, provenance = field(score, 'subject'), field(score, 'metadata') or {}
                    if field(subject, 'kind') != 'observation':
                        return dict(status='incomplete', reason='score_observation_subject_required')
                    scores.append(dict(name=field(score, 'name'), value=field(score, 'value'),
                        evaluator_version=provenance.get('evaluator_version'), compiled_sha256=provenance.get('compiled_sha256'),
                        trace_id=field(subject, 'trace_id'), observation_id=field(subject, 'id'),
                        output_sha256=provenance.get('output_sha256')))
                normalized.append(dict(item_id=field(item, 'experiment_item_id'), dataset=metadata.get('dataset'),
                    dataset_snapshot=metadata.get('dataset_snapshot'), input_sha256=digest(field(item, 'input')),
                    output_sha256=digest(field(item, 'output')), trace_id=field(item, 'trace_id'),
                    observation_id=scores[0]['observation_id'] if scores else None, scores=scores))
            if len(normalized) > len(expected):
                return dict(status='incomplete', reason='experiment_item_count_or_duplicates')
            cursor = field(result.meta, 'cursor')
            if not cursor:
                return score_readback(normalized, expected)
            if cursor in seen: break
            seen.add(cursor)
        except Exception as error:
            return dict(status='incomplete', reason='experiment_readback_' + type(error).__name__)
    return dict(status='incomplete', reason='experiment_pagination_incomplete')


class IndependentJudgeAdapter:
    """A single executor, with an injected completion transport and explicit pin gate."""
    def __init__(self, transport, *, controlled=False):
        self.transport, self.controlled = transport, controlled

    async def call(self, packet):
        if not self.controlled and packet.get('publication') != 'pinned':
            raise ValueError('published_judge_components_required')
        # Keep policy in the instruction field; data is serialized separately.
        response = await self.transport.complete(dict(instructions=packet['instructions'],
            input={k: packet[k] for k in ('evidence', 'gold')}, store=False))
        import json
        value = json.loads(response['text'])
        if not isinstance(value, dict): raise ValueError('malformed_judge_output')
        # Response identity/accounting is transport-owned, never parsed from model text.
        return {**value, **{key: response.get(key) for key in ('response_id', 'model', 'usage')}}
