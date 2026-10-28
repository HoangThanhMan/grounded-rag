"""Whose conversations are whose, without accounts.

Each browser gets a random token in an HttpOnly cookie on its first request,
renewed on every visit after; its conversations are stored under a hash of
that token, and every conversation route answers only to the browser that
started it. Lose the cookie and the history is gone - the price of having no
sign-in.
"""

from __future__ import annotations

import hashlib
import re
import secrets

from fastapi import Request
from starlette.requests import cookie_parser
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from grounded_rag.config import settings

COOKIE = "gr_owner"
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{32,64}$")
YEAR = 365 * 24 * 3600


def owner_of(token: str) -> str:
    """What is stored: a leaked database does not hand out working cookies."""
    return hashlib.sha256(token.encode()).hexdigest()[:32]


class OwnerCookie:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = _cookie(scope) or secrets.token_urlsafe(32)
        scope.setdefault("state", {})["owner"] = owner_of(token)

        async def send_with_cookie(message: Message) -> None:
            if message["type"] == "http.response.start":
                value = f"{COOKIE}={token}; Path=/; Max-Age={YEAR}; HttpOnly; SameSite=Lax"
                if settings.cookie_secure:
                    value += "; Secure"
                message["headers"] = [*message.get("headers", []),
                                      (b"set-cookie", value.encode("latin-1"))]
            await send(message)

        await self.app(scope, receive, send_with_cookie)


def current_owner(request: Request) -> str:
    return request.state.owner


def _cookie(scope: Scope) -> str | None:
    """Starlette's parser, not http.cookies: that one stops at the first
    cookie it dislikes, and another app on the host may set one."""
    raw = dict(scope["headers"]).get(b"cookie", b"").decode("latin-1")
    value = cookie_parser(raw).get(COOKIE, "")
    return value if _TOKEN.match(value) else None
