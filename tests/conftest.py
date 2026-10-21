"""Keep the original acceptance suite on its explicit legacy contract.

The running prototype defaults to the chapter entitlement model. The existing
specification tests exercise the retired five-session trial because they also
cover preview, grant, expiry and refund behavior. New chapter-model tests opt
in explicitly so both migrations remain covered while the product changes.
"""

import os
from pathlib import Path

os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")

import httpx
import pytest

from apps.api import prompt_artifact
from scripts.prompt_registry import prompt_registry, ROOT


# Offline application replays test reviewed source text, including unpublished
# PR edits. The production loader and publication tests still validate receipts.
_published_prompt = prompt_artifact.load_prompt_artifact
_source_paths = {ROOT / relative for relative in prompt_registry(include_unpublished=True).values()}


def _offline_prompt_source(path):
    path = Path(path)
    return path.read_text(encoding='utf-8') if path in _source_paths else _published_prompt(path)


prompt_artifact.load_prompt_artifact = _offline_prompt_source


@pytest.fixture(autouse=True)
def deny_external_provider_dispatch(monkeypatch):
    """Only in-process transports and loopback services belong in ordinary tests."""
    import socket
    from offline_network import deny_external_network
    original, resolver = deny_external_network()
    connect, resolve = socket.socket.connect, socket.getaddrinfo
    socket.socket.connect, socket.getaddrinfo = original, resolver
    monkeypatch.setattr(socket.socket,'connect',connect)
    monkeypatch.setattr(socket,'getaddrinfo',resolve)


os.environ.setdefault("MEMORY_SPARK_ENTITLEMENT_MODEL", "legacy")
os.environ.setdefault("MEMORY_SPARK_TEST_MODE", "1")

# Original worker acceptance fixtures deliberately represent pre-migration-only
# deployments. Security/adoption tests explicitly remove this assertion.
os.environ.setdefault("MEMOIR_LEGACY_ONLY_DEPLOYMENT", "1")


@pytest.fixture
def fixed_policy_controls():
    """Explicit (kind, exact quote) model fixture; no natural-language classifier."""
    return []


@pytest.fixture(autouse=True)
def controlled_policy_review_transport(monkeypatch, fixed_policy_controls):
    from apps.api import policy_review
    original = policy_review.complete_json

    async def complete(name, payload, schema, **kwargs):
        source = payload['source']
        controls = []
        for kind, quote in fixed_policy_controls:
            start = source['text'].index(quote)
            controls.append(dict(kind=kind, quote=quote, char_start=start, char_end=start + len(quote)))
        output = dict(complete=True, restrictions=controls)
        def respond(request):
            return httpx.Response(200, json=dict(id='controlled-policy-response', status='completed',
                output=[dict(type='message', status='completed', content=[dict(type='output_text', text=__import__('json').dumps(output))])]))
        kwargs['model']=kwargs.get('model') or 'controlled-policy-model'
        return await original(name, payload, schema, transport=httpx.MockTransport(respond),
            base_url='https://policy.invalid/v1',api_key='controlled-policy-key',**kwargs)

    monkeypatch.setattr(policy_review, 'complete_json', complete)


@pytest.fixture(autouse=True)
def fixed_caption_interpretation(monkeypatch):
    """Neutral caption proposal; tests of date roles supply explicit assertions."""
    from apps.api.place_photo_browser import _research
    from fixed_caption_data import proposal
    monkeypatch.setattr(_research(), '_caption_date_proposal', proposal)
