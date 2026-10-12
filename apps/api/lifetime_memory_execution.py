"""Disposable engine execution, separate from product and retry identities.

The caller constructs a current authorized canonical packet and validates its
fence; this helper never installs a database pointer or restores harness files.
"""
from copy import deepcopy


class ExecutionStateUnavailable(RuntimeError):
    def __init__(self, reason):
        if reason not in {'missing', 'corrupt', 'incompatible'}:
            raise ValueError('unrecognized execution-state failure')
        self.reason = reason
        super().__init__('Disposable execution state is ' + reason)


def _thread_id(result):
    thread = result.get('thread') if isinstance(result, dict) else None
    value = thread.get('id') if isinstance(thread, dict) else None
    if not isinstance(value, str) or not value.strip() or len(value)>512:
        raise ExecutionStateUnavailable('corrupt')
    return value


async def open_execution(connection, *, thread_id, compatible, start_params, identity):
    """One resume attempt and at most one cold start; auth/provider errors escape.

    ``compatible`` must include schema/model/prompt, policy/source and execution
    generation checks. Lifetime round count is deliberately absent. The returned
    pointer is a candidate only: the existing turn lease/fence must commit it.
    """
    reason = None
    if thread_id and compatible:
        try:
            result = await connection.request('thread/resume', {**start_params, 'threadId':thread_id})
            return {'thread_id':_thread_id(result), 'identity':deepcopy(identity), 'cold_resume_reason':None}
        except ExecutionStateUnavailable as error:
            reason = error.reason
    else:
        reason = 'incompatible' if thread_id else 'missing'
    result = await connection.request('thread/start', dict(start_params))
    return {'thread_id':_thread_id(result), 'identity':deepcopy(identity), 'cold_resume_reason':reason}
