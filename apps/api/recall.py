"""Recall access uses durable usage and verified payment entitlements."""
import os


def free_recall_rounds() -> int:
    value = int(os.getenv('MEMORY_SPARK_FREE_RECALL_ROUNDS', '20'))
    if value < 1:
        raise ValueError('MEMORY_SPARK_FREE_RECALL_ROUNDS must be a positive integer')
    return value


def recall_status(completed: int, entitlement: dict | None) -> dict:
    limit = free_recall_rounds()
    paid = bool(entitlement and entitlement.get('status') == 'paid')
    return {
        'rounds_completed': completed,
        'free_rounds': limit,
        'payment_required': completed >= limit and not paid,
        'paid': paid,
    }


def storage_recall_status(storage, entitlement: dict | None) -> dict | None:
    reader = getattr(storage, 'recall_rounds_completed', None)
    # The retired story adapter and offline evaluation fixtures have no live quota.
    return recall_status(reader(), entitlement) if callable(reader) else None
