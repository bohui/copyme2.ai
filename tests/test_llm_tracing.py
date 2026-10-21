from __future__ import annotations

import json

import httpx
import pytest

from apps.api import llm_tracing
from apps.api.speech import OpenAISpeechService


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
