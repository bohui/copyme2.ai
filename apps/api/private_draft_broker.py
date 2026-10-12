"""Trusted job-scoped outbox broker; credentials never leave the API."""
import asyncio
import os
import httpx
from .memoir_preview import source_snapshot
from .private_draft_jobs import PrivateDraftJobs
from .recall import free_recall_rounds,private_draft_cadence
from .codex_runtime import normalize_conversation_language


def receipt_scope_conflict(error, *, snapshot=False):
    """Only the database's explicit stale-scope fence discards a checkpoint."""
    try:
        detail=error.response.json()
    except (ValueError,AttributeError):
        return False
    message='stale private draft snapshot' if snapshot else 'private draft receipt scope stale'
    return isinstance(detail,dict) and detail.get('code')=='40001' and detail.get('message')==message


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

    async def snapshot(self,event_id,cursor=None):
        path='rpc/private_draft_event_page' if cursor is not None else 'rpc/private_draft_event_snapshot'
        parameters={'p_event_id':event_id}
        if cursor is not None:
            parameters['p_cursor']=cursor
        result=await self.request('POST',path,json=parameters)
        return result.json()

    @staticmethod
    def reconcile(snapshot):
        from .private_drafts import enabled
        queue=PrivateDraftJobs(os.environ['MEMORY_SPARK_TASK_DB'])
        if snapshot.get('protocol') == 'lifetime_draft_pages':
            return queue.synchronize_page(snapshot,free_limit=free_recall_rounds(),
                cadence=private_draft_cadence(),enabled=enabled())
        queue.invalidate_other_locales(snapshot['user_id'],snapshot['project_id'],normalize_conversation_language(snapshot['locale']))
        return queue.synchronize(snapshot['user_id'],snapshot['project_id'],normalize_conversation_language(snapshot['locale']),
            snapshot['rounds'],source_snapshot(snapshot['memories'],snapshot['project_id']),completed=snapshot['completed'],
            free_limit=free_recall_rounds(),cadence=private_draft_cadence(),enabled=enabled(),authorization_event_id=snapshot['event_id'])

    async def acknowledge(self,event_id,queue):
        try:
            await self.request('PATCH','user_private_draft_outbox',params={'id':f'eq.{event_id}'},json={'delivered':True})
        except httpx.HTTPStatusError as error:
            if not receipt_scope_conflict(error):
                raise
            await asyncio.to_thread(queue.restart_page,event_id)
            return False
        return True

    async def drain_once(self):
        result=await self.request('GET','user_private_draft_outbox',params={
            'select':'id','delivered':'eq.false','order':'created_at.asc,id.asc','limit':'50'})
        # A drain is bounded by both receipt count and total source pages.
        # Remaining receipts retain delivered=false and durable next cursors.
        pages_left=8
        queue=PrivateDraftJobs(os.environ['MEMORY_SPARK_TASK_DB'])
        for event in result.json():
            if pages_left<=0:
                break
            resume=await asyncio.to_thread(queue.page_resume,event['id'])
            if resume and resume['complete']:
                if not await self.acknowledge(event['id'],queue):
                    return
                continue
            try:
                snapshot=await self.snapshot(event['id'],resume['next_cursor'] if resume else None)
            except httpx.HTTPStatusError as error:
                if not resume or not (error.response.status_code in {400,409} or receipt_scope_conflict(error,snapshot=True)):
                    raise
                # A revoked epoch invalidates the opaque continuation. Start
                # one freshly authorised receipt, never retry stale content.
                snapshot=await self.snapshot(event['id'])
            while snapshot:
                pages_left-=1
                view=await asyncio.to_thread(self.reconcile,snapshot)
                if snapshot.get('protocol') != 'lifetime_draft_pages' or view['retrieval_complete']:
                    break
                if pages_left<=0:
                    return
                snapshot=await self.snapshot(event['id'],view['next_cursor'])
            # Only the complete, durable receipt permits acknowledgement.
            # Draft composition remains a distinct pending/approved operation.
            if not await self.acknowledge(event['id'],queue):
                return

    async def run(self):
        while True:
            try:
                await self.drain_once()
            except (httpx.HTTPError,OSError,ValueError,KeyError):
                # Durable events remain pending; never log content or secrets.
                pass
            await asyncio.sleep(5)
