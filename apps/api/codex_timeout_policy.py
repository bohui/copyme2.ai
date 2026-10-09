"""Pure worker deadline defaults; importing this module allocates nothing."""

WORKER_TIMEOUT = 120
WORKER_MAX_TIMEOUT = 240
WORKSPACE_TIMEOUT = 240
COMPOSER_TIMEOUT = 240
COMPOSER_DRAFT_TIMEOUT = 600


def native_worker_deadlines():
    # Native evaluation uses offline_environment, which never inherits the
    # worker timeout override. Return fresh data without importing the service.
    return {'scope': 'whole_worker_execution', 'timeout_override_inherited': False,
        'seconds_by_role': {'collector': WORKER_TIMEOUT, 'organiser': WORKER_TIMEOUT,
            'memory_context': WORKER_TIMEOUT, 'author_timeline': WORKER_TIMEOUT,
            'workspace': WORKSPACE_TIMEOUT,
            'composer': {'index': COMPOSER_TIMEOUT, 'prepare': COMPOSER_TIMEOUT,
                'draft': COMPOSER_DRAFT_TIMEOUT, 'review': COMPOSER_TIMEOUT}}}
