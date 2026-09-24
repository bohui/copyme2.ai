"""HTTP namespace adapters for product-scoped API routes.

The memoir product owns the public ``/api/v1/memoir`` namespace.  The
prototype's original ``/v1`` routes remain available as a compatibility
interface while clients migrate.  Rewriting happens before FastAPI routing,
so the existing route implementation and domain entities stay unchanged.
"""

from __future__ import annotations

from typing import Any

MEMOIR_API_PREFIX = "/api/v1/memoir"
LEGACY_API_PREFIX = "/v1"


def rewrite_memoir_path(scope: dict[str, Any]) -> bool:
    """Rewrite a public memoir path to the legacy route implementation.

    Returns ``True`` when the request used the canonical product namespace.
    The ASGI scope is mutated in place before FastAPI performs route matching.
    """

    path = str(scope.get("path", ""))
    if path != MEMOIR_API_PREFIX and not path.startswith(f"{MEMOIR_API_PREFIX}/"):
        return False

    suffix = path[len(MEMOIR_API_PREFIX) :]
    rewritten = f"{LEGACY_API_PREFIX}{suffix}"
    scope["path"] = rewritten
    scope["raw_path"] = rewritten.encode("utf-8")
    return True


def memoir_url(path: str) -> str:
    """Return the canonical memoir URL for an internal ``/v1`` path."""

    if path == LEGACY_API_PREFIX:
        return MEMOIR_API_PREFIX
    if path.startswith(f"{LEGACY_API_PREFIX}/"):
        return f"{MEMOIR_API_PREFIX}{path[len(LEGACY_API_PREFIX):]}"
    return path
