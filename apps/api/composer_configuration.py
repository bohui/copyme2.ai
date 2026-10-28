"""Composer-only selection; shared extraction and other skills retain their policy."""
from dataclasses import dataclass
import os
from collections.abc import Mapping

REVIEWED_COMPOSER_MODELS = frozenset({'gpt-6.1-sol', 'gpt-5.6-sol', 'gpt-5.6-luna-pooled',
    'legal2ai-luna-low', 'memoir-luna-low', 'synthetic-byte-bpe'})


class ComposerConfigurationError(ValueError):
    """Operator configuration cannot select a substitute or invalid effort."""


@dataclass(frozen=True)
class ComposerConfiguration:
    model: str
    effort: str


def composer_configuration(environment: Mapping | None = None) -> ComposerConfiguration:
    environment = os.environ if environment is None else environment
    model = environment.get('MEMOIR_COMPOSER_MODEL', 'gpt-6.1-sol')
    effort = environment.get('MEMOIR_COMPOSER_REASONING_EFFORT', 'low')
    if not isinstance(model, str) or not isinstance(effort, str):
        raise ComposerConfigurationError('Invalid composer configuration')
    selection = ComposerConfiguration(model.strip(), effort.strip())
    if selection.model not in REVIEWED_COMPOSER_MODELS:
        raise ComposerConfigurationError('Invalid composer model configuration')
    if selection.effort not in {'low', 'medium', 'high'}:
        raise ComposerConfigurationError('Invalid composer reasoning effort configuration')
    return selection
