"""Review only pending original narration before admitting private-context work."""
import asyncio
import os
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .lifetime_memory_publication import ProviderPublication, GovernedRequestBody
from .lifetime_memory_policy import PolicyUnavailable
from .model_request import complete_json


class PolicyReviewPublication(ProviderPublication):
    lock_function = 'lock_lifetime_policy_review'


class Restriction(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    kind: Literal['excluded_topic', 'paused_topic']
    quote: str = Field(min_length=1, max_length=500)
    char_start: int = Field(ge=0)
    char_end: int = Field(ge=1)


class PolicyReview(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    complete: bool
    restrictions: list[Restriction] = Field(max_length=8)


class PolicyReviewOpening(PolicyReview):
    acknowledgement: str | None = Field(default=None, min_length=1, max_length=500, pattern='^[^?？]*$')


def early_ack_enabled():
    return os.getenv('MEMORY_SPARK_EARLY_POLICY_ACK', '').lower() in {'1', 'true', 'yes'}


def reviewed_acknowledgement(value, source, language):
    if not early_ack_enabled() or not isinstance(value, dict):
        return None
    if (type(value.get('source_version')) is not int or value.get('source_id') != source['id']
            or value.get('source_version') != source['version']
            or value.get('language') != language):
        return None
    text = value.get('text')
    if not isinstance(text, str) or not text.strip() or len(text) > 500 or '?' in text or '？' in text:
        return None
    return text.strip()


def validate_review(output, source):
    value = PolicyReview.model_validate(output)
    if not value.complete:
        raise PolicyUnavailable()
    for item in value.restrictions:
        if item.char_end > len(source['text']) or source['text'][item.char_start:item.char_end] != item.quote:
            raise ValueError('Policy review requires exact original spans')
    if len({(item.kind, item.char_start, item.char_end) for item in value.restrictions}) != len(value.restrictions):
        raise ValueError('Duplicate policy review control')
    return value.model_dump()


async def _review_pending_policy(storage, lease, conversation_id, *, model=None, base_url=None, api_key=None,
                                 language=None, fallback_language='en-AU', include_decision=False):
    """An unavailable review leaves durable pending state and all other work closed."""
    from psycopg import AsyncConnection
    from psycopg.types.json import Jsonb
    from .lifetime_memory_reads import _settle

    fence = await lease.io(storage.lifetime_rpc, 'capture_lifetime_fence',
                           p_conversation_id=conversation_id, p_lease_token=lease.lease_token)
    source = await lease.io(storage.lifetime_rpc, 'read_lifetime_policy_review', p_fence=fence)
    if source is None:
        return
    publisher = PolicyReviewPublication(os.getenv('MEMOIR_PUBLICATION_DATABASE_URL'), authenticated_owner=storage.user_id)
    saved_language = source.pop('interview_language', None)
    selected_language = language or saved_language or fallback_language
    if selected_language not in {'en-AU', 'zh-CN'}:
        selected_language = 'en-AU'
    opening = early_ack_enabled()
    schema = (PolicyReviewOpening if opening else PolicyReview).model_json_schema()
    schema['required'] = list(schema['properties'])
    for field in schema['properties'].values():
        field.pop('default', None)
    payload = {'source': source}
    if opening:
        payload.update(acknowledgement_requested=True, interview_language=selected_language)
    prompt = 'memoir/skills/memoir-interviewer/policy-review' + ('-opening' if opening else '')
    output, receipt = await complete_json(prompt,
        payload, schema,
        model=model or os.getenv('MEMORY_SPARK_COLLECTOR_MODEL') or os.getenv('MEMORY_SPARK_LLM_MODEL'),
        base_url=base_url, api_key=api_key,
        trace_name='memoir-interviewer',
        body_factory=lambda content: GovernedRequestBody(content, publisher=publisher, fence=fence))
    acknowledgement = None
    if opening:
        parsed = PolicyReviewOpening.model_validate(output)
        acknowledgement = parsed.acknowledgement.strip() if parsed.acknowledgement else None
        output = parsed.model_dump(exclude={'acknowledgement'})
    output = validate_review(output, source)
    if acknowledgement:
        receipt = {**receipt, 'acknowledgement': acknowledgement,
                   'acknowledgement_language': selected_language}
    connection = await AsyncConnection.connect(os.environ['MEMOIR_PUBLICATION_DATABASE_URL'], connect_timeout=2)
    try:
        async with connection.transaction():
            await connection.execute('set local role service_role')
            await connection.execute("set local lock_timeout='5s'")
            await connection.execute('select public.complete_lifetime_policy_review(%s,%s,%s,%s,%s)',
                (Jsonb(fence), source['id'], source['version'], Jsonb(output), Jsonb(receipt)))
    finally:
        await _settle(asyncio.create_task(connection.close()))
    opening = (dict(source_id=source['id'], source_version=source['version'],
                    language=selected_language, text=acknowledgement) if acknowledgement else None)
    if include_decision:
        return dict(source_id=source['id'], source_version=source['version'],
                    restricted=bool(output['restrictions']), acknowledgement=opening)
    return opening


async def review_pending_policy(storage, lease, conversation_id, *, model=None, base_url=None, api_key=None,
                                language=None, fallback_language='en-AU', include_decision=False):
    import httpx
    import psycopg
    try:
        return await _review_pending_policy(storage, lease, conversation_id,
            model=model, base_url=base_url, api_key=api_key, language=language, fallback_language=fallback_language,
            include_decision=include_decision)
    except (ValueError, KeyError, TypeError, OSError, httpx.HTTPError, psycopg.Error) as error:
        raise PolicyUnavailable() from error
