from __future__ import annotations

import base64
import io
import json
import wave

import httpx
import pytest

from apps.api import llm_tracing
from apps.api.speech import DoubaoSpeechService, GeminiSpeechService, OpenAISpeechService


class FakeObservation:
    def __init__(self, fields):
        self.fields = fields
        self.updates = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.closed = True
        return False

    def update(self, **fields):
        self.updates.append(fields)


class FakeLangfuse:
    def __init__(self):
        self.observations = []

    def start_as_current_observation(self, **fields):
        observation = FakeObservation(fields)
        self.observations.append(observation)
        return observation


def test_direct_trace_records_safe_generation_metadata_and_closes(monkeypatch):
    client = FakeLangfuse()
    monkeypatch.setattr(llm_tracing, "_client_cache", client)

    with llm_tracing.trace_llm_call(
        "test.generation",
        "test-model",
        input_summary={"kind": "text", "characters": 12},
        metadata={"endpoint": "test"},
    ) as observation:
        llm_tracing.update_llm_trace(
            observation,
            output={"kind": "json", "fields": ["status"]},
            usage_details={"input": 3, "output": 2},
        )

    assert client.observations[0].fields["name"] == "test.generation"
    assert client.observations[0].fields["input"] == {"kind": "text", "characters": 12}
    assert client.observations[0].updates == [{
        "output": {"kind": "json", "fields": ["status"]},
        "usage_details": {"input": 3, "output": 2},
    }]
    assert client.observations[0].closed


def test_direct_trace_marks_errors_but_preserves_provider_error(monkeypatch):
    client = FakeLangfuse()
    monkeypatch.setattr(llm_tracing, "_client_cache", client)

    with pytest.raises(RuntimeError, match="provider failed"):
        with llm_tracing.trace_llm_call("test.failure", "test-model"):
            raise RuntimeError("provider failed")

    assert client.observations[0].updates == [{
        "level": "ERROR",
        "status_message": "test.failure failed: RuntimeError",
    }]
    assert client.observations[0].closed


def test_skill_metadata_keeps_the_coordinator_trace_and_scope_does_not_leak(monkeypatch):
    monkeypatch.setattr(llm_tracing,'_client_cache',FakeLangfuse())
    with llm_tracing.trace_llm_call('memoir-background-agent','synthetic',gateway=True):
        with llm_tracing.trace_skill_execution('memoir-memory-context','profile'):
            assert llm_tracing.gateway_metadata('memoir-memory-context')=={
                'generation_name':'memoir-memory-context','trace_name':'memoir-background-agent'}
    assert llm_tracing.gateway_metadata('memoir-interviewer')=={
        'generation_name':'memoir-interviewer','trace_name':'memoir-interviewer'}


def test_unavailable_tracing_does_not_block_execution(monkeypatch):
    class Unavailable:
        def start_as_current_observation(self,**fields):
            raise RuntimeError('Tracing is offline')
    monkeypatch.setattr(llm_tracing,'_client_cache',Unavailable())
    executed=[]
    with llm_tracing.trace_skill_execution('memoir-memory-context','profile'):
        executed.append(True)
    assert executed==[True]


def test_background_trace_scope_does_not_change_a_concurrent_foreground_trace(monkeypatch):
    import asyncio
    monkeypatch.setattr(llm_tracing,'_client_cache',FakeLangfuse())
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        async def background():
            with llm_tracing.trace_llm_call('memoir-background-agent','synthetic',gateway=True):
                entered.set()
                await release.wait()
                assert llm_tracing.gateway_metadata('memoir-memory-context')['trace_name']=='memoir-background-agent'
        task=asyncio.create_task(background())
        try:
            await entered.wait()
            with llm_tracing.trace_llm_call('memoir-interviewer','synthetic',gateway=True):
                assert llm_tracing.gateway_metadata('memoir-interviewer')['trace_name']=='memoir-interviewer'
        finally:
            release.set()
            await task
    asyncio.run(run())


def test_speech_calls_are_traced_without_recording_audio_or_text(monkeypatch):
    client = FakeLangfuse()
    monkeypatch.setattr(llm_tracing, "_client_cache", client)

    def provider(request):
        if request.url.path.endswith("transcriptions"):
            return httpx.Response(200, json={"text": "A private answer.", "language": "en"})
        return httpx.Response(200, content=b"audio")

    http_client = httpx.Client(
        base_url="https://speech.test/v1",
        transport=httpx.MockTransport(provider),
    )
    speech = OpenAISpeechService("test-key", client=http_client)
    speech.transcribe(b"private audio", filename="answer.webm", mime_type="audio/webm")
    speech.synthesize("private answer")

    assert [observation.fields["name"] for observation in client.observations] == [
        "speech.transcription",
        "speech.synthesis",
    ]
    assert client.observations[0].fields["input"] == {
        "kind": "audio",
        "bytes": len(b"private audio"),
        "mime_type": "audio/webm",
    }
    assert client.observations[1].fields["input"] == {"kind": "text", "characters": len("private answer")}
    assert all("private" not in json.dumps(observation.fields,default=lambda p: {'name':p.name,'version':p.version}) for observation in client.observations)
    http_client.close()


@pytest.mark.parametrize('provider', ['gemini', 'doubao'])
def test_native_speech_tracing_keeps_text_audio_and_credentials_out_of_observations(monkeypatch, provider):
    tracer = FakeLangfuse()
    monkeypatch.setattr(llm_tracing, '_client_cache', tracer)
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as audio:
        audio.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
        audio.writeframes(b'private audio bytes\x00')
    encoded = base64.b64encode(buffer.getvalue()).decode()

    def upstream(request):
        if provider == 'gemini':
            return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'inlineData': {
                'mimeType': 'audio/wav', 'data': encoded,
            }}]}}]})
        return httpx.Response(200, text=json.dumps({'code': 0, 'data': encoded}))

    client = httpx.Client(base_url='https://speech.test', transport=httpx.MockTransport(upstream))
    service = GeminiSpeechService('private-api-key', client=client) if provider == 'gemini' else DoubaoSpeechService('private-api-key', client=client)
    service.synthesize('Private narrated memory.', language='en-AU' if provider == 'gemini' else 'zh-CN')
    assert len(tracer.observations) == 1
    observation = tracer.observations[0]
    assert observation.fields['metadata']['provider'] == provider
    assert observation.fields['metadata']['prompt_manifest']['artifacts']
    serialized = json.dumps([observation.fields, observation.updates],
                            default=lambda prompt: {'name': prompt.name, 'version': prompt.version})
    assert 'Private narrated memory.' not in serialized
    assert 'private-api-key' not in serialized
    assert encoded not in serialized
    assert observation.closed
