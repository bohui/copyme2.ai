"""Authenticated Supabase API boundary, separate from prototype demo accounts."""
import os
from typing import Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .agent_routes_support import authenticated_storage
from .conversation_text import original_conversation_text

router = APIRouter(prefix='/v1/user', tags=['Supabase user data'])


storage = authenticated_storage


class MemoryInput(BaseModel):
    content: str = Field(min_length=1, max_length=100000)


class TransferToken(BaseModel):
    token: str = Field(pattern=r'^[a-f0-9]{64}$')


class ConversationMessage(BaseModel):
    role: Literal['user', 'assistant']
    text: str = Field(max_length=100000)


class GuestConversationTransfer(TransferToken):
    project_id: str = Field(min_length=1, max_length=128)
    messages: list[ConversationMessage] = Field(max_length=1000)
    workspace_profile: dict = Field(default_factory=dict)
    ui_locale: Literal['en-AU', 'zh-CN'] | None = None


class WorkspaceMergeToken(TransferToken):
    guest_wins: bool = False


def _queue_if_configured():
    if os.getenv('MEMORY_SPARK_TASK_DB'):
        from .task_queue import configured_queue
        return configured_queue()


def _wait_for_deliveries(service):
    queue = _queue_if_configured()
    if queue and queue.has_pending_user_work(service.user_id):
        raise HTTPException(409, 'Wait for generated workspace results to finish')


def _transfer(service, function, payload):
    try:
        return service.request('POST', f'/rest/v1/rpc/{function}', json=payload).json()
    except httpx.HTTPStatusError as error:
        # Do not expose capability tokens or request bodies in errors.
        try:
            code = error.response.json().get('code')
        except (ValueError, AttributeError):
            code = None
        if code == '55000':
            raise HTTPException(409, 'Wait for the current reply to finish') from None
        if code in {'42501', '22023'}:
            raise HTTPException(409, 'Conversation transfer unavailable or expired') from None
        raise HTTPException(503, 'Conversation transfer storage unavailable') from None
    except httpx.RequestError:
        raise HTTPException(503, 'Conversation transfer storage unavailable') from None


@router.post('/conversation-transfer')
def prepare_conversation_transfer(payload: GuestConversationTransfer,
                                  authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        if not service.is_anonymous:
            raise HTTPException(403, 'Guest session required')
        _wait_for_deliveries(service)
        return _transfer(service, 'prepare_guest_conversation_transfer', {
            'p_token': payload.token, 'p_project_id': payload.project_id,
            'p_messages': [message.model_dump() for message in payload.messages],
            'p_workspace_profile': payload.workspace_profile, 'p_ui_locale': payload.ui_locale,
        })
    finally:
        service.client.close()


@router.post('/conversation-transfer/attach')
def attach_conversation_transfer(payload: WorkspaceMergeToken,
                                 authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        if service.is_anonymous:
            raise HTTPException(403, 'Sign in to a permanent account first')
        _wait_for_deliveries(service)
        result = _transfer(service, 'attach_guest_conversation', {'p_token': payload.token, 'p_guest_wins': payload.guest_wins})
        # Compatibility with already attached transcripts from the first version.
        if result.get('guest_user_id'):
            from .workspace_merge import import_guest_files
            try:
                import_guest_files(service, result['guest_user_id'], result.get('storage_objects', []))
                queue = _queue_if_configured()
                if queue:
                    queue.import_guest_results(result['guest_user_id'], service.user_id,
                                               result['conversation_id'], result.get('memory_id_map', {}))
            except (httpx.HTTPError, ValueError):
                raise HTTPException(503, 'Workspace merge incomplete; retry this transfer') from None
        result.pop('storage_objects', None)
        return result
    finally:
        service.client.close()


@router.get('/conversations')
def conversation_attachments(authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        items = service.request('GET', '/rest/v1/user_conversation_attachment', params={
            'select': 'id,project_id,messages,workspace,created_at',
            'user_id': f'eq.{service.user_id}', 'order': 'created_at.desc', 'limit': '100',
        }).json()
        for item in items:
            for message in item.get('messages', []):
                if message.get('role') == 'user':
                    message['text'] = original_conversation_text(message['text'])
        queue = _queue_if_configured()
        if queue:
            for item in items:
                item.setdefault('workspace', {})['generated_documents'] = queue.list(service.user_id, item['project_id'])
                item['workspace']['collection'] = queue.collection(service.user_id, item['project_id'])
        # Normal OAuth conversations are persisted as agent memories; they
        # never pass through the guest-attachment table. Show both sources.
        imported_ids = {str(memory_id) for item in items
                        for memory_id in (item.get('workspace', {}).get('memory_id_map') or {}).values()}
        messages = []
        created_at = None
        for memory in service.all_memories():
            if memory.get('kind') != 'agent' or str(memory.get('id')) in imported_ids:
                continue
            content = memory.get('content') or ''
            if not content.startswith('Storyteller: '):
                continue
            question, separator, reply = content.removeprefix('Storyteller: ').partition('\nMemory Spark: ')
            if not separator:
                continue
            messages.extend([{'role': 'user', 'text': original_conversation_text(question)},
                             {'role': 'assistant', 'text': reply}])
            created_at = memory.get('created_at')
        if messages:
            items.append({'id': 'account-conversation', 'project_id': 'account-conversation',
                          'messages': messages, 'workspace': {}, 'created_at': created_at})
        items.sort(key=lambda item: item.get('created_at') or '', reverse=True)
        return {'items': items}
    finally:
        service.client.close()


@router.put('/profile')
async def save_profile(payload: dict, authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        from .agent_lock import AgentTurnLease, AgentTurnBusyError
        async with AgentTurnLease(service) as lease:
            current = await lease.io(service.profile)
            # Generic workspace writes may be delayed snapshots. Explicit
            # language changes belong to the dedicated profile-settings route.
            merged = {**current, **payload}
            for key in ('preferred_language', 'conversation_language'):
                if key in current:
                    merged[key] = current[key]
                else:
                    merged.pop(key, None)
            await lease.check()
            result = await lease.io(service.save_profile, merged)
            await lease.check()
            return result
    except AgentTurnBusyError:
        raise HTTPException(409, 'Please wait for the current reply before saving workspace context.') from None
    finally:
        service.client.close()


@router.get('/profile')
async def read_workspace_profile(authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        import asyncio
        from .conversation_locale import restore_from_history
        profile = await asyncio.to_thread(service.profile)
        profile = await restore_from_history(service, profile)
        return {key: value for key, value in profile.items() if not key.startswith('_')}
    finally:
        service.client.close()


@router.post('/attachments')
async def upload_attachment(request: Request, filename: str,
                            authorization: str | None = Header(default=None)):
    # Keep the same 50 MiB bound as the bucket, including chunked uploads.
    chunks = bytearray()
    async for chunk in request.stream():
        chunks.extend(chunk)
        if len(chunks) > 50 * 1024 * 1024:
            raise HTTPException(413, 'Attachment exceeds 50 MiB')
    service = storage(authorization)
    try:
        path = service.put_attachment(filename, bytes(chunks), request.headers.get('content-type', 'application/octet-stream'))
        return {'path': path}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    finally:
        service.client.close()


@router.get('/memories')
def list_memories(authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        return {'items': service.memories()}
    finally:
        service.client.close()


@router.post('/memories')
def save_memory(payload: MemoryInput, authorization: str | None = Header(default=None)):
    service = storage(authorization)
    try:
        return service.save_memory(payload.content)
    finally:
        service.client.close()
