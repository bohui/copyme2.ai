"""Cross-replica serialization for user-owned Codex turns."""
from __future__ import annotations

import asyncio
from uuid import uuid4


class AgentTurnBusyError(RuntimeError):
    """Another API replica is already running this user's Codex turn."""


class AgentTurnLease:
    """A renewable Supabase lease with a small local async surface.

    The database RPC is the authoritative seam.  The local asyncio lock still
    avoids needless database contention inside one process, while the lease
    handles multiple API replicas and crash recovery through expiry.
    """

    def __init__(self, storage, *, lease_seconds: int = 300):
        self.storage = storage
        self.lease_seconds = max(30, min(int(lease_seconds), 900))
        self.lease_token = str(uuid4())
        self._heartbeat_task: asyncio.Task | None = None
        self._lost = False
        self._owner: asyncio.Task | None = None
        self._cancel_requested = False

    @staticmethod
    async def io(function, *args, **kwargs):
        # Cancelling to_thread does not stop its thread. Settle outstanding IO
        # before releasing the lease or closing the request's HTTP client.
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            while not task.done():
                try:
                    await asyncio.shield(task)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not task.cancelled():
                task.exception()  # Retrieve any IO failure; preserve cancellation.
            raise

    async def __aenter__(self):
        try:
            acquired = await self.io(
                self.storage.acquire_agent_turn_lease,
                self.lease_token,
                self.lease_seconds,
            )
        except asyncio.CancelledError:
            # Acquisition may have succeeded after the client disconnected.
            # Releasing this random token cannot release another holder's row.
            try:
                await self.io(self.storage.release_agent_turn_lease, self.lease_token)
            except Exception:
                pass  # A persistence outage leaves expiry as the safe fallback.
            raise
        if not acquired:
            raise AgentTurnBusyError("A Codex turn is already running for this user")
        self._owner = asyncio.current_task()
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        return self

    async def _heartbeat(self):
        interval = max(10, self.lease_seconds // 3)
        try:
            while True:
                await asyncio.sleep(interval)
                renewed = await self.io(
                    self.storage.renew_agent_turn_lease,
                    self.lease_token,
                    self.lease_seconds,
                )
                if not renewed:
                    self._lose()
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            self._lose()

    def _lose(self):
        self._lost = True
        if self._owner is not None:
            self._cancel_requested = self._owner.cancel()

    def assert_held(self):
        if self._lost:
            raise RuntimeError("The Codex turn lease was lost; check the conversation before retrying")

    async def check(self):
        self.assert_held()
        renewed = await self.io(
            self.storage.renew_agent_turn_lease, self.lease_token, self.lease_seconds
        )
        if not renewed:
            self._lost = True
        self.assert_held()

    async def __aexit__(self, exc_type, exc, tb):
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        try:
            released = await self.io(
                self.storage.release_agent_turn_lease,
                self.lease_token,
            )
            if not released and exc is None:
                raise RuntimeError("The Codex turn lease could not be released")
        except Exception:
            if exc is None:
                raise
        if isinstance(exc, asyncio.CancelledError) and self._cancel_requested:
            # Consume only our cancellation, preserving an independent client
            # cancellation if it raced the heartbeat failure.
            if self._owner.uncancel():
                return
        if exc is None or isinstance(exc, asyncio.CancelledError):
            self.assert_held()
