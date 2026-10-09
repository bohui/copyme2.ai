"""Two explicit, bounded evaluation profiles; no implicit product-limit override.

This module declares synthetic task scope only. It does not authorize execution,
create accounts, change subscriptions or supply any real payment entitlement.
"""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class _Profile:
    name: str
    case_ids: tuple
    rounds: int
    checkpoints: tuple
    plans: object
    bridge: object
    max_requests: int
    max_seconds: int
    case_max_requests: int | None = None
    case_max_seconds: int | None = None
    dataset_version: str | None = None
    dataset_sha256: str | None = None

    def validate_limits(self, requests, seconds, case_requests=None, case_seconds=None):
        def bounded(value, maximum, integer=False):
            return ((type(value) is int if integer else type(value) in (int, float))
                    and math.isfinite(value) and 0 < value <= maximum)
        if not bounded(requests, self.max_requests, True) or not bounded(seconds, self.max_seconds):
            raise ValueError('Explicit approved request/time bounds required')
        if self.case_max_requests is None:
            if case_requests is not None or case_seconds is not None:
                raise ValueError('Historical profile does not accept campaign limits')
        elif (not bounded(case_requests, self.case_max_requests, True)
              or not bounded(case_seconds, self.case_max_seconds)):
            raise ValueError('Explicit approved per-case request/time bounds required')

    @property
    def family_enabled(self):
        return self.name == 'subscription_fifty'

    def family_enabled_for_round(self, case, ordinal):
        return self.family_enabled and (case['language'] == 'en-AU' or ordinal >= 16)

    def entitlement(self, case, ordinal=1):
        if not self.family_enabled_for_round(case, ordinal):
            return None
        # Consumed only by the verified disposable PostgresRest HTTP facade.
        # No payment table, payment provider or real account is changed.
        return {'user_id': case['owner_id'], 'status': 'paid',
                'plan_key': 'family_memoir_v1', 'stripe_price_id': 'synthetic-memoir-fifty-price',
                'family_tree': True, 'timeline': True, 'expanded_details': True}


def profile_for(name):
    if name == 'subscription_progressive':
        from scripts.issue14_progressive_readback import CASE_IDS, ProgressiveReadback, case_plans_for_run
        return _Profile(name, CASE_IDS, 15, (5, 10, 15), case_plans_for_run,
                        ProgressiveReadback, 160, 1800)
    if name == 'subscription_fifty':
        from scripts.memoir_fifty_readback import (
            CASE_IDS, CHECKPOINTS, FiftyReadback, case_plans_for_run, DATASET_SHA256)
        return _Profile(name, CASE_IDS, 50, CHECKPOINTS, case_plans_for_run,
                        FiftyReadback, 3000, 36000, 600, 7200,
                        'memoir-five-case/1', DATASET_SHA256)
    raise ValueError('An explicit supported subscription evaluation profile is required')
