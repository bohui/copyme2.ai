"""Actual actor protocol + guard, without installed imports or real credentials."""
import asyncio
from contextlib import aclosing
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.canary_gateway_actor import serve_frames, expected_source_hashes
from scripts.canary_send_guard import CanarySendGuard, CanaryStopped

control_path = Path(sys.argv[1])
control = json.loads(control_path.read_text())


class ControlledRuntime:
    def __init__(self, config):
        assert config['consumer_authorization'] == 'Bearer synthetic-consumer-only'
        assert config['source_sha256'] == expected_source_hashes()
        self.source_sha256 = expected_source_hashes()
        self.consumer_binding = hashlib.sha256(b'controlled-consumer').hexdigest()
        self.guard = CanarySendGuard(reservation=control_path.with_suffix('.reservation'),
            run_id=config['run_id'], source_revision=config['source_revision'],
            account_binding=config['account_binding'], model='gpt-5.6-luna', maximum_requests=2)
    def receipt(self):
        result = self.guard.receipt()
        result['binding'] = {'accepting_requests': not self.guard.closed and not self.guard.stop_reason
            and len(self.guard.entries) < self.guard.maximum_requests}
        result['controlled_external_provider'] = True
        return result
    async def responses(self, headers, body):
        assert headers['authorization'] == 'Bearer synthetic-consumer-only'
        if control['mode'] == 'http_failure':
            self.guard.stop('upstream_failed_or_incomplete')
            return 503, {'content-type': 'application/json'}, '{"error":"controlled_failure"}'
        async def send(payload):
            if control['mode'] == 'terminal_failure':
                yield 'data: {"type":"response.failed"}\n\n'
            else:
                yield 'data: ' + json.dumps({'type': 'response.completed', 'response': {
                    'id': 'resp_controlled', 'model': 'gpt-5.6-luna', 'usage': {'input_tokens': 1, 'output_tokens': 1}}}) + '\n\n'
        try:
            correlation = {**body['client_metadata'], 'request_id': 'gateway-' + str(len(self.guard.entries) + 1)}
            async with aclosing(self.guard.stream(send, payload=body, transport='http',
                    account_binding=self.guard.account_binding, correlation=correlation)) as stream:
                result = ''.join([chunk async for chunk in stream])
        except CanaryStopped:
            result = 'data: {"type":"response.failed","error":{"code":"controlled_failure"}}\n\n'
        return 200, {'content-type': 'text/event-stream'}, result
    async def stop(self):
        await self.guard.aclose()
        return self.receipt()


async def main():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=16 * 1024 * 1024 + 1)
    transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    async def factory(config): return ControlledRuntime(config)
    async def emit(raw):
        sys.stdout.buffer.write(raw)
        sys.stdout.buffer.flush()
    try:
        await serve_frames(reader.readline, emit, runtime_factory=factory)
    finally:
        transport.close()
asyncio.run(main())
