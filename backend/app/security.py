from __future__ import annotations

import hmac

from fastapi import Header, HTTPException, status

from .config import get_settings


def _extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None

    value = authorization.strip()
    if not value:
        return None

    if value.lower().startswith("bearer "):
        return value[7:].strip() or None
    return value


def require_admin_access(
    x_admin_token: str | None = Header(default=None, alias="X-Admin-Token"),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> None:
    """Gate a route behind the single-tenant admin token.

    Security model (single-tenant, fail-closed):
    - This system has **no per-user accounts**. All data on one instance
      belongs to the same tenant. `ENABLE_ADMIN_GUARD` provides a coarse
      "is the caller allowed to touch this instance at all" gate rather than
      per-user / per-project ownership filtering.
    - To isolate multiple independent tenants on one host, run a separate
      process per tenant or put a reverse proxy / SSO in front.
    - When `ENABLE_ADMIN_GUARD` is true (default):
      * If `ADMIN_API_TOKEN` is set, callers must present it via
        `X-Admin-Token` or `Authorization: Bearer <token>`. `task_id` /
        `project_id` / `file_id` are NOT access credentials.
      * If `ADMIN_API_TOKEN` is empty, the instance is **misconfigured**:
        requests are rejected with `503 Service Unavailable`. This ensures a
        fail-closed posture — an operator who enables the guard but forgets
        to configure a token cannot silently expose every sensitive endpoint.
    - When `ENABLE_ADMIN_GUARD=false`, every route is open to any client that
      can reach the HTTP port — suitable only for a trusted single-user
      deployment on an isolated network where protection is explicitly
      turned off.
    """
    settings = get_settings()
    if not settings.ENABLE_ADMIN_GUARD:
        return

    expected_token = settings.get_admin_token()
    provided_token = x_admin_token or _extract_bearer_token(authorization)

    # Fail-closed: guard enabled but no token configured → the operator has
    # asked for protection yet hasn't provided a credential. We refuse to
    # serve sensitive routes rather than silently allowing anyone through.
    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "admin guard is enabled but no ADMIN_API_TOKEN is configured. "
                "Set ADMIN_API_TOKEN in backend/.env to activate protected mode, "
                "or set ENABLE_ADMIN_GUARD=false for a trusted single-user deployment."
            ),
        )

    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access token is required",
        )
