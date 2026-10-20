"""Selective derived context on canonical compaction; originals remain retrievable."""
from __future__ import annotations
from copy import deepcopy
import json
from pathlib import Path
from typing import Literal
from uuid import UUID
from pydantic import BaseModel,ConfigDict,Field,ValidationError,model_validator
from .lifetime_memory_contracts import Contract
from .prompt_artifact import load_prompt_artifact, prompt_path

MAX_SUMMARY_BYTES=8192
SUMMARY_RETRY_CODES=frozenset({'SUMMARY_EVIDENCE','SUMMARY_BUDGET','OUTPUT_SCHEMA'})


def summary_rejection_reason(error):
    if isinstance(error,ValidationError):
        if any(str((detail.get('ctx') or {}).get('error',''))=='Derived summary exceeds the byte budget'
               for detail in error.errors(include_input=False,include_url=False)):
            return 'SUMMARY_BUDGET'
        return 'OUTPUT_SCHEMA'
    return {'Summary cites unseen or ambiguous original evidence':'SUMMARY_EVIDENCE',
            'Derived summary exceeds the byte budget':'SUMMARY_BUDGET'}.get(str(error),'OUTPUT_SCHEMA')


class SummaryRef(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    source_id:str=Field(min_length=1,max_length=128)
    version:int=Field(ge=1)
    quote:str=Field(min_length=1,max_length=500)
    char_start:int|None=Field(ge=0)
    char_end:int|None=Field(ge=1)


class SummaryItem(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    text:str=Field(min_length=1,max_length=500)
    uncertainty:str=Field(min_length=1,max_length=500)
    source_refs:list[SummaryRef]=Field(min_length=1,max_length=4)


class SummaryProposal(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    items:list[SummaryItem]=Field(max_length=16)

    @model_validator(mode='after')
    def bounded_bytes(self):
        if len(json.dumps(self.model_dump(),ensure_ascii=False).encode())>MAX_SUMMARY_BYTES:
            raise ValueError('Derived summary exceeds the byte budget')
        return self


class AcceptedMemorySummary(Contract):
    kind:Literal['selective_derived_context']='selective_derived_context'
    maintenance_id:UUID
    coverage_digest:str=Field(pattern=r'^[a-f0-9]{64}$')
    processed_windows:int=Field(ge=1,strict=True)
    processed_through:int=Field(ge=1,strict=True)
    items:list[SummaryItem]=Field(max_length=16)

    @model_validator(mode='after')
    def accepted_refs(self):
        SummaryProposal(items=self.items)
        for item in self.items:
            for ref in item.source_refs:
                if ref.char_start is None or ref.char_end is None or ref.char_end-ref.char_start!=len(ref.quote):
                    raise ValueError('Accepted summary needs exact original spans')
        return self


def summary_contract(page=None):
    schema=SummaryProposal.model_json_schema()
    if page is not None:
        page=page.model_dump(mode='json') if hasattr(page,'model_dump') else page
        source=page.get('source')
        citations=[ref for item in (page.get('memory_summary') or {}).get('prior',{}).get('items',[])
                   for ref in item['source_refs']]
        identities={(ref['source_id'],ref['version']) for ref in citations}
        if source:identities.add((source['id'],source['version']))
        choices=[]
        for source_id,version in sorted(identities):
            ref=deepcopy(schema['$defs']['SummaryRef'])
            ref['properties']['source_id']['enum']=[source_id]
            ref['properties']['version']['enum']=[version]
            choices.append(ref)
        if choices:schema['$defs']['SummaryRef']={'anyOf':choices}
        else:schema['properties']['items']['maxItems']=0
    return load_prompt_artifact(prompt_path('memoir/skills/memoir-memory-context/summary')), schema


def summary_packet(fence):
    state=fence['memory_summary']
    return {'source':deepcopy(fence['source']),'prior':deepcopy(state['prior']),
        'maintenance_id':state['maintenance_id'],'revision':state['revision'],
        'coverage_end':state['through_sequence'],'selective':True,
        'recent_dialogue':deepcopy((fence.get('attribution_context') or {}).get('recent_dialogue', []))}


def validate_summary(raw,page):
    value=SummaryProposal.model_validate(raw).model_dump()
    source=page.get('source');prior=(page.get('memory_summary') or {}).get('prior',{}).get('items',[])
    for item in value['items']:
        for ref in item['source_refs']:
            matches=[]
            windows=[(cite['quote'],cite['char_start']) for old in prior for cite in old['source_refs']
                     if all(ref[k]==cite[k] for k in ('source_id','version'))]
            if source and source['id']==ref['source_id'] and source['version']==ref['version']:
                windows.append((source['text'],source['char_start']))
            for text,offset in windows:
                start=text.find(ref['quote'])
                while start>=0:
                    absolute=offset+start;matches.append((absolute,absolute+len(ref['quote'])))
                    start=text.find(ref['quote'],start+1)
            matches=list(dict.fromkeys(matches))
            positions=(ref['char_start'],ref['char_end'])
            if positions not in matches and len(matches)==1:positions=matches[0]
            if positions not in matches or None in positions:raise ValueError('Summary cites unseen or ambiguous original evidence')
            ref.update(char_start=positions[0],char_end=positions[1])
    return SummaryProposal.model_validate(value).model_dump()
