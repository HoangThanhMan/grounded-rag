"""One error shape for every failure the API reports:

    {"error": {"code": "not_found", "message": "...", "request_id": "..."}}

`code` is stable and meant for the client to branch on; `message` is for
people. The request id is the one in the X-Request-ID header and in the log
line of that request, so a user's screenshot leads straight to the log. A
crash nobody planned for gets the same shape, from the middleware.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from grounded_rag.api.middleware import current_request_id
from grounded_rag.generation.llm_client import LLMUnavailable

CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "too_large",
    422: "validation_error",
    429: "rate_limited",
    503: "unavailable",
}


class AppError(Exception):
    def __init__(
        self, status: int, code: str, message: str, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.headers = status, code, message, headers


def body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message, "request_id": current_request_id()}}


def error_response(
    status: int, code: str, message: str, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status, content=body(code, message), headers=headers)


def install(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        return error_response(exc.status, exc.code, exc.message, exc.headers)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException) -> JSONResponse:
        code = CODES.get(exc.status_code, f"http_{exc.status_code}")
        return error_response(exc.status_code, code, str(exc.detail), exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid(request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p != "body")
        message = f"{where}: {first.get('msg', 'invalid request')}" if where else "invalid request"
        return error_response(422, "validation_error", message)

    @app.exception_handler(LLMUnavailable)
    async def llm_down(request: Request, exc: LLMUnavailable) -> JSONResponse:
        # Refusing to answer is a 200. Failing to reach the model is not.
        return error_response(503, "llm_unavailable", f"LLM provider unavailable: {exc}")
