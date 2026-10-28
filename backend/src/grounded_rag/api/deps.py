"""Dependencies shared by the routes."""

from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Header, HTTPException

from grounded_rag.config import settings


def require_admin(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Off unless ADMIN_API_KEY is set, so a server nobody configured for it
    never takes files from the network. The comparison is constant-time."""
    expected = settings.admin_api_key
    if not expected:
        raise HTTPException(403, "document management is disabled: set ADMIN_API_KEY")
    if x_api_key is None or not hmac.compare_digest(x_api_key.encode(), expected.encode()):
        raise HTTPException(401, "missing or wrong X-API-Key", {"WWW-Authenticate": "ApiKey"})
