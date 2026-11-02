"""Scripted native protocol boundary, retaining the real HTTP/SSE decoder."""
from copy import deepcopy
import json

import httpx

from apps.api import conversation_reply_transport as transport


def install_native_provider(monkeypatch, provider):
    from apps.api import lifetime_memory_engine, codex_worker_service
    class Body:
        def __init__(self, content, admission):
            self.content, self.admission = content, admission

        async def __aiter__(self):
            async with self.admission():
                yield self.content

        async def aclose(self):
            pass
    class Connection:
        histories = {}
        def __init__(self, command, home, **options):
            self.options = options

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def request(self, method, params):
            async with self.options['request_admission']():
                if method == 'thread/start':
                    thread = 'native-' + str(len(self.histories))
                    self.histories[thread] = [dict(role='developer', content=[
                        dict(type='input_text', text=params['baseInstructions'])])]
                else:
                    thread = params['threadId']
                if method == 'thread/inject_items':
                    for item in params['items']:
                        self.histories[thread].append(dict(role=item['role'], content=item['content'][0]['text']))
                return {'thread': {'id': thread}}

        async def turn(self, thread_id, text, *, output_schema=None, on_delta=None, **kwargs):
            history = self.histories[thread_id]
            history.append(dict(role='user', content=text))
            body = dict(model='controlled-native', input=deepcopy(history),
                metadata=kwargs.get('responsesapi_client_metadata', {}),
                text=dict(format=dict(type='json_schema', schema=output_schema)))
            encoded = json.dumps(body).encode()
            raw, _ = await transport.stream_document(request=Body(encoded, self.options['request_admission']),
                content_length=len(encoded), base_url='http://provider.invalid/v1',
                api_key=self.options['provider_env']['MEMORY_SPARK_LLM_API_KEY'], timeout=2,
                transport=httpx.MockTransport(provider), on_delta=on_delta)
            history.append(dict(role='assistant', content=raw))
            return raw
    monkeypatch.setattr(lifetime_memory_engine, 'CodexConnection', Connection)
    monkeypatch.setattr(codex_worker_service, 'CodexConnection', Connection)
    return Connection
