"""Request id, access log and the last-resort 500, as plain ASGI so a
streamed answer is neither buffered nor logged before it has finished.

The id is taken from X-Request-ID when the client (or nginx) sends a sane
one, generated otherwise, returned in the response header, and written on the
request's one JSON log line. An exception nothing else handled is answered
here too: Starlette's own handler for it runs outside this middleware, where
the request id is already gone.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("grounded_rag.access")

_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
_VALID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def current_request_id() -> str:
    return _request_id.get()


class RequestContext:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        sent = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = sent if _VALID.match(sent) else uuid.uuid4().hex
        token = _request_id.set(rid)
        started = time.perf_counter()
        status = 500
        response_started = False

        async def send_with_id(message: Message) -> None:
            nonlocal status, response_started
            if message["type"] == "http.response.start":
                status, response_started = message["status"], True
                message.setdefault("headers", [])
                message["headers"] = [
                    *message["headers"], (b"x-request-id", rid.encode("latin-1"))
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        except Exception:
            log.exception("unhandled error")
            if response_started:
                raise       # headers are out; nothing left to do but drop the connection
            body = json.dumps({"error": {
                "code": "internal", "message": "internal server error", "request_id": rid,
            }}).encode()
            await send_with_id({
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())],
            })
            await send_with_id({"type": "http.response.body", "body": body})
        finally:
            log.info(json.dumps({
                "request_id": rid,
                "method": scope["method"],
                "path": scope["path"],
                "status": status,
                "ms": int((time.perf_counter() - started) * 1000),
            }))
            _request_id.reset(token)
