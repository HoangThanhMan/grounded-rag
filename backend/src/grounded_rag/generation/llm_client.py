"""One client for every provider.

Groq, Gemini's compatibility endpoint, Ollama, vLLM and OpenAI all speak the
OpenAI chat-completions protocol, so swapping provider is a base URL and a key
in .env - "we ran out of free tier" is a five-minute problem, not a rewrite.
Plain HTTP through httpx, no SDK, so the protocol stays visible.
"""

from __future__ import annotations

import asyncio
import functools
import json
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from grounded_rag.config import settings

_RETRYABLE = {408, 429, 500, 502, 503, 504}
_BACKOFF_S = 0.5
# 5xx means the provider is overloaded, not that we asked too fast: backing off
# half a second just spends a retry. 429 is different - it carries its own hint.
_SERVER_BACKOFF_S = 5.0
_MAX_WAIT_S = 60.0
_sleep = asyncio.sleep  # tests replace it to see the waits without waiting
# the block of the first source; its header is "[C1]" or "[C1 (Điều 35, Khoản 1)]"
# "[C1] Điều 105, Khoản 1\n<clause>" - the label, then where it came from
_FIRST_SOURCE = re.compile(r"^\[C1\][^\n]*\n(.*?)(?=\n\n|\Z)", re.MULTILINE | re.DOTALL)


class LLMUnavailable(RuntimeError):
    """The provider failed after retries. The API turns this into a 503."""


@dataclass
class LLMResponse:
    text: str
    tokens: int = 0
    # The provider stopped at max_tokens: the text is unfinished. Thinking
    # models spend output tokens on reasoning first, so this happens with
    # budgets that look generous - and a cut-off sentence has no citation.
    truncated: bool = False


class LLMClient(Protocol):
    async def complete(self, system: str, user: str, **kw) -> LLMResponse: ...
    def stream(self, system: str, user: str, **kw) -> AsyncIterator[str]: ...


class MockClient:
    """Echoes the first document back with a citation. Lets the whole
    pipeline, the API and the eval harness run with no API key at all.

    Asked to rewrite a follow-up, it returns the new question unchanged."""

    async def complete(self, system: str, user: str, **kw) -> LLMResponse:
        if "CÂU HỎI MỚI:" in user:
            text = user.rsplit("CÂU HỎI MỚI:", 1)[-1].strip()
        else:
            m = _FIRST_SOURCE.search(user)
            lines = m.group(1).splitlines() if m else []
            # quote the clause itself, not the article heading above it
            body = re.sub(r"^\d+\.\s*", "", " ".join(" ".join(lines[1:] or lines).split()))
            if len(body) > 180:
                body = body[:180].rsplit(" ", 1)[0]
            text = f"{body} [C1]" if body else "Không tìm thấy thông tin này trong tài liệu."
        return LLMResponse(text=text, tokens=len(text.split()))

    async def stream(self, system: str, user: str, **kw) -> AsyncIterator[str]:
        res = await self.complete(system, user, **kw)
        for token in res.text.split(" "):
            yield token + " "


