"""Resolve operator model settings without choosing a model in application code."""
import os


REASONING_EFFORTS = frozenset({'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max'})


def _configured(keys, environment):
    environment = os.environ if environment is None else environment
    for key in keys:
        value = environment.get(key, '')
        if not isinstance(value, str):
            raise ValueError(f'Invalid model setting: {key}')
        if value.strip():
            return value.strip()
    raise ValueError(f'Model setting is not configured: {", ".join(keys)}')


def configured_model(*keys, environment=None):
    value = _configured(keys or ('MEMORY_SPARK_LLM_MODEL',), environment)
    if len(value) > 256 or any(ord(char) < 32 for char in value):
        raise ValueError('Invalid model configuration')
    return value


def configured_effort(*keys, environment=None):
    value = _configured(keys or ('MEMORY_SPARK_LLM_REASONING_EFFORT',), environment)
    if value not in REASONING_EFFORTS:
        raise ValueError('Invalid reasoning effort configuration')
    return value


def background_model(environment=None):
    return configured_model('MEMORY_SPARK_MEMOIR_COMPOSER_MODEL',
        'MEMORY_SPARK_LLM_MODEL', environment=environment)


def background_effort(environment=None):
    return configured_effort('MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT',
        'MEMORY_SPARK_LLM_REASONING_EFFORT', environment=environment)


def game_configuration(environment=None):
    return (configured_model('MEMOIR_GAME_MODEL', 'MEMORY_SPARK_MEMOIR_COMPOSER_MODEL',
                'MEMORY_SPARK_LLM_MODEL', environment=environment),
            configured_effort('MEMOIR_GAME_REASONING_EFFORT', 'MEMORY_SPARK_MEMOIR_COMPOSER_REASONING_EFFORT',
                'MEMORY_SPARK_LLM_REASONING_EFFORT', environment=environment))
