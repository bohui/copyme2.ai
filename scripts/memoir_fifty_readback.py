"""Pure, explicit readback for the original five-case, fifty-input campaign.

This bridge reads only the hash-pinned original input file. It never loads the
separate truth/expected file, extends the 15-turn dataset, dispatches an executor,
or grants provider, durability, word-limit or semantic acceptance. Callers must
obtain outcomes from a separately admitted executor.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid5

from scripts.issue14_progressive_readback import (
    ReadbackError, _ConfiguredReadback, _identifier, _list, _object, _require,
)


DATASET_PATH = Path(__file__).resolve().parents[1] / 'tests/evaluation/memoir_five_case_inputs.json'
DATASET_SHA256 = 'e7f705bc4a96537b01cb5cde7d412972bdd929de49d339bc6b1a95bc9cb43927'
DATASET_VERSION = 'memoir-five-case/1'
CASE_IDS = ('harbour-copper-notebook', 'chengdu-tea-ledger',
            'perth-workshop-compass', 'kunming-garden-lanterns',
            'sydney-platform-letters')
CHECKPOINTS = tuple(range(5, 51, 5))
EVIDENCE_MODE = 'subscription_fifty'
_LOCALES = ('en-AU', 'zh-CN', 'en-AU', 'zh-CN', 'en-AU')


def case_plans_for_run(run_id):
    """Fresh UUID5 identities per run and campaign; no supplied fixture projects."""
    if type(run_id) is not str:
        raise ValueError('Canonical run UUID required')
    try:
        namespace = UUID(run_id)
    except ValueError:
        raise ValueError('Canonical run UUID required') from None
    if str(namespace) != run_id:
        raise ValueError('Canonical run UUID required')
    campaign = uuid5(namespace, DATASET_VERSION + '/' + EVIDENCE_MODE)
    return {case_id: {'case_id': case_id,
        'owner_id': str(uuid5(campaign, case_id + '/owner')),
        'project_id': str(uuid5(campaign, case_id + '/project')), 'language': locale}
        for case_id, locale in zip(CASE_IDS, _LOCALES)}


def _original_cases():
    try:
        raw = DATASET_PATH.read_bytes()
    except OSError:
        raise ReadbackError('Original fifty-round dataset unavailable') from None
    _require(hashlib.sha256(raw).hexdigest() == DATASET_SHA256)
    dataset = _object(json.loads(raw))
    _require(dataset.get('schema_version') == 'memoir-five-case-inputs/1'
             and dataset.get('dataset_version') == DATASET_VERSION)
    cases = _list(dataset.get('cases'))
    _require(len(cases) == len(CASE_IDS))
    for case, case_id, locale in zip(cases, CASE_IDS, _LOCALES):
        _require(_object(case).get('id') == case_id and case.get('locale') == locale)
        rounds = _list(case.get('rounds'))
        _require(len(rounds) == 50 and all(type(text) is str and text.strip() for text in rounds))
        _require(len(set(rounds)) == 50)
    return cases


class FiftyReadback(_ConfiguredReadback):
    """Check 50 exact original inputs and ten ready, provenance-bound snapshots.

    The input file has positional strings, so dataset source identifiers are
    '<case_id>/round/<1-based ordinal>'. They identify the original hash-pinned
    inputs; application source IDs must be unique accepted narrator sources.
    Only the explicit subscription_fifty evidence label is accepted, and that
    caller-supplied label is not proof that a provider or subscription ran.
    """

    def __init__(self, *, case_id, run_id, project_id, source_revision):
        _require(case_id in CASE_IDS)
        _identifier(run_id)
        _identifier(project_id)
        original = next(case for case in _original_cases() if case['id'] == case_id)
        case = {'case_id': case_id, 'language': original['locale'], 'input': {
            'narrator_turns': [{'id': f'{case_id}/round/{ordinal}', 'version': 1, 'text': text}
                               for ordinal, text in enumerate(original['rounds'], 1)]}}
        self._configure(case=case, run_id=run_id, project_id=project_id,
            source_revision=source_revision, dataset_name=DATASET_VERSION, dataset_hash=DATASET_SHA256,
            checkpoints=CHECKPOINTS, evidence_modes=(EVIDENCE_MODE,),
            schema_version='memoir-fifty-readback/1', status_key='memoir_fifty_readback_status')
