"""Keep the original acceptance suite on its explicit legacy contract.

The running prototype defaults to the chapter entitlement model. The existing
specification tests exercise the retired five-session trial because they also
cover preview, grant, expiry and refund behavior. New chapter-model tests opt
in explicitly so both migrations remain covered while the product changes.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")

import httpx
import pytest

from apps.api import prompt_artifact
from scripts.prompt_registry import prompt_registry, ROOT

# Use the same fixtures that ship in an isolated photo-skill installation.
sys.path.insert(0, str(ROOT / 'skills/memoir-place-photo-research/tests'))

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
    from photo_test_support.offline_network import deny_external_network
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
    from controlled_policy import install_policy_review_transport
    install_policy_review_transport(monkeypatch, fixed_policy_controls)
