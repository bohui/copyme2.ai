"""Task-only Codex worker with an authenticated owned gateway lease.

Controlled fixtures and native Codex have separate constructors. Live access
requires the lease's owned actor/socket; a URL or readiness JSON is insufficient.
"""
import asyncio
import hashlib
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit

from apps.api.codex_worker_service import CodexWorker
from scripts.run_codexlb_canary import APPROVED_ACCOUNT_BINDING


class CanaryWorker(CodexWorker):
    def __init__(self, *, home_root, base_url, evidence_mode, command_prefix=None):
        if evidence_mode != 'controlled_provider':
            raise ValueError('Live mode requires a reviewed installed gateway dispatch binding')
        self._validate_endpoint(base_url)
        fixtures = Path(__file__).resolve().parents[1] / 'tests/fixtures'
        if (not isinstance(command_prefix, (list, tuple)) or len(command_prefix) != 3
                or Path(command_prefix[0]).resolve() != Path(sys.executable).resolve()
                or Path(command_prefix[1]).resolve() not in {
                    fixtures / 'issue6_controlled_app_server.py',
                    fixtures / 'canary_audited_app_server.py'}):
            raise ValueError('Only an explicit checked-in controlled app-server fixture is allowed')
        self._configure(home_root, base_url, command_prefix, 'synthetic-only', evidence_mode)

    @classmethod
    def for_gateway_lease(cls, *, home_root, lease, codex_binary, expected_sha256):
        from scripts.canary_gateway_bridge import NativeGatewayLease
        if not isinstance(lease, NativeGatewayLease):
            raise ValueError('An owned native gateway lease is required')
        lease.assert_ready()
        cls._validate_endpoint(lease.base_url)
        binary = Path(codex_binary)
        if (not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK)
                or not re.fullmatch('[a-f0-9]{64}', expected_sha256)
                or hashlib.sha256(binary.read_bytes()).hexdigest() != expected_sha256):
            raise ValueError('The exact independently reviewed installed Codex executable is required')
        worker = object.__new__(cls)
        worker._configure(home_root, lease.base_url, [str(binary)],
                          lease.consumer_key_for_owned_worker(), 'guarded_live_canary', lease=lease)
        worker.codex_binary_sha256 = expected_sha256
        return worker

    @staticmethod
    def _validate_endpoint(base_url):
        url = urlsplit(base_url)
        if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.path != '/v1'
                or url.username or url.password or url.query or url.fragment
                or url.port is None or url.port < 1024 or url.port in {2455, 4000}):
            raise ValueError('An explicit disposable loopback provider endpoint is required')

    def _configure(self, home_root, base_url, command_prefix, api_key, evidence_mode, *, lease=None):
        home = Path(home_root)
        if home.exists() or home.is_symlink():
            raise ValueError('A fresh task home is required')
        home.mkdir(mode=0o700)
        options = ['model_providers.llm_provider.request_max_retries=0',
            'model_providers.llm_provider.stream_max_retries=0',
            'model_providers.llm_provider.stream_idle_timeout_ms=60000',
            'model_providers.llm_provider.supports_websockets=false',
            'features.memories=false', 'memories.generate_memories=false',
            'memories.use_memories=false', 'web_search="disabled"']
        command = list(command_prefix)
        for option in options:
            command.extend(['-c', option])
        command.append('app-server')
        super().__init__(home_root=home, command=command, base_url=base_url,
            model='gpt-5.6-luna', timeout=240, api_key=api_key, reasoning_effort='low')
        # Never migrate an inherited customer's Codex home into this task.
        self.legacy_root = None
        self.evidence_mode = evidence_mode
        self.gateway_lease = lease
        self._serial = asyncio.Lock()
        self._stopped = False
        self._pinned_command = tuple(command)
        self.before_dispatch = None

    def assert_live_ready(self, *, run_id=None, source_revision=None, account_binding=APPROVED_ACCOUNT_BINDING):
        if (self.evidence_mode != 'guarded_live_canary' or self.gateway_lease is None or self._stopped
                or self.base_url != self.gateway_lease.base_url or self.model != 'gpt-5.6-luna'
                or tuple(self.command) != self._pinned_command):
            raise ValueError('Live evaluation requires a verified provider accounting adapter')
        return self.gateway_lease.assert_ready(run_id=run_id, source_revision=source_revision,
                                              account_binding=account_binding)

    async def turn(self, payload, on_delta=None, on_event=None):
        if payload.agent_role not in {'collector', 'workspace', 'memory_context', 'author_timeline', 'composer'}:
            raise ValueError('Worker role is outside the approved canary')
        if payload.model not in {None, 'gpt-5.6-luna'}:
            raise ValueError('The canary role model differs from the pinned model')
        payload = payload.model_copy(update={'model': 'gpt-5.6-luna'})
        async with self._serial:
            if self._stopped:
                raise RuntimeError('Canary worker stopped after an earlier failure')
            if self.evidence_mode == 'guarded_live_canary':
                self.assert_live_ready()
            try:
                if self.before_dispatch is not None:
                    self.before_dispatch()
                async with asyncio.timeout(300):
                    return await super().turn(payload, on_delta=on_delta, on_event=on_event)
            except BaseException:
                self._stopped = True
                if self.gateway_lease is not None:
                    await self.gateway_lease.stop()
                raise
