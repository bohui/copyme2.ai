"""Narrow task-publishing contract for the collection and organising agents."""
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .memoir_tasks import BookSection, MemoirTask, MemorySource

TASK_START = '[[MEMORY_SPARK_TASKS]]'
TASK_END = '[[/MEMORY_SPARK_TASKS]]'


class TaskRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['BuildFreePreview', 'BuildSourceExport']
    memory_ids: list[str] = Field(min_length=1, max_length=1000)
    title: str = Field(default='Collected memories', min_length=1, max_length=200)


class BookStructure(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1, max_length=200)
    sections: list[BookSection] = Field(min_length=1, max_length=100)


def extract_task_requests(reply):
    """Strip all control markers and fail closed on malformed task requests."""
    requests = []
    pattern = re.escape(TASK_START) + r'(.*?)' + re.escape(TASK_END)

    def parse(match):
        try:
            raw = json.loads(match[1]) if len(match[1]) <= 20000 else None
            if not isinstance(raw, list) or len(raw) > 4:
                return ''
            validated = [TaskRequest.model_validate(item) for item in raw]
            requests.extend(validated)
        except (ValueError, TypeError):
            pass
        return ''

    visible = re.sub(pattern, parse, reply, flags=re.DOTALL)
    visible = visible.split(TASK_START, 1)[0].strip()
    return visible, requests[:4]


def resolve_task(request: TaskRequest, sources: list[MemorySource]):
    by_id = {source.id: source for source in sources}
    if not set(request.memory_ids).issubset(by_id):
        raise ValueError('Task requested an unavailable memory')
    return MemoirTask(kind=request.kind, title=request.title,
                      sources=[by_id[key] for key in request.memory_ids])
