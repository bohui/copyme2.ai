"""Server-owned, reversible policy for future collector generations only.

A route name/requested effort is not proof of the provider's effective policy.
No credentials, provider settings, persisted history or shared defaults change.
"""
from dataclasses import dataclass
import os


class CollectorConfigurationError(ValueError):
    """Invalid operator policy, distinct from an invalid storyteller request."""


@dataclass(frozen=True)
class CollectorConfiguration:
    model: str
    effort: str | None
    prompt_version: str


def collector_configuration(default_model: str) -> CollectorConfiguration:
    # Resolve at generation time, never when a session/runtime is constructed.
    model = os.getenv('MEMORY_SPARK_COLLECTOR_MODEL', '').strip() or default_model
    effort = os.getenv('MEMORY_SPARK_COLLECTOR_REASONING_EFFORT', '').strip() or None
    version = os.getenv('MEMORY_SPARK_COLLECTOR_PROMPT_VERSION', '').strip() or 'compact-v1'
    if len(model) > 256 or any(ord(char) < 32 for char in model):
        raise CollectorConfigurationError('Invalid collector model configuration')
    if effort not in {None, 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'}:
        raise CollectorConfigurationError('Invalid collector reasoning effort configuration')
    if version not in {'compact-v1', 'two-lane-v1', 'reply-v2'}:
        raise CollectorConfigurationError('Invalid collector prompt version configuration')
    if version == 'reply-v2' and effort == 'low' and model == 'gpt-5.6-luna-pooled':
        # The pooled key enforces max; this existing same-model route has a low-policy key.
        model = 'gpt-5.6-luna-memoir-low'
    return CollectorConfiguration(model, effort, version)
