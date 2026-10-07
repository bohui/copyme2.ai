"""Hidden, task-lifetime input of an existing gateway consumer credential.

This module never creates a key, changes authentication configuration or writes
credentials. Importing it reads no secret. The native owner must authorize and
preflight the exact actor/worker before invoking the context manager.
"""
from contextlib import asynccontextmanager, contextmanager
import getpass
import os
import sys
import warnings

TASK_KEY_NAME = 'MEMOIR_CANARY_GATEWAY_API_KEY'


class TaskConsumerAuthorization:
    """Redacted holder; clear references at the end of the owned task scope."""
    def __init__(self, key):
        if (not isinstance(key, str) or not 8 <= len(key) <= 4096
                or any(not 33 <= ord(char) <= 126 for char in key)):
            raise ValueError('A nonempty existing gateway consumer key is required')
        self._key = key

    def __repr__(self):
        return '<TaskConsumerAuthorization redacted>'

    def __reduce_ex__(self, protocol):
        raise TypeError('Task authentication cannot be serialized')

    def authorization_header(self):
        if self._key is None:
            raise RuntimeError('Task authentication has been cleared')
        return 'Bearer ' + self._key

    def clear(self):
        self._key = None


@contextmanager
def task_consumer_authorization(*, input_mode='prompt', on_input_read=None):
    """Read only an explicit hidden prompt or the dedicated task environment.

    A task environment value is removed immediately from this process; normal
    Memoir/LiteLLM variables and project files are neither read nor changed.
    Python strings cannot guarantee memory zeroization; references are cleared
    best effort and no persistence or secure-erasure guarantee is claimed.
    on_input_read receives no values and records returned input before shape
    validation; absent input, EOF and blocked echo fallback do not invoke it.
    """
    raw, secret = None, None
    try:
        if input_mode == 'environment':
            raw = os.environ.pop(TASK_KEY_NAME, None)
        elif input_mode == 'prompt':
            if not sys.stdin.isatty():
                raise ValueError('Hidden gateway-key input requires a private local terminal')
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', getpass.GetPassWarning)
                    raw = getpass.getpass(prompt='Existing gateway consumer key (hidden): ')
            except getpass.GetPassWarning:
                raise ValueError('A hidden prompt is unavailable; echo fallback is forbidden') from None
        else:
            raise ValueError('Choose the hidden prompt or dedicated task environment')
        if raw is not None and on_input_read is not None:
            on_input_read()
        secret = TaskConsumerAuthorization(raw)
        raw = None
        yield secret
    finally:
        raw = None
        if secret is not None:
            secret.clear()


@asynccontextmanager
async def authenticated_canary_worker(*, actor_options, home_root, codex_binary,
                                      expected_codex_sha256, input_mode='prompt', before_actor_start=None,
                                      on_actor_started=None, on_input_read=None):
    """Keep existing auth inside the owned lease/worker lifetime, then clear it.

    actor_options contains only the reviewed actor command, run/source/account
    identity and source hashes. It must never contain authentication itself.
    The caller supplies and owns PostgreSQL/Temporal and the application run.
    """
    from scripts.canary_gateway_bridge import NativeGatewayLease
    from scripts.canary_worker import CanaryWorker
    if 'consumer_authorization' in actor_options:
        raise ValueError('Authentication must enter through the hidden task input')
    NativeGatewayLease.validate_native_target(**actor_options)
    lease, worker = None, None
    with task_consumer_authorization(input_mode=input_mode, on_input_read=on_input_read) as secret:
        try:
            if before_actor_start is not None:
                before_actor_start()
            lease = await NativeGatewayLease.start_native(**actor_options,
                consumer_authorization=secret.authorization_header())
            if on_actor_started is not None:
                on_actor_started(lease.receipt())
            worker = CanaryWorker.for_gateway_lease(home_root=home_root, lease=lease,
                codex_binary=codex_binary, expected_sha256=expected_codex_sha256)
            yield worker
        finally:
            if worker is not None:
                worker.api_key = ''
            if lease is not None:
                await lease.stop()


def main():
    """Optional input-shape check only, with zero authentication/model calls."""
    import argparse
    import json
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            # Never echo unknown argv values: a user might mistakenly put a
            # credential there. Accepted options have no credential argument.
            self.exit(2, 'Invalid options; enter credentials only through the hidden task input.\n')
    parser = SafeParser(description=__doc__)
    parser.add_argument('--check-input', action='store_true', required=True)
    parser.add_argument('--input-mode', choices=('prompt', 'environment'), default='prompt')
    args = parser.parse_args()
    try:
        with task_consumer_authorization(input_mode=args.input_mode):
            pass
    except (ValueError, EOFError, KeyboardInterrupt):
        print(json.dumps({'status': 'input_unavailable', 'gateway_auth_verified': False,
                          'provider_requests_started': 0}))
        return 3
    print(json.dumps({'status': 'input_shape_valid_and_cleared', 'gateway_auth_verified': False,
                      'provider_requests_started': 0}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
