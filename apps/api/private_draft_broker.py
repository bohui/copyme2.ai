"""Trusted job-scoped outbox broker; credentials never leave the API."""
import asyncio
import os
import httpx
from .memoir_preview import source_snapshot
from .private_draft_jobs import PrivateDraftJobs
from .recall import free_recall_rounds,private_draft_cadence
from .codex_runtime import normalize_conversation_language


class PrivateDraftBroker:
    def __init__(self, *, client=None):
        self.url=os.environ['SUPABASE_URL'].rstrip('/')
        self.key=os.environ['SUPABASE_SECRET_KEY']
        self.client=client or httpx.AsyncClient(timeout=15)

    async def request(self,method,path,**kwargs):
        result=await self.client.request(method,self.url+'/rest/v1/'+path,
            headers={'apikey':self.key,'Authorization':'Bearer '+self.key},**kwargs)
        result.raise_for_status()
        return result

    async def snapshot(self,event_id):
        result=await self.request('POST','rpc/private_draft_event_snapshot',json={'p_event_id':event_id})
        return result.json()

    @staticmethod
    def reconcile(snapshot):
        from .private_drafts import enabled
        queue=PrivateDraftJobs(os.environ['MEMORY_SPARK_TASK_DB'])
        queue.invalidate_other_locales(snapshot['user_id'],snapshot['project_id'],normalize_conversation_language(snapshot['locale']))
        return queue.synchronize(snapshot['user_id'],snapshot['project_id'],normalize_conversation_language(snapshot['locale']),
            snapshot['rounds'],source_snapshot(snapshot['memories'],snapshot['project_id']),completed=snapshot['completed'],
            free_limit=free_recall_rounds(),cadence=private_draft_cadence(),enabled=enabled(),authorization_event_id=snapshot['event_id'])

    async def drain_once(self):
        result=await self.request('GET','user_private_draft_outbox',params={
            'select':'id','delivered':'eq.false','order':'created_at.asc,id.asc','limit':'50'})
        for event in result.json():
            snapshot=await self.snapshot(event['id'])
            if snapshot:
                await asyncio.to_thread(self.reconcile,snapshot)
            # Acknowledgement follows the durable local transaction. A crash
            # before acknowledgement safely replays the same manifest.
            await self.request('PATCH','user_private_draft_outbox',params={'id':f'eq.{event["id"]}'},json={'delivered':True})

    async def run(self):
        while True:
            try:
                await self.drain_once()
            except (httpx.HTTPError,OSError,ValueError,KeyError):
                # Durable events remain pending; never log content or secrets.
                pass
            await asyncio.sleep(5)
