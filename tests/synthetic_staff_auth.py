"""Controlled external identity boundary for legacy staff acceptance cases.

These identities and server-owned roles exist only in this fixture. Production
authentication, accounts, credentials and role assignments are not changed.
"""
from types import SimpleNamespace

from fastapi import HTTPException

from apps.api import main


STAFF_ROLES = {
    'ops-1': ['operator'],
    'ops-rights': ['operator'],
    'ops-print': ['operator'],
    'ops-support': ['operator'],
    'ops-004': ['operator'],
    'ops-016': ['operator'],
    'ops-020': ['operator'],
    'ops-043': ['operator'],
    'ops-044': ['operator'],
    'ops-045': ['operator'],
    'ops-047': ['operator'],
    'ops-050': ['operator'],
    'ops-052': ['operator'],
    'finance-046': ['finance'],
    'support-agent': [],
    'support-004': [],
}


def staff_headers(account: str, **extra: str) -> dict[str, str]:
    headers = {'X-Account-Id': account, **extra}
    if account in STAFF_ROLES:
        headers['Authorization'] = 'Bearer synthetic-staff-session-' + account
    return headers


def authenticated_staff(monkeypatch) -> None:
    sessions = {
        staff_headers(account)['Authorization']: SimpleNamespace(
            user_id=account,
            user={'id': account, 'app_metadata': {'roles': roles}, 'user_metadata': {}},
            client=SimpleNamespace(close=lambda: None),
        ) for account, roles in STAFF_ROLES.items()
    }

    def verified_identity(authorization):
        if authorization not in sessions:
            raise HTTPException(401, 'Invalid or missing synthetic staff session')
        return sessions[authorization]

    monkeypatch.setattr(main, 'authenticated_storage', verified_identity)
