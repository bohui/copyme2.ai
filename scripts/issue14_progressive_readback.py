"""Pure correlation/readback bridge for the two reviewed 15-turn chapter cases.

Nothing here dispatches an application, model, judge or Langfuse experiment.
The caller must obtain returned outcomes from a separately admitted executor.
Shape validation cannot authenticate that caller or prove durable execution.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID, uuid5

from scripts.memoir_checkpoint_readback import (
    CheckpointReadbackError, checkpoint_binding, checkpoint_records,
)


DATASET_SHA256 = 'bea8a31f8d4ab0539e2f1c99e08978acbcb4d60ffc25bf36579f04c8a27392c7'
DATASET_PATH = Path(__file__).resolve().parents[1] / 'tests/evaluation/issue6_semantic_datasets.json'
CASE_IDS = ('chapters.transitions.en-AU', 'chapters.transitions.zh-CN')


def case_plans_for_run(run_id):
    """Pure synthetic identity plan; imports no app/worker/credential code."""
    namespace = UUID(run_id)
    if str(namespace) != run_id:
        raise ValueError('Canonical run UUID required')
    return {case_id: {'case_id': case_id, 'owner_id': str(uuid5(namespace, case_id + '/owner')),
        'project_id': str(uuid5(namespace, case_id + '/project')), 'language': case_id.rsplit('.', 1)[1]}
        for case_id in CASE_IDS}


class ReadbackError(ValueError):
    """Incomplete, stale or mismatched evidence; never a semantic score."""


def _require(condition):
    if not condition:
        raise ReadbackError('Progressive application readback unavailable or inconsistent')


def _identifier(value):
    _require(type(value) is str and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,256}', value))
    return value


def _integer(value, expected=None):
    _require(type(value) is int and value >= 0 and (expected is None or value == expected))
    return value


def _object(value):
    _require(type(value) is dict)
    return value


def _list(value):
    _require(type(value) is list)
    return value


def _references(refs, originals):
    """Resolve original spans only. This is not a factual-entailment test."""
    projected = []
    for ref in _list(refs):
        ref = _object(ref)
        source = originals.get(_identifier(ref.get('source_id')))
        _require(source is not None)
        version = ref.get('version')
        _require((type(version) is int or type(version) is str) and str(version) == str(source['version']))
        text = source['text']
        has_span = 'char_start' in ref or 'char_end' in ref
        if has_span:
            start, end = _integer(ref.get('char_start')), _integer(ref.get('char_end'))
            _require(start < end <= len(text))
            if 'quote' in ref:
                _require(ref['quote'] == text[start:end])
        else:
            _require(type(ref.get('quote')) is str and ref['quote'] and ref['quote'] in text)
        projected.append({key: ref[key] for key in ('source_id', 'version', 'char_start', 'char_end', 'quote') if key in ref})
    return projected


class _ConfiguredReadback:
    """Private structural checks shared by explicit, separately pinned profiles."""

    def _configure(self, *, case, run_id, project_id, source_revision,
                   dataset_name, dataset_hash, checkpoints, evidence_modes,
                   schema_version, status_key):
        self._run_id, self._project_id = _identifier(run_id), _identifier(project_id)
        _require(type(source_revision) is str and re.fullmatch('[0-9a-f]{40}', source_revision))
        self._revision = source_revision
        self._dataset_name, self._dataset_hash = dataset_name, dataset_hash
        self._checkpoints, self._evidence_modes = tuple(checkpoints), tuple(evidence_modes)
        self._round_count = self._checkpoints[-1]
        self._schema_version, self._status_key = schema_version, status_key
        self._case = deepcopy(case)

    def driver_inputs(self):
        """No expected answers, provider hints, credentials or execution mode."""
        return {'case_id': self._case['case_id'], 'project_id': self._project_id,
                'rounds': [s['text'] for s in self._case['input']['narrator_turns']],
                'language': self._case['language']}

    def before_round(self, case_id, ordinal):
        _require(case_id == self._case['case_id'])
        _integer(ordinal)
        _require(1 <= ordinal <= self._round_count)
        binding = [self._run_id, self._revision, self._project_id, case_id, ordinal, self._dataset_hash]
        trace_id = hashlib.sha256(json.dumps(binding, separators=(',', ':')).encode()).hexdigest()[:32]
        return {'run_id': self._run_id, 'case_id': case_id, 'round_id': str(ordinal),
                'trace_id': trace_id, 'application_revision': self._revision,
                'dataset': self._dataset_name, 'dataset_version': self._dataset_hash}

    def capture(self, outcome):
        """Return a detached structural projection or raise ReadbackError.

        Only these checks are claimed: original input coverage, correlation,
        ready frozen snapshots, complete bounded pages, reference resolution and
        preservation of records with unchanged event/source dependencies.
        No provider/cohort/word-limit/semantic acceptance.
        """
        result = _object(outcome)
        case_id, locale = self._case['case_id'], self._case['language']
        _require(result.get('status') == 'completed' and result.get('case_id') == case_id
                 and result.get('project_id') == self._project_id)
        _require(result.get('evidence_mode') in self._evidence_modes)
        rounds = _list(result.get('rounds'))
        _require(len(rounds) == self._round_count)
        accepted, mappings, states = [], [], {}
        for ordinal, record in enumerate(rounds, 1):
            record = _object(record)
            _integer(record.get('round'), ordinal)
            _require(record.get('status') == 'completed' and record.get('background_settled') is True)
            trajectory = _object(record.get('trajectory'))
            correlation = _object(trajectory.get('correlation'))
            _require(all(correlation.get(k) == v for k, v in self.before_round(case_id, ordinal).items()))
            _require(_object(trajectory.get('final')).get('status') == 'completed')
            source_id = _identifier(record.get('accepted_source_id'))
            _require(source_id not in accepted)
            accepted.append(source_id)
            view = _object(record.get('canonical_state'))
            _require(view.get('project_id') == self._project_id)
            _integer(view.get('completed_rounds'), ordinal)
            processing = _object(view.get('processing'))
            _integer(processing.get('extracted_through'), ordinal)
            _integer(processing.get('pending_inputs'), 0)
            sources = _list(view.get('sources'))
            _require(len(sources) == ordinal)
            for index, (source, original) in enumerate(zip(sources, self._case['input']['narrator_turns']), 1):
                source = _object(source)
                _require(source.get('id') == accepted[index - 1] and source.get('text') == original['text']
                         and source.get('project_id') == self._project_id and source.get('language') == locale
                         and source.get('kind') == 'narrator_chat' and source.get('status') == 'active')
                _integer(source.get('version'), original['version'])
                _integer(source.get('sequence'), index)
            states[ordinal] = {s['id']: s for s in sources}
            mappings.append({'dataset_source_id': self._case['input']['narrator_turns'][ordinal-1]['id'],
                             'application_source_id': source_id, 'version': 1, 'round': ordinal,
                             'trace_id': correlation['trace_id']})
        checkpoints = _list(result.get('checkpoints'))
        _require(len(checkpoints) == len(self._checkpoints))
        identity = _object(result.get('canonical_identity'))
        try:
            binding = checkpoint_binding(identity, identity.get('owner_id'), self._project_id, locale)
        except CheckpointReadbackError:
            _require(False)
        saved, previous, snapshots = [], {}, {}
        last_revision, last_records = 0, None
        for checkpoint, ordinal in zip(checkpoints, self._checkpoints):
            _integer(_object(checkpoint).get('milestone'), ordinal)
            _require(checkpoint.get('identity') == binding)
            try:
                records = checkpoint_records(checkpoint, binding, ordinal, states[ordinal])
            except CheckpointReadbackError:
                _require(False)
            draft = checkpoint['draft']
            revision = draft['revision']
            _require(revision >= last_revision)
            authority = (draft['policy_epoch'], checkpoint['pages'][0]['preference_revision'])
            projections = []
            for record in records:
                projection = {key: record[key] for key in ('id', 'event_id', 'event_revision')}
                projection['preview'] = {key: record['preview'][key] for key in ('locale', 'text')}
                projection['source_refs'] = _references(record['source_refs'], states[ordinal])
                prior_entry = previous.get(record['id'])
                if prior_entry:
                    prior_authority, prior = prior_entry
                    _require(prior['event_id'] == projection['event_id'])
                    _require(projection['event_revision'] >= prior['event_revision'])
                    if (authority == prior_authority and prior['event_revision'] == projection['event_revision']
                            and prior['source_refs'] == projection['source_refs']):
                        _require(prior == projection)
                previous[record['id']] = (authority, deepcopy(projection))
                projections.append(projection)
            if revision == last_revision:
                _require(projections == last_records)
            last_revision, last_records = revision, deepcopy(projections)
            frozen = {key: draft[key] for key in (
                'root_digest', 'source_revision', 'event_revision', 'policy_epoch')}
            frozen['preference_revision'] = authority[1]
            frozen['records'] = projections
            if draft['snapshot_id'] in snapshots:
                _require(snapshots[draft['snapshot_id']] == frozen)
            snapshots[draft['snapshot_id']] = deepcopy(frozen)
            saved.append({'milestone': ordinal, 'coverage_round': ordinal, 'revision': revision,
                'snapshot_id': draft['snapshot_id'], 'root_digest': draft['root_digest'], 'records': projections})
        return deepcopy({'schema_version': self._schema_version,
            'status': 'structural_readback_complete', 'case_id': case_id, 'language': locale,
            'run_id': self._run_id, 'project_id': self._project_id, 'source_revision': self._revision,
            'dataset_content_hash': self._dataset_hash, 'declared_evidence_mode': result['evidence_mode'],
            'source_mapping': mappings, 'saved_checkpoints': saved,
            'evidence_basis': 'caller_supplied_application_readback', 'durability_verified': False,
            'provider_cohort_verified': False, 'live_ready': False,
            'semantic_acceptance': 'human_review_required',
            'unassessed': ['chapter_word_limit', 'canonical_event_entailment', 'provider_usage', 'bilingual_cohort']})

    def observation(self, outcome):
        """SDK-neutral data only; missing evidence must produce null output."""
        try:
            evidence = self.capture(outcome)
        except ReadbackError:
            return {'output': None, 'metadata': {self._status_key: 'unavailable', 'live_ready': False}}
        return {'output': evidence, 'metadata': {
            self._status_key: evidence['status'], 'live_ready': False}}


class ProgressiveReadback(_ConfiguredReadback):
    """Bind the original two 15-turn cases without broadening their guards.

    driver_inputs() and before_round match CanonicalEvaluationDriver's existing
    hooks. Its historical five-round live limit stays intact. capture() consumes
    the returned terminal outcome, not the mutable running progress callbacks.
    """

    def __init__(self, *, case_id, run_id, project_id, source_revision):
        _require(case_id in CASE_IDS)
        # Validate caller context before loading any dataset, as historically.
        _identifier(run_id)
        _identifier(project_id)
        _require(type(source_revision) is str and re.fullmatch('[0-9a-f]{40}', source_revision))
        raw = DATASET_PATH.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == DATASET_SHA256)
        dataset = next(d for d in json.loads(raw)['datasets'] if d['dimension'] == 'chapter-continuity')
        case = next(i for i in dataset['items'] if i['case_id'] == case_id)
        self._configure(case=case, run_id=run_id, project_id=project_id,
            source_revision=source_revision, dataset_name=dataset['name'], dataset_hash=DATASET_SHA256,
            checkpoints=(5, 10, 15),
            evidence_modes=('mock_only', 'guarded_live_canary', 'subscription_progressive'),
            schema_version='memoir-progressive-readback/1', status_key='issue14_progressive_readback_status')
