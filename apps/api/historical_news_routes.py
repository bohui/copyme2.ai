"""Owner-scoped historical cue controls; no search on the request path."""
import asyncio
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .agent_routes_support import authenticated_storage
from .interview_photos import _project

router=APIRouter(prefix='/v1/agent/projects',tags=['Historical context'])

class Preference(BaseModel):
    model_config=ConfigDict(extra='forbid')
    enabled:bool | None = None
    reject_id:str|None=Field(default=None,pattern=r'^news-[a-f0-9]{24}$')

@router.put('/{project_id}/historical-news')
async def historical_preference(project_id:str,body:Preference,authorization:str|None=Header(default=None)):
    _project(project_id)
    storage=await asyncio.to_thread(authenticated_storage,authorization)
    try:
        state=await asyncio.to_thread(storage.set_historical_news,project_id,body.enabled,body.reject_id)
        return {'enabled':state['enabled']}
    except Exception:
        raise HTTPException(503,'Historical context preference could not be saved. Please try again.') from None
    finally:await asyncio.to_thread(storage.client.close)
