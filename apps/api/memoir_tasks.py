"""Validated, deterministic tasks shared by agent publishers and workers.

These handlers assemble supplied, authorised memory snapshots. They never call
a model or treat generated chapter headings as new biographical evidence.
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MemorySource(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1, max_length=128)
    content: str = Field(max_length=100000)


class BookSection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    memory_ids: list[str] = Field(min_length=1, max_length=1000)


class MemoirTask(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['BuildFreePreview', 'BuildOutline', 'BuildChapter', 'BuildSourceExport']
    sources: list[MemorySource] = Field(min_length=1, max_length=1000)
    title: str = Field(default='A life remembered', min_length=1, max_length=200)
    sections: list[BookSection] = Field(default_factory=list, max_length=100)

    @model_validator(mode='after')
    def validate_sources(self):
        ids = [source.id for source in self.sources]
        if len(set(ids)) != len(ids):
            raise ValueError('Duplicate memory source ids')
        if sum(len(source.content) for source in self.sources) > 2_000_000:
            raise ValueError('Memory snapshot exceeds task size limit')
        for section in self.sections:
            if not set(section.memory_ids).issubset(ids):
                raise ValueError('Book section references an unknown memory')
            if len(set(section.memory_ids)) != len(section.memory_ids):
                raise ValueError('Duplicate memories within a book section')
        if self.kind == 'BuildOutline' and not self.sections:
            raise ValueError('BuildOutline requires an organising-agent or user supplied structure')
        return self


class PublishTaskInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    user_id: UUID
    project_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]*$')
    task: MemoirTask


def execute_task(task: MemoirTask) -> dict:
    """Return a repeatable artifact; persistence and retries belong to the queue."""
    sources = [source.model_dump() for source in task.sources]
    common = {'schema_version': 1, 'kind': task.kind, 'title': task.title,
              'source_memory_ids': [source.id for source in task.sources]}
    if task.kind == 'BuildSourceExport':
        return {**common, 'sources': sources}
    if task.kind == 'BuildOutline':
        return {**common, 'sections': [section.model_dump() for section in task.sections]}
    # Preserve the storyteller's exact words. Prose rewriting is the organising
    # agent's responsibility and must remain separately reviewable.
    return {**common, 'blocks': [
        {'type': 'narrative', 'text': source.content, 'source_memory_ids': [source.id]}
        for source in task.sources
    ]}
