"""Composer-only selection; shared extraction and other skills retain their policy."""
from dataclasses import dataclass
import os
from collections.abc import Mapping
from .model_configuration import configured_model, configured_effort

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
    try:
        selection = ComposerConfiguration(
            configured_model('MEMOIR_COMPOSER_MODEL', 'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL',
                'MEMORY_SPARK_LLM_MODEL', environment=environment),
            configured_effort('MEMOIR_COMPOSER_REASONING_EFFORT', 'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT',
                'MEMORY_SPARK_LLM_REASONING_EFFORT', environment=environment))
    except ValueError as error:
        raise ComposerConfigurationError('Invalid composer configuration') from error
    if selection.model not in REVIEWED_COMPOSER_MODELS:
        raise ComposerConfigurationError('Invalid composer model configuration')
    if selection.effort not in {'low', 'medium', 'high'}:
        raise ComposerConfigurationError('Invalid composer reasoning effort configuration')
    return selection
