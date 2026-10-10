"""Recall access uses durable usage and verified payment entitlements."""
import os


def free_recall_rounds() -> int:
    return _positive_config('MEMORY_SPARK_FREE_RECALL_ROUNDS', 20)


def private_draft_cadence() -> int:
    return _positive_config('MEMORY_SPARK_PRIVATE_DRAFT_CADENCE', 5)


def _positive_config(name, default):
    try:
        value = int(os.getenv(name, str(default)))
        if not 1 <= value <= 1000000:
            raise ValueError
    except ValueError:
        raise ValueError(f'{name} must be a positive integer from 1 through 1000000') from None
    return value


def recall_status(completed: int, entitlement: dict | None, *, free_rounds: int | None = None) -> dict:
    limit = free_recall_rounds() if free_rounds is None else free_rounds
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
    if not callable(reader):
        return None
    limit = free_recall_rounds()
    # Local evaluation backend only: extend this one configured account's
    # absolute allowance, without fabricating a purchase or changing payment data.
    owner = os.getenv('MEMORY_SPARK_EVAL_RECALL_OWNER_ID', '').strip()
    if owner and owner == getattr(storage, 'user_id', None):
        limit = max(limit, _positive_config('MEMORY_SPARK_EVAL_RECALL_LIMIT', limit))
    return recall_status(reader(), entitlement, free_rounds=limit)
