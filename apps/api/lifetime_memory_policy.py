"""Exact authority diagnostics for accepted-but-incomplete privacy policy.

Never infer this recoverable state from provider text, a timeout, or a generic
permission/fence error. The safe exception carries no source or SQL details.
"""
import httpx

from .lifetime_memory_publication import PublicationUnavailable


class PolicyUnavailable(PublicationUnavailable):
    code = 'LIFETIME_POLICY_PENDING'

    def __init__(self):
        super().__init__('Accepted conversation policy requires maintenance before private content can be used')


def is_policy_pending(error):
    if isinstance(error, PolicyUnavailable):
        return True
    from psycopg import Error
    if isinstance(error, Error):
        return error.sqlstate == '55000' and error.diag.message_primary == PolicyUnavailable.code
    if isinstance(error, httpx.HTTPStatusError):
        try:
            detail = error.response.json()
        except ValueError:
            return False
        return (error.response.is_error and isinstance(detail, dict)
            and detail.get('code') == '55000' and detail.get('message') == PolicyUnavailable.code)
    return False
