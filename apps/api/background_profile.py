"""Bounded narrator-profile proposals; application code owns admission and writes."""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PROFILE_FIELDS = ('name', 'birth_year', 'birth_date_expression', 'birth_place', 'childhood_place', 'avatar_style')
TEXT_LIMITS = {'name': 120, 'birth_date_expression': 120, 'birth_place': 160, 'childhood_place': 160}
RETRY_CODES = frozenset({'PROFILE_EVIDENCE', 'PROFILE_TARGET', 'OUTPUT_SCHEMA'})


class ProfileRef(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source_id: str = Field(min_length=1, max_length=128)
    version: int = Field(ge=1)
    quote: str = Field(min_length=1, max_length=2304)
    char_start: int | None = Field(ge=0)
    char_end: int | None = Field(ge=1)


class ProfileChange(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    field: Literal['name', 'birth_year', 'birth_date_expression', 'birth_place', 'childhood_place', 'avatar_style']
    value: str | int
    source_refs: list[ProfileRef] = Field(min_length=1, max_length=4)


class ProfileProposal(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    profile_patch: list[ProfileChange] = Field(max_length=6)


def profile_packet(page):
    page = page.model_dump(mode='json') if hasattr(page, 'model_dump') else page
    state = page.get('profile_context')
    source = page.get('source')
    if (not isinstance(state, dict) or state.get('work_mode') != 'extract'
            or type(state.get('revision')) is not int or state['revision'] < 0
            or type(state.get('target_round')) is not int or state['target_round'] < 1
            or not isinstance(state.get('targets'), list) or not state['targets']
            or len(set(state['targets'])) != len(state['targets'])
            or not set(state['targets']) <= set(PROFILE_FIELDS)
            or not isinstance(state.get('reference'), dict)
            or len(json.dumps(state, ensure_ascii=False).encode()) > 16384):
        raise ValueError('Invalid canonical profile targets')
    if (not isinstance(source, dict) or source.get('project_id') != page['project_id']
            or source.get('status') != 'active' or source.get('kind') not in {'narrator_chat', 'narrator_transcript'}
            or not isinstance(source.get('text'), str) or not 0 < len(source['text']) <= 2304
            or type(source.get('char_start')) is not int or source['char_start'] < 0
            or source.get('char_end') != source['char_start'] + len(source['text'])
            or type(source.get('original_length')) is not int
            or not source['char_end'] <= source['original_length'] <= 100000):
        raise ValueError('Invalid bounded profile evidence')
    return {'schema_version': 1, 'source': deepcopy(source), 'profile_context': deepcopy(state)}


def profile_contract(page):
    packet = profile_packet(page)
    schema = ProfileProposal.model_json_schema()
    schema['$defs']['ProfileChange']['properties']['field']['enum'] = packet['profile_context']['targets']
    ref = schema['$defs']['ProfileRef']['properties']
    ref['source_id']['enum'] = [packet['source']['id']]
    ref['version']['enum'] = [packet['source']['version']]
    from .prompt_artifact import load_prompt_artifact
    instructions = load_prompt_artifact(Path(__file__).resolve().parents[2] / 'skills/memoir-memory-context/SKILL.md')
    return instructions, schema


def validate_profile(raw, page):
    packet = profile_packet(page)
    source, state = packet['source'], packet['profile_context']
    result = ProfileProposal.model_validate(raw).model_dump()
    seen = set()
    for change in result['profile_patch']:
        field, value = change['field'], change['value']
        if field not in state['targets'] or field in seen:
            raise ValueError('Profile field outside current targets')
        seen.add(field)
        if field == 'birth_year':
            valid = type(value) is int and 1800 <= value <= date.today().year
        elif field == 'avatar_style':
            valid = value in ('male', 'female')
        else:
            valid = isinstance(value, str) and bool(value.strip()) and len(value) <= TEXT_LIMITS[field]
        if not valid:
            raise ValueError('Invalid profile value')
        for ref in change['source_refs']:
            if ref['source_id'] != source['id'] or ref['version'] != source['version']:
                raise ValueError('Profile evidence outside current source')
            quote, start, end = ref['quote'], ref['char_start'], ref['char_end']
            if (start is None) != (end is None):
                raise ValueError('Profile evidence requires exact span')
            if not (type(start) is int and type(end) is int and 0 <= start < end <= len(source['text'])
                    and source['text'][start:end] == quote):
                start = source['text'].find(quote)
                if start < 0 or source['text'].find(quote, start + 1) >= 0:
                    raise ValueError('Profile evidence requires exact span')
                end = start + len(quote)
            ref.update(char_start=start + source['char_start'], char_end=end + source['char_start'])
    return result


async def extract_profile(page, worker):
    # Stopped/empty-target and literal reply-only pages never load skill instructions.
    state = page['profile_context']
    if state['work_mode'] == 'skip':
        return {'profile_patch': [], 'skipped': True}
    if state['work_mode'] == 'reply_only':
        return {'profile_patch': []}
    from .lifetime_memory_composer import check_model_packet, lane_model_budget
    from .lifetime_memory_lane_engine import build_bounded_lane_input, send_bounded_lane_request
    packet = profile_packet(page)
    instructions, schema = profile_contract(page)
    check_model_packet(packet, instructions, schema)
    for attempt in range(3):
        bounded = build_bounded_lane_input(page, phase='profile', packet=packet, budget=lane_model_budget())
        response = await send_bounded_lane_request(worker_url=worker.worker_url, worker_secret=worker.worker_secret,
            bounded_lane=bounded, worker_transport=worker.worker_transport,
            publisher=getattr(worker, 'lane_publisher', None), timeout=240)
        try:
            return validate_profile(json.loads(response['reply']), page)
        except (ValueError, TypeError, KeyError):
            if attempt == 2:
                raise ValueError('Profile output failed validation') from None
            packet['retry_reason'] = 'OUTPUT_SCHEMA'
