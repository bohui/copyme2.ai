"""Provider-free formal draft assembly from a database-frozen evidence plan.

This version orders exact narrator passages under neutral chapter headings. It
does not synthesize prose or infer facts. PostgreSQL independently reconstructs
and validates the complete staged chapter, then commits the edition and receipt.
"""
import asyncio
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class FormalQuoteBlock(BaseModel):
    model_config = {'extra': 'forbid'}
    text: str = Field(min_length=1, max_length=2000)
    source_id: UUID
    version: int = Field(ge=1, strict=True)
    char_start: int = Field(ge=0, strict=True)
    char_end: int = Field(ge=1, strict=True)

    @model_validator(mode='after')
    def exact_span(self):
        if self.char_end - self.char_start != len(self.text):
            raise ValueError('Formal evidence span differs from its text')
        return self


class FormalChapter(BaseModel):
    model_config = {'extra': 'forbid'}
    schema_version: Literal[1] = 1
    chapter_id: UUID
    title: str = Field(min_length=1, max_length=80)
    blocks: list[FormalQuoteBlock] = Field(min_length=1, max_length=8)


async def advance_formal_memoir(broker, run_id, *, quantum=8):
    """Advance at most eight chapters; authority and replay live in PostgreSQL.

    The caller is a trusted worker. No owner, source inventory, completion flag,
    prose or consent can be provided by the caller. Every read/stage is fenced.
    """
    run_id = str(UUID(str(run_id)))
    if type(quantum) is not int or not 1 <= quantum <= 8:
        raise ValueError('Formal work quantum must be between one and eight')
    job = await broker.rpc('claim_formal_memoir', p_run_id=run_id, p_lease_seconds=300)
    if job.get('status') in {'completed', 'busy'}:
        return job
    token = str(UUID(job['token']))
    completed = False
    try:
        async with asyncio.timeout(60):
            start, count = job['next_ordinal'], job['chapter_count']
            if type(start) is not int or type(count) is not int or not 1 <= start <= count + 1:
                raise ValueError('Invalid formal chapter cursor')
            stop = min(count + 1, start + quantum)
            for ordinal in range(start, stop):
                page = await broker.rpc('read_formal_memoir_chapter',
                    p_run_id=run_id, p_token=token, p_ordinal=ordinal)
                chapter = FormalChapter(chapter_id=page['chapter_id'], title=page['title'], blocks=[
                    FormalQuoteBlock(text=ref['quote'], source_id=ref['source_id'], version=ref['version'],
                                     char_start=ref['char_start'], char_end=ref['char_end'])
                    for ref in page['evidence']])
                await broker.rpc('stage_formal_memoir_chapter', p_run_id=run_id, p_token=token,
                    p_ordinal=ordinal, p_chapter=chapter.model_dump(mode='json'), p_validation={
                        'schema_version': 1, 'validator': 'formal-extractive-v1',
                        'chapter_plan_digest': page['chapter_plan_digest'],
                        'provenance': 'deterministic-extractive', 'blocking_count': 0})
            if stop == count + 1:
                result = await broker.rpc('complete_formal_memoir', p_run_id=run_id, p_token=token)
                completed = result.get('status') == 'completed'
                if not completed:
                    raise ValueError('Formal completion was not committed')
                return result
    except BaseException:
        if not completed:
            # Release preserves validated stages but revokes this token. Failed
            # release is safe: the bounded lease expires and commit rechecks it.
            try:
                await broker.rpc('release_formal_memoir', p_run_id=run_id, p_token=token)
            except (Exception, asyncio.CancelledError):
                pass
        raise
    # Successful yielding also needs current authority. Do not report pending
    # from local arithmetic if a concurrent correction rejected the release.
    return await broker.rpc('release_formal_memoir', p_run_id=run_id, p_token=token)
