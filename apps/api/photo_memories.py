"""User-selected reference photos, kept separately from narrated memories."""
from copy import deepcopy
from typing import Literal
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException
from pydantic import BaseModel, Field, model_validator

PHOTO_MEMORIES = 'photo_memories'


class PhotoReference(BaseModel):
    image_url: str = Field(min_length=1, max_length=4096)
    original_url: str = Field(default='', max_length=4096)
    source_url: str = Field(default='', max_length=4096)
    asset_id: str = Field(default='', max_length=256)
    title: str = Field(default='', max_length=1000)
    attribution: str = Field(default='', max_length=1000)
    date_expression: str = Field(default='', max_length=160)
    place: str = Field(default='', max_length=160)
    period: str = Field(default='', max_length=160)

    @model_validator(mode='after')
    def safe_urls(self):
        for value in (self.image_url, self.original_url, self.source_url):
            if not value:
                continue
            parsed = urlsplit(value)
            if not (parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.password
                    or value.startswith('/static/') and not parsed.netloc and not parsed.scheme
                    and '..' not in unquote(parsed.path).replace('\\', '/').split('/')):
                raise ValueError('Use a public HTTPS photo reference')
        return self

    def reference(self):
        value = self.model_dump()
        value['key'] = self.original_url or self.image_url
        return value


class PhotoMemoryInput(BaseModel):
    action: Literal['select', 'favorite', 'unfavorite', 'clear']
    photo: PhotoReference | None = None

    @model_validator(mode='after')
    def needs_photo(self):
        if self.action != 'clear' and self.photo is None:
            raise ValueError('A photo is required')
        return self


def photo_memory_state(profile, project_id):
    return deepcopy((profile.get(PHOTO_MEMORIES) or {}).get(project_id)
                    or {'favorites': [], 'selected': None})


def update_photo_memory(profile, project_id, payload):
    state = photo_memory_state(profile, project_id)
    if payload.action == 'clear':
        state['selected'] = None
    else:
        photo = payload.photo.reference()
        favorites = [item for item in state['favorites'] if item['key'] != photo['key']]
        if payload.action in ('select', 'favorite'):
            if len(favorites) >= 200:
                raise HTTPException(422, 'This interview already has 200 favourite photos')
            favorites.append(photo)
        state['favorites'] = favorites
        if payload.action == 'select':
            state['selected'] = photo['key']
        elif payload.action == 'unfavorite' and state['selected'] == photo['key']:
            state['selected'] = None
    updated = {**profile, PHOTO_MEMORIES: {**(profile.get(PHOTO_MEMORIES) or {}), project_id: state}}
    return updated, state


def selected_photo(profile, project_id):
    if not project_id:
        return None
    state = photo_memory_state(profile or {}, project_id)
    return next((item for item in state['favorites'] if item['key'] == state['selected']), None)
