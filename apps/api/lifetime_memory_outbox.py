"""Bounded durable projection work and explicitly optional engine artifacts.

Canonical accept/reply transactions enqueue obligations in PostgreSQL, not here.
A failed drain never changes the accepted/saved receipt, commercial counters, or
claims a complete backup. Raw engine objects cannot authorize canonical evidence.
"""
from __future__ import annotations

from hashlib import sha256
import json
from uuid import UUID

from .lifetime_memory_contracts import ExecutionFence


_ARTIFACT_KEYS = {'schema_version', 'owner_id', 'conversation_id', 'policy_epoch',
    'execution_generation', 'snapshot_semantics', 'files', 'removed_paths',
    'omissions', 'complete', 'canonical_recovery_required', 'status', 'predecessor'}


def artifact_manifest_bytes(candidate):
    """Return exactly the measured delta; None means reuse a persisted manifest.

    The uploader's _state/counters are local checkpoints, never wire content.
    A zero-byte result still requires the database to find an existing accepted
    manifest ID in the same policy/generation scope, under a current fence. It cannot create an empty replacement.
    """
    if not isinstance(candidate, dict) or not _ARTIFACT_KEYS.issubset(candidate):
        raise ValueError('complete artifact candidate required')
    manifest_id = candidate.get('manifest_id')
    if not isinstance(manifest_id, str) or len(manifest_id) != 64 or any(c not in '0123456789abcdef' for c in manifest_id):
        raise ValueError('invalid artifact digest')
    if type(candidate.get('manifest_bytes')) is not int or candidate['manifest_bytes'] < 0:
        raise ValueError('bounded integer artifact size required')
    if candidate['manifest_bytes'] == 0:
        if candidate['files'] or candidate['removed_paths'] or candidate['omissions'] or candidate['predecessor'] != manifest_id:
            raise ValueError('unchanged artifact must reuse its predecessor')
        return None
    wire = json.dumps({key: candidate[key] for key in _ARTIFACT_KEYS}, sort_keys=True,
                      separators=(',', ':')).encode('utf-8')
    if len(wire) != candidate.get('manifest_bytes') or sha256(wire).hexdigest() != manifest_id:
        raise ValueError('artifact manifest size or digest mismatch')
    if len(wire) > 1024 * 1024:
        raise ValueError('artifact manifest exceeds bounded job size')
    return wire


class LifetimeMemoryOutbox:
    def __init__(self, rpc):
        self.rpc = rpc

    @staticmethod
    def _fence(fence):
        return ExecutionFence.model_validate(fence).model_dump(mode='json')

    def inspect(self, conversation_id, *, after=None, limit=32):
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('inspection limit must be between 1 and 32')
        return self.rpc('read_lifetime_memory_obligations',
            p_conversation_id=str(UUID(str(conversation_id))),
            p_after=str(UUID(str(after))) if after else None, p_limit=limit)

    def claim(self, fence):
        return self.rpc('claim_lifetime_memory_obligation', p_fence=self._fence(fence))

    def complete(self, fence, obligation):
        # SQL derives exact source/version/span references from canonical rows;
        # no caller-supplied prose or backup-success flag can be linked here.
        return self.rpc('complete_lifetime_memory_obligation', p_fence=self._fence(fence),
            p_id=str(UUID(str(obligation['id']))), p_claim_token=str(UUID(str(obligation['claim_token']))))

    def fail(self, fence, obligation, *, error_code='projection_failed'):
        if error_code not in {'projection_failed', 'storage_unavailable', 'manifest_incomplete'}:
            raise ValueError('bounded error code required; never store private exception text')
        return self.rpc('fail_lifetime_memory_obligation', p_fence=self._fence(fence),
            p_id=str(UUID(str(obligation['id']))), p_claim_token=str(UUID(str(obligation['claim_token']))),
            p_error_code=error_code)

    def cancel(self, fence, obligation_id):
        return self.rpc('cancel_lifetime_memory_obligation', p_fence=self._fence(fence),
            p_id=str(UUID(str(obligation_id))))

    def drain(self, fence, *, limit=4):
        if type(limit) is not int or not 1 <= limit <= 32:
            raise ValueError('drain limit must be between 1 and 32')
        snapshot = self._fence(fence)
        processed = failed = 0
        for _ in range(limit):
            try:
                obligation = self.claim(snapshot)
            except Exception:
                return dict(processed=processed, failed=failed+1, pending=True, backup_complete=False)
            if not obligation:
                # A delayed retry or terminal failure is not an empty successful
                # queue. Claim returns an explicit no-ready-work status for it.
                return dict(processed=processed, failed=failed, pending=False, backup_complete=False)
            if obligation.get('status') == 'not_ready':
                return dict(processed=processed, failed=failed, pending=True, backup_complete=False)
            try:
                result = self.complete(snapshot, obligation)
                if not result or result.get('status') != 'succeeded':
                    raise RuntimeError('projection not confirmed')
                processed += 1
            except Exception:
                failed += 1
                try:
                    self.fail(snapshot, obligation)
                except Exception:
                    # The durable running claim expires and is retryable. Never
                    # conceal a failed failure receipt as completed work.
                    pass
                return dict(processed=processed, failed=failed, pending=True, backup_complete=False)
        return dict(processed=processed, failed=failed, pending=True, backup_complete=False)

    def link_artifact(self, fence, candidate, *, authorized=False):
        if authorized is not True:
            raise ValueError('raw engine artifact requires explicit authorization')
        snapshot = self._fence(fence)
        scope = {'owner_id': snapshot['identity']['owner_id'],
            'conversation_id': snapshot['identity']['conversation_id'],
            'policy_epoch': snapshot['policy_epoch'], 'execution_generation': snapshot['execution_generation']}
        if any(candidate.get(key) != value for key, value in scope.items()):
            raise ValueError('artifact scope does not match fence')
        wire = artifact_manifest_bytes(candidate)
        return self.rpc('link_lifetime_optional_artifact', p_fence=snapshot,
            p_manifest_id=candidate['manifest_id'], p_manifest=wire.decode('utf-8') if wire else None,
            p_authorized=True)
