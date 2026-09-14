"""One interface, several providers.

Swapping provider is a config change, not a code change - which is what
makes "we ran out of free tier" a five-minute problem instead of a rewrite.

vLLM, Ollama, Gemini's compatibility endpoint and OpenAI all speak the OpenAI
chat-completions protocol, so one client covers them and each provider is only
a preset (base URL + key). Anthropic gets its own small client. Both talk
plain HTTP through httpx - no SDKs, so the protocol stays visible.
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

GEMINI_OPENAI_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_RETRYABLE = {408, 429, 500, 502, 503, 504}
_BACKOFF_S = 0.5
# 5xx means the provider is overloaded, not that we asked too fast: backing off
# half a second just spends a retry. 429 is different - it carries its own hint.
_SERVER_BACKOFF_S = 5.0
_MAX_WAIT_S = 60.0
_sleep = asyncio.sleep  # tests replace it to see the waits without waiting
# the block of the first source; its header is "[C1]" or "[C1 (Điều 35, Khoản 1)]"
_FIRST_SOURCE = re.compile(r"^\[C1\b[^\]]*\]\n(.*?)(?=\n\n|\Z)", re.MULTILINE | re.DOTALL)


class LLMUnavailable(RuntimeError):
    """The provider failed after retries. The API turns this into a 503."""


class BudgetExceeded(RuntimeError):
    """More LLM calls than RunConfig.max_llm_calls. The loops check the budget
    before calling, so this should never fire - which is why it is an error."""


@dataclass
class LLMResponse:
    text: str
    tokens: int = 0
    cost_usd: float = 0.0
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

    Asked to plan queries, it splits the question on "và" - just enough to
    drive the corrective-retrieval path end to end without a model."""

    async def complete(self, system: str, user: str, **kw) -> LLMResponse:
        if '"queries"' in system:
            question = user.split("CÂU HỎI:", 1)[-1].split("\n", 1)[0]
            parts = [p.strip(" ?") for p in re.split(r"\s+và\s+|;", question) if p.strip(" ?")]
            text = json.dumps({"in_domain": True, "queries": parts}, ensure_ascii=False)
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
        self._transport = transport  # tests inject httpx.MockTransport

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
        data = await _post_json(
            self.url, body, self.headers, self.timeout, self.retries, self._transport
        )
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
        body = {**self._body(system, user, temperature, max_tokens), "stream": True}
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout, transport=self._transport) as client,
                client.stream("POST", self.url, json=body, headers=self.headers) as r,
            ):
                if r.status_code >= 400:
                    raise LLMUnavailable(f"{self.url} -> HTTP {r.status_code}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    for choice in json.loads(payload).get("choices") or []:
                        if delta := (choice.get("delta") or {}).get("content"):
                            yield delta
        except httpx.HTTPError as e:
            raise LLMUnavailable(f"{self.url} -> {type(e).__name__}: {e}") from e


class AnthropicClient:
    """POST /v1/messages."""

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float | None = None,
        retries: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        self.model = model
        self.timeout = timeout or settings.llm_timeout_s
        self.retries = settings.llm_max_retries if retries is None else retries
        self._transport = transport

    async def complete(
        self, system: str, user: str, *, temperature: float = 0.0, max_tokens: int = 512
    ) -> LLMResponse:
        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = await _post_json(
            ANTHROPIC_URL, body, self.headers, self.timeout, self.retries, self._transport
        )
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        usage = data.get("usage") or {}
        return _response(
            text,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            truncated=data.get("stop_reason") == "max_tokens",
        )

    async def stream(self, system: str, user: str, **kw) -> AsyncIterator[str]:
        # Answers are verified before anything is streamed (ADR-0003), so
        # token-level streaming from the provider is never on the answer path.
        yield (await self.complete(system, user, **kw)).text


class MeteredLLM:
    """Wraps the client for one question: enforces the call budget and adds up
    tokens and cost over every call - planner, generation, regeneration."""

    def __init__(self, client: LLMClient, max_calls: int) -> None:
        self.client = client
        self.max_calls = max_calls
        self.calls = 0
        self.tokens = 0
        self.cost_usd = 0.0

    @property
    def left(self) -> int:
        return self.max_calls - self.calls

    async def complete(self, system: str, user: str, **kw) -> LLMResponse:
        if self.left <= 0:
            raise BudgetExceeded(f"already made {self.max_calls} LLM calls for this question")
        self.calls += 1
        res = await self.client.complete(system, user, **kw)
        self.tokens += res.tokens
        self.cost_usd += res.cost_usd
        return res


async def _post_json(
    url: str,
    body: dict,
    headers: dict[str, str],
    timeout: float,
    retries: int,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """POST with retries on transient failures (timeouts, 429, 5xx). Anything
    else fails fast."""
    error = "no attempt made"
    wait = 0.0
    async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
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
    cost = (
        input_tokens * settings.llm_input_usd_per_mtok
        + output_tokens * settings.llm_output_usd_per_mtok
    ) / 1_000_000
    return LLMResponse(
        text=text.strip(),
        tokens=input_tokens + output_tokens,
        cost_usd=cost,
        truncated=truncated,
    )


@functools.lru_cache(maxsize=1)
def get_llm_client() -> LLMClient:
    provider = settings.llm_provider
    if provider == "mock":
        return MockClient()
    if provider == "anthropic":
        return AnthropicClient(settings.anthropic_api_key, settings.llm_model)
    base_url, key = {
        "ollama": (f"{settings.ollama_base_url.rstrip('/')}/v1", ""),
        "vllm": (settings.vllm_base_url, settings.vllm_api_key),
        "openai": (settings.openai_base_url, settings.openai_api_key),
        "gemini": (GEMINI_OPENAI_URL, settings.gemini_api_key),
    }[provider]
    return OpenAICompatClient(
        base_url, key, settings.llm_model, reasoning_effort=settings.llm_reasoning_effort
    )
