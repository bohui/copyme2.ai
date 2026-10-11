"""Server-owned, reversible policy for future collector generations only.

A route name/requested effort is not proof of the provider's effective policy.
No credentials, provider settings, persisted history or shared defaults change.
"""
from dataclasses import dataclass
import os


@dataclass(frozen=True)
class CollectorConfiguration:
    model: str
    effort: str | None
    prompt_version: str


def collector_configuration(legacy_model: str) -> CollectorConfiguration:
    # Resolve at generation time, never when a session/runtime is constructed.
    model = os.getenv('MEMORY_SPARK_COLLECTOR_MODEL', '').strip() or legacy_model
    effort = os.getenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', '').strip() or None
    version = os.getenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', '').strip() or 'legacy'
    if len(model) > 256 or any(ord(char) < 32 for char in model):
        raise ValueError('Invalid collector model configuration')
    if effort not in {None, 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}:
        raise ValueError('Invalid collector reasoning effort configuration')
    if version not in {'legacy', 'compact-v1'}:
        raise ValueError('Invalid collector prompt version configuration')
    return CollectorConfiguration(model, effort, version)
