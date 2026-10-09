"""Pure worker deadline defaults; importing this module allocates nothing."""
import math

WORKER_TIMEOUT = 120
WORKER_MAX_TIMEOUT = 240
WORKSPACE_TIMEOUT = 240
COMPOSER_TIMEOUT = 240
COMPOSER_DRAFT_TIMEOUT = 600


def validate_native_collector_timeout(seconds):
    # Validate before any session/output allocation. Do not silently clamp a
    # campaign setting or inherit the normal product's environment override.
    if (type(seconds) not in (int, float) or not .001 <= seconds <= WORKER_MAX_TIMEOUT
            or not math.isfinite(seconds)):
        raise ValueError('Explicit collector timeout must be finite and between 0.001 and 240 seconds')
    return seconds


def native_worker_deadlines(collector_timeout_seconds=WORKER_TIMEOUT):
    # Native evaluation uses offline_environment, which never inherits the
    # worker timeout override. Return fresh data without importing the service.
    collector_timeout_seconds = validate_native_collector_timeout(collector_timeout_seconds)
    return {'scope': 'whole_worker_execution', 'timeout_override_inherited': False,
        'seconds_by_role': {'collector': collector_timeout_seconds, 'organiser': WORKER_TIMEOUT,
            'memory_context': WORKER_TIMEOUT, 'author_timeline': WORKER_TIMEOUT,
            'workspace': WORKSPACE_TIMEOUT,
            'composer': {'index': COMPOSER_TIMEOUT, 'prepare': COMPOSER_TIMEOUT,
                'draft': COMPOSER_DRAFT_TIMEOUT, 'review': COMPOSER_TIMEOUT}}}
