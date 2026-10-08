"""Opt-in, deny-only evaluation admission. This never grants provider access.

Normal app instances use None and keep their existing behavior. The dedicated
issue 14 entry point requires an owned policy and still refuses execution.
Neither caller JSON nor an environment boolean can create live authority.
"""
from collections.abc import Mapping
from dataclasses import dataclass
import re
import threading
from uuid import UUID
from weakref import WeakKeyDictionary


class AdmissionDenied(RuntimeError):
    """Fixed content-free denial, not a retryable provider failure."""


ROLES = frozenset({'collector', 'workspace', 'classification', 'memory_context',
    'author_timeline', 'organiser', 'composer', 'composer_preparation',
    'composer_draft', 'composer_review', 'tool_loop', 'retry', 'native', 'judge', 'photo'})
_ISSUED = WeakKeyDictionary()
_LOCK = threading.RLock()


def _uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except (ValueError, AttributeError):
        return False


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False, eq=False)
class Issue14Admission:
    run_id: str
    source_revision: str

    def __init__(self):
        raise TypeError('Use deny_only; live admission is unavailable')

    @classmethod
    def deny_only(cls, *, run_id, source_revision):
        if (cls is not Issue14Admission or not _uuid(run_id)
                or type(source_revision) is not str
                or re.fullmatch('[a-f0-9]{40}', source_revision) is None):
            raise AdmissionDenied('admission_identity_invalid')
        instance = object.__new__(cls)
        object.__setattr__(instance, 'run_id', run_id)
        object.__setattr__(instance, 'source_revision', source_revision)
        with _LOCK:
            _ISSUED[instance] = {'closed': False, 'run_id': run_id, 'source_revision': source_revision}
        return instance

    def close(self):
        with _LOCK:
            _owned(self)['closed'] = True

    def receipt(self):
        with _LOCK:
            state = _owned(self)
            return {'mode': 'deny_only', 'run_id': state['run_id'],
                'source_revision': state['source_revision'], 'closed': state['closed'],
                'live_ready': False, 'actual_provider_requests': None,
                'real_provider_token_or_cost_limits_verified': False,
                'blockers': ['provider_capability_unverified', 'live_budget_not_approved',
                    'native_actual_send_integration_pending', 'judge_calibration_unavailable']}


def _owned(admission):
    if type(admission) is not Issue14Admission:
        raise AdmissionDenied('admission_missing_or_foreign')
    state = _ISSUED.get(admission)
    if (state is None or admission.run_id != state['run_id']
            or admission.source_revision != state['source_revision']):
        raise AdmissionDenied('admission_missing_or_foreign')
    return state


def validate_optional_issue14_admission(admission):
    """Only None means ordinary application mode; all other values are checked."""
    if admission is not None:
        with _LOCK:
            _owned(admission)
    return admission


def require_issue14_admission(admission, *, run_id, source_revision, role):
    """The dedicated execution path has no permissive branch, even when valid."""
    with _LOCK:
        state = _owned(admission)
        if state['closed']:
            raise AdmissionDenied('admission_closed')
        if run_id != state['run_id'] or source_revision != state['source_revision']:
            raise AdmissionDenied('admission_scope_mismatch')
        if type(role) is not str or role not in ROLES:
            raise AdmissionDenied('admission_role_invalid')
        raise AdmissionDenied('provider_capability_unverified')


def check_issue14_dispatch(admission, *, role, correlation=None):
    """Enforce an instance-owned opt-in independently of request metadata."""
    if admission is None:
        return
    with _LOCK:
        state = _owned(admission)
        if correlation is not None and not isinstance(correlation, Mapping):
            raise AdmissionDenied('admission_scope_mismatch')
        metadata = correlation or {}
        require_issue14_admission(admission,
            run_id=metadata.get('run_id', state['run_id']),
            source_revision=metadata.get('application_revision',
                metadata.get('source_revision', state['source_revision'])), role=role)


def issue14_connection_options(admission):
    """Do not change normal app constructor calls, including existing stubs."""
    validate_optional_issue14_admission(admission)
    return {} if admission is None else {'issue14_admission': admission}
