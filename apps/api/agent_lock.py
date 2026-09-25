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

    async def __aenter__(self):
        acquired = await asyncio.to_thread(
            self.storage.acquire_agent_turn_lease,
            self.lease_token,
            self.lease_seconds,
        )
        if not acquired:
            raise AgentTurnBusyError("A Codex turn is already running for this user")
        self._heartbeat_task = asyncio.create_task(self._heartbeat())
        return self

    async def _heartbeat(self):
        interval = max(10, self.lease_seconds // 3)
        try:
            while True:
                await asyncio.sleep(interval)
                renewed = await asyncio.to_thread(
                    self.storage.renew_agent_turn_lease,
                    self.lease_token,
                    self.lease_seconds,
                )
                if not renewed:
                    self._lost = True
                    return
        except asyncio.CancelledError:
            return
        except Exception:
            # Do not silently allow a lease to expire after a persistence
            # outage.  The caller will fail closed before saving the turn.
            self._lost = True

    def assert_held(self):
        if self._lost:
            raise RuntimeError("The Codex turn lease was lost; the turn was not saved")

    async def __aexit__(self, exc_type, exc, tb):
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        try:
            released = await asyncio.to_thread(
                self.storage.release_agent_turn_lease,
                self.lease_token,
            )
            if not released and exc is None:
                raise RuntimeError("The Codex turn lease could not be released")
        except Exception:
            if exc is None:
                raise
        if exc is None:
            self.assert_held()
