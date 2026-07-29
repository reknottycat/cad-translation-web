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
    settings = get_settings()
    if not settings.ENABLE_ADMIN_GUARD:
        return

    expected_token = settings.get_admin_token()
    provided_token = x_admin_token or _extract_bearer_token(authorization)

    if not expected_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access token is not configured",
        )

    if not provided_token or not hmac.compare_digest(provided_token, expected_token):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="admin access token is required",
        )
