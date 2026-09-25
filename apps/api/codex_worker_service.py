"""Private Codex worker for isolated, per-user app-server execution."""
from __future__ import annotations

import base64
import asyncio
import fcntl
import hashlib
import hmac
import json
import os
import threading
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Request
from pydantic import BaseModel, Field

from .codex_agent import CodexConnection, provider_config
from .codex_artifacts import iter_artifacts
from .codex_runtime import build_system_prompt
from .codex_worker_files import migrate_home, write_config
from .agent_lock import AgentTurnBusyError


class WorkerTurnInput(BaseModel):
    user_id: UUID
    thread_id: str | None = Field(default=None, min_length=1, max_length=256)
    memories: list[str] = Field(default_factory=list, max_length=20)
    text: str = Field(min_length=1, max_length=100000)
    model: str | None = Field(default=None, min_length=1, max_length=256)


class CodexWorker:
    """Run Codex outside the API container and under a user-specific UID."""

    def __init__(self, *, home_root=None, legacy_root=None, command=None, base_url=None, model=None, timeout=120):
        self.home_root = Path(home_root or os.getenv(
            "MEMORY_SPARK_CODEX_HOME", "var/codex-worker-users"
        ))
        # The image initializer requests 0711. Some volume providers
        # normalize a mounted root to 0755; either way, sibling contents stay
        # protected because each user home below is 0700 and UID-owned.
        self.home_root.mkdir(parents=True, exist_ok=True, mode=0o711)
        legacy_root = legacy_root or os.getenv('MEMORY_SPARK_LEGACY_CODEX_HOME')
        self.legacy_root = Path(legacy_root) if legacy_root else None
        self.command = command or [os.getenv("MEMORY_SPARK_CODEX_BIN", "codex"), "app-server"]
        self.privdrop = os.getenv("MEMORY_SPARK_CODEX_PRIVDROP_BIN", "/usr/bin/setpriv")
        self.base_url = base_url or os.getenv(
            "MEMORY_SPARK_LLM_BASE_URL", "http://127.0.0.1:4000/v1"
        )
        self.model = model or os.getenv("MEMORY_SPARK_LLM_MODEL", "deepseek-v4-flash")
        self.api_key = os.getenv("MEMORY_SPARK_LLM_API_KEY", "")
        # Bound the whole execution, not each protocol request separately.
        # This remains below the API's 300-second lease even if the API dies.
        self.timeout = min(timeout, 240)
        self._locks: dict[str, object] = {}
        self._identity_lock = threading.Lock()
        self._identity_file = self.home_root / ".user-ids.json"

    def _lock(self, user_id: str):
        # This lock is only an in-worker optimization. The API's Supabase
        # lease remains authoritative across replicas and worker instances.
        import asyncio

        return self._locks.setdefault(user_id, asyncio.Lock())

    def _uid_for(self, user_id: str) -> int:
        """Allocate a stable, non-system UID for the user's Codex process."""
        with self._identity_lock, (self.home_root / '.identity.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                mapping = json.loads(self._identity_file.read_text(encoding="utf-8"))
            except FileNotFoundError:
                mapping = {}
            if user_id in mapping:
                return int(mapping[user_id])

            used = {int(value) for value in mapping.values()}
            first = 20000 + (int(hashlib.sha256(user_id.encode()).hexdigest()[:8], 16) % 40000)
            candidate = first
            while candidate in used:
                candidate = 20000 + ((candidate - 20000 + 1) % 40000)
                if candidate == first:
                    raise RuntimeError("No Codex worker UID is available")
            mapping[user_id] = candidate
            temporary = self._identity_file.with_suffix(".tmp")
            temporary.write_text(json.dumps(mapping, sort_keys=True), encoding="utf-8")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._identity_file)
            return candidate

    def _home(self, user_id: str, uid: int) -> Path:
        home = self.home_root / user_id
        if not home.exists() and not home.is_symlink() and self.legacy_root is not None:
            migrate_home(self.legacy_root / user_id, home, uid)
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        write_config(home, self.home_root, uid, provider_config(self.base_url, self.model))
        return home

    def _run_command(self, uid: int):
        return [
            self.privdrop,
            f"--reuid={uid}",
            f"--regid={uid}",
            "--clear-groups",
            "--no-new-privs",
            *self.command,
        ]

    async def turn(self, payload: WorkerTurnInput):
        user_id = str(payload.user_id)
        async with self._lock(user_id):
            # Shared-volume lock also covers API disconnect/lease expiry and
            # multiple worker processes. Never overlap writers to a Codex home.
            with (self.home_root / f'.turn-{user_id}.lock').open('a') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise AgentTurnBusyError('Codex worker is busy for this user') from None
                async with asyncio.timeout(self.timeout):
                    return await self._turn(payload)

    async def _turn(self, payload: WorkerTurnInput):
        user_id = str(payload.user_id)
        uid = self._uid_for(user_id)
        home = self._home(user_id, uid)
        model = payload.model or self.model
        context = "\n".join(str(memory)[:2000] for memory in payload.memories) or "(none)"
        prompt = f"{build_system_prompt(context)}\n\nStoryteller message:\n{payload.text}"
        environment = {"MEMORY_SPARK_LLM_API_KEY": self.api_key}
        async with CodexConnection(
            self._run_command(uid),
            home,
            provider_env=environment,
            timeout=self.timeout,
        ) as connection:
            if payload.thread_id:
                result = await connection.request("thread/resume", {
                    "threadId": payload.thread_id,
                    "cwd": str(home),
                    "modelProvider": "llm_provider",
                    "model": model,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                })
            else:
                result = await connection.request("thread/start", {
                    "cwd": str(home),
                    "ephemeral": False,
                    "modelProvider": "llm_provider",
                    "model": model,
                    "approvalPolicy": "never",
                    "sandbox": "read-only",
                    "baseInstructions": build_system_prompt(context),
                })
            thread_id = result["thread"]["id"]
            reply = await connection.turn(thread_id, prompt)

        artifacts = [
            {"path": path, "content": base64.b64encode(content).decode("ascii")}
            for path, content in iter_artifacts(home)
        ]
        return {"thread_id": thread_id, "reply": reply, "artifacts": artifacts}


app = FastAPI(title="Memory Spark Codex Worker")
worker = CodexWorker()


def _require_worker_secret(provided: str | None):
    expected = os.getenv("MEMORY_SPARK_CODEX_WORKER_SECRET", "")
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="Invalid Codex worker credentials")


@app.get("/health")
def health():
    return {"status": "ok", "service": "memory-spark-codex-worker"}


@app.post("/internal/codex/turn")
async def turn(payload: WorkerTurnInput, request: Request,
               x_codex_worker_secret: str | None = Header(default=None)):
    _require_worker_secret(x_codex_worker_secret)
    task = asyncio.create_task(worker.turn(payload))
    try:
        while not task.done():
            if await request.is_disconnected():
                task.cancel()
                break
            await asyncio.wait({task}, timeout=0.1)
        return await task
    except AgentTurnBusyError as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except TimeoutError:
        raise HTTPException(status_code=504, detail='Codex worker turn timed out') from None
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=f"Codex worker failed: {error}") from None
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