class _ConnectionPool:
    """One httpx.AsyncClient per provider client, so calls reuse connections
    and TLS sessions instead of opening a new one for every completion.

    An AsyncClient belongs to the event loop it first ran on, and the eval
    scripts and the tests each run their own loop - so it is re-created when
    the loop changes rather than shared across loops."""

    def __init__(self, timeout: float, transport: httpx.AsyncBaseTransport | None) -> None:
        self._timeout = timeout
        self._transport = transport  # tests inject httpx.MockTransport
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def get(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if self._client is None or self._client.is_closed or self._loop is not loop:
            self._client = httpx.AsyncClient(timeout=self._timeout, transport=self._transport)
            self._loop = loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and self._loop is asyncio.get_running_loop():
            await self._client.aclose()
        self._client = None


class OpenAICompatClient:
    """POST {base_url}/chat/completions - vLLM, Ollama, Gemini, OpenAI."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout: float | None = None,
        retries: int | None = None,
        reasoning_effort: str = "",
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/chat/completions"
        self.headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self.model = model
        self.timeout = timeout or settings.llm_timeout_s
        self.retries = settings.llm_max_retries if retries is None else retries
        self.reasoning_effort = reasoning_effort
        self._http = _ConnectionPool(self.timeout, transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    def _body(self, system: str, user: str, temperature: float, max_tokens: int) -> dict:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.reasoning_effort:  # only sent when set: not every server accepts it
            body["reasoning_effort"] = self.reasoning_effort
        return body

    async def complete(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 512
    ) -> LLMResponse:
        body = self._body(system, user, temperature, max_tokens)
        data = await _post_json(self._http.get(), self.url, body, self.headers, self.retries)
        try:
            choice = data["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as e:
            raise LLMUnavailable(f"unexpected response: {str(data)[:200]}") from e
        usage = data.get("usage") or {}
        return _response(
            text,
            usage.get("prompt_tokens", 0),
            usage.get("completion_tokens", 0),
            truncated=choice.get("finish_reason") == "length",
        )

    async def stream(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 512
    ) -> AsyncIterator[str]:
        """The answer token by token. A rate limit or an overloaded server is
        retried like `complete` does - but only before the first token: once
        text has reached the user, a retry would repeat it."""
        body = {**self._body(system, user, temperature, max_tokens), "stream": True}
        error, wait = "no attempt made", 0.0
        for attempt in range(self.retries + 1):
            if attempt:
                await _sleep(wait)
            try:
                async with self._http.get().stream(
                    "POST", self.url, json=body, headers=self.headers
                ) as r:
                    if r.status_code >= 400:
                        text = (await r.aread()).decode(errors="replace")
                        error = f"HTTP {r.status_code}: {text[:200]}"
                        if r.status_code not in _RETRYABLE:
                            break
                        wait = _retry_wait(r, attempt)
                        continue
                    async for line in r.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if payload == "[DONE]":
                            return
                        for choice in json.loads(payload).get("choices") or []:
                            if delta := (choice.get("delta") or {}).get("content"):
                                yield delta
                    return
            except httpx.HTTPError as e:
                raise LLMUnavailable(f"{self.url} -> {type(e).__name__}: {e}") from e
        raise LLMUnavailable(f"{self.url} -> {error}")


async def _post_json(
    client: httpx.AsyncClient,
    url: str,
    body: dict,
    headers: dict[str, str],
    retries: int,
) -> dict[str, Any]:
    """POST with retries on transient failures (timeouts, 429, 5xx). Anything
    else fails fast."""
    error = "no attempt made"
    wait = 0.0
    for attempt in range(retries + 1):
        if attempt:
            await _sleep(wait)
        try:
            r = await client.post(url, json=body, headers=headers)
        except httpx.TransportError as e:
            error = f"{type(e).__name__}: {e}"
            wait = _BACKOFF_S * 2**attempt
            continue
        if r.status_code < 400:
            return r.json()
        error = f"HTTP {r.status_code}: {r.text[:200]}"
        if r.status_code not in _RETRYABLE:
            break
        wait = _retry_wait(r, attempt)
    raise LLMUnavailable(f"{url} -> {error}")


def _retry_wait(r: httpx.Response, attempt: int) -> float:
    """The server's own hint when it gives one - Retry-After, or the
    retryDelay Gemini puts in a 429 body - else exponential backoff. Free-tier
    rate limits reset per minute, so a fixed half-second retry just fails again."""
    hint = r.headers.get("retry-after")
    if hint is None and (m := re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', r.text)):
        hint = m.group(1)
    base = _SERVER_BACKOFF_S if r.status_code >= 500 else _BACKOFF_S
    try:
        return min(float(hint), _MAX_WAIT_S) if hint is not None else base * 2**attempt
    except ValueError:  # Retry-After can also be an HTTP date
        return base * 2**attempt


def _response(
    text: str, input_tokens: int, output_tokens: int, *, truncated: bool = False
) -> LLMResponse:
    return LLMResponse(text=text.strip(), tokens=input_tokens + output_tokens, truncated=truncated)


@functools.lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    if settings.llm_provider == "mock":
        return MockClient()
    return OpenAICompatClient(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        reasoning_effort=settings.llm_reasoning_effort,
    )
