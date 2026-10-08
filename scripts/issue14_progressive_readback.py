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


DATASET_SHA256 = 'bea8a31f8d4ab0539e2f1c99e08978acbcb4d60ffc25bf36579f04c8a27392c7'
DATASET_PATH = Path(__file__).resolve().parents[1] / 'tests/evaluation/issue6_semantic_datasets.json'
CASE_IDS = ('chapters.transitions.en-AU', 'chapters.transitions.zh-CN')


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


class ProgressiveReadback:
    """Bind original inputs and readbacks; no live execution or admission API.

    driver_inputs() and before_round match CanonicalEvaluationDriver's existing
    hooks. Its historical five-round live limit stays intact. capture() consumes
    the returned terminal outcome, not the mutable running progress callbacks.
    """

    def __init__(self, *, case_id, run_id, project_id, source_revision):
        _require(case_id in CASE_IDS)
        self._run_id, self._project_id = _identifier(run_id), _identifier(project_id)
        _require(type(source_revision) is str and re.fullmatch('[0-9a-f]{40}', source_revision))
        self._revision = source_revision
        raw = DATASET_PATH.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == DATASET_SHA256)
        dataset = next(d for d in json.loads(raw)['datasets'] if d['dimension'] == 'chapter-continuity')
        self._dataset_name = dataset['name']
        self._case = deepcopy(next(i for i in dataset['items'] if i['case_id'] == case_id))

    def driver_inputs(self):
        """No expected answers, provider hints, credentials or execution mode."""
        return {'case_id': self._case['case_id'], 'project_id': self._project_id,
                'rounds': [s['text'] for s in self._case['input']['narrator_turns']],
                'language': self._case['language']}

    def before_round(self, case_id, ordinal):
        _require(case_id == self._case['case_id'])
        _integer(ordinal)
        _require(1 <= ordinal <= 15)
        binding = [self._run_id, self._revision, self._project_id, case_id, ordinal, DATASET_SHA256]
        trace_id = hashlib.sha256(json.dumps(binding, separators=(',', ':')).encode()).hexdigest()[:32]
        return {'run_id': self._run_id, 'case_id': case_id, 'round_id': str(ordinal),
                'trace_id': trace_id, 'application_revision': self._revision,
                'dataset': self._dataset_name, 'dataset_version': DATASET_SHA256}

    def capture(self, outcome):
        """Return a detached structural projection or raise ReadbackError.

        Only these checks are claimed: original input coverage, correlation,
        ready saved checkpoint shapes, reference resolution and same-fingerprint
        section preservation. No provider/cohort/word-limit/semantic acceptance.
        """
        result = _object(outcome)
        case_id, locale = self._case['case_id'], self._case['language']
        _require(result.get('status') == 'completed' and result.get('case_id') == case_id
                 and result.get('project_id') == self._project_id)
        _require(result.get('evidence_mode') in ('mock_only', 'guarded_live_canary'))
        rounds = _list(result.get('rounds'))
        _require(len(rounds) == 15)
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
        _require(len(checkpoints) == 3)
        saved, previous = [], {}
        last_revision = 0
        last_snapshot = None
        for checkpoint, ordinal in zip(checkpoints, (5, 10, 15)):
            _integer(_object(checkpoint).get('milestone'), ordinal)
            draft = _object(checkpoint.get('draft'))
            _require(draft.get('status') == 'ready' and draft.get('updating') is False
                     and draft.get('error') is None and draft.get('proposal_pending') is False)
            _integer(draft.get('covered_round'), ordinal)
            _integer(draft.get('milestone'), ordinal)
            revision = _integer(draft.get('revision'))
            _require(revision > 0 and revision >= last_revision)
            preview = _object(draft.get('preview'))
            _require(preview.get('locale') == locale and type(preview.get('text')) is str and preview['text'].strip())
            snapshot = {'preview': preview, 'sections': _list(draft.get('sections'))}
            if revision == last_revision:
                _require(snapshot == last_snapshot)
            last_revision, last_snapshot = revision, deepcopy(snapshot)
            extraction = _object(_object(draft.get('progress')).get('extraction'))
            _integer(extraction.get('extracted_through'), ordinal)
            _integer(extraction.get('pending_inputs'), 0)
            milestones = _list(draft.get('milestones'))
            _require(len(milestones) == ordinal // 5)
            for row, old in zip(milestones, range(5, ordinal + 1, 5)):
                _integer(_object(row).get('milestone'), old)
                _integer(row.get('covered_round'), old)
                _require(row.get('state') == 'completed')
                _integer(row.get('manuscript_revision'), revision if old == ordinal else saved[old // 5 - 1]['revision'])
            sections, ids = [], set()
            for section in _list(draft.get('sections')):
                section = _object(section)
                section_id = _identifier(section.get('id'))
                _require(section_id not in ids)
                ids.add(section_id)
                _require(type(section.get('content')) is str and section['content'].strip())
                _require(type(section.get('fingerprint')) is str and re.fullmatch('[0-9a-f]{64}', section['fingerprint']))
                _require(_integer(section.get('revision')) > 0)
                projection = {k: section[k] for k in ('id', 'content', 'fingerprint', 'revision')}
                projection['chapter_id'] = _identifier(section.get('chapter_id'))
                projection['source_refs'] = _references(section.get('source_refs'), states[ordinal])
                _require(projection['source_refs'])
                prior = previous.get(section_id)
                if prior and prior['fingerprint'] == projection['fingerprint']:
                    _require(prior == section)
                elif prior:
                    _require(projection['revision'] > prior['revision'])
                previous[section_id] = deepcopy(section)
                sections.append(projection)
            _require(sections)
            saved.append({'milestone': ordinal, 'covered_round': ordinal, 'revision': revision, 'sections': sections})
        return deepcopy({'schema_version': 'memoir-progressive-readback/1',
            'status': 'structural_readback_complete', 'case_id': case_id, 'language': locale,
            'run_id': self._run_id, 'project_id': self._project_id, 'source_revision': self._revision,
            'dataset_content_hash': DATASET_SHA256, 'declared_evidence_mode': result['evidence_mode'],
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
            return {'output': None, 'metadata': {'issue14_progressive_readback_status': 'unavailable', 'live_ready': False}}
        return {'output': evidence, 'metadata': {
            'issue14_progressive_readback_status': evidence['status'], 'live_ready': False}}
