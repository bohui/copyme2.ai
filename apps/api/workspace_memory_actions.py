"""Scoped workspace intent, separate from narrator testimony and saved pace."""
from typing import Literal

import httpx
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .stage_readiness import LIFE_STAGES


class WorkspaceMemoryFocus(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['add_memory', 'explore_memory']
    life_stage: str | None = None
    event_id: str | None = Field(default=None, min_length=1, max_length=128)
    event_revision: int | None = Field(default=None, ge=1, strict=True)

    @model_validator(mode='after')
    def scoped(self):
        if self.kind == 'add_memory':
            if self.life_stage not in (*LIFE_STAGES, 'unplaced') or self.event_id or self.event_revision:
                raise ValueError('Choose a life stage for a new memory')
        elif self.life_stage is not None or self.event_id is None or self.event_revision is None:
            raise ValueError('Choose an existing memory and its revision')
        return self


def read_workspace_focus(storage, project_id, focus):
    if focus is None:
        return None
    if not project_id:
        raise HTTPException(422, 'Workspace actions require a project')
    value = WorkspaceMemoryFocus.model_validate(focus).model_dump(mode='json', exclude_none=True)
    try:
        return storage.lifetime_rpc('read_workspace_memory_focus', p_project_id=project_id, p_focus=value)
    except httpx.HTTPStatusError:
        raise HTTPException(409, 'This memory changed or is unavailable. Choose it again.',
            headers={'X-Error-Code': 'WORKSPACE_MEMORY_FOCUS_STALE'}) from None


def apply_workspace_focus(context, focus):
    if not focus:
        return
    context['workspace_focus'] = {key: value for key, value in focus.items() if key != 'event'}
    if focus.get('event'):
        event = focus['event']
        context['events'] = [event, *[item for item in context.get('events', []) if item['id'] != event['id']]][:8]
