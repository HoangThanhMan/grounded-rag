"""Provider clients against httpx.MockTransport: the request each one sends,
the response each one parses, and how failures surface."""

import json

import httpx
import pytest
from pydantic import ValidationError

from grounded_rag.config import Settings
from grounded_rag.generation import llm_client
from grounded_rag.generation.llm_client import (
    AnthropicClient,
    BudgetExceeded,
    LLMResponse,
    LLMUnavailable,
    MeteredLLM,
    OpenAICompatClient,
)


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(llm_client, "_BACKOFF_S", 0.0)


def _reply(text="Phải báo trước 45 ngày [C1].", prompt_tokens=100, completion_tokens=12):
    return {
        "choices": [{"message": {"role": "assistant", "content": text}}],
        "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens},
    }


def _client(handler, **kw) -> OpenAICompatClient:
    return OpenAICompatClient(
        "http://vllm:8000/v1/", "key", "qwen", transport=httpx.MockTransport(handler), **kw
    )


@pytest.mark.asyncio
async def test_openai_compatible_request_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(url=str(request.url), auth=request.headers["authorization"],
                    body=json.loads(request.content))
        return httpx.Response(200, json=_reply())

    res = await _client(handler, retries=0).complete("sys", "user", max_tokens=64)
    assert seen["url"] == "http://vllm:8000/v1/chat/completions"
    assert seen["auth"] == "Bearer key"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["body"]["max_tokens"] == 64
    assert (res.text, res.tokens) == ("Phải báo trước 45 ngày [C1].", 112)


@pytest.mark.asyncio
async def test_a_cut_off_answer_is_flagged_not_passed_off_as_complete():
    reply = _reply(text="Công dân Việt Nam từ đủ 75 tuổi trở lên và đáp ứng các điều")
    reply["choices"][0]["finish_reason"] = "length"
    res = await _client(lambda r: httpx.Response(200, json=reply)).complete("s", "u")
    assert res.truncated
    done = _reply()
    done["choices"][0]["finish_reason"] = "stop"
    finished = await _client(lambda r: httpx.Response(200, json=done)).complete("s", "u")
    assert not finished.truncated


@pytest.mark.asyncio
async def test_reasoning_effort_is_sent_only_when_configured():
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=_reply())

    await _client(handler).complete("s", "u")
    await OpenAICompatClient(
        "http://x/v1", "", "m", reasoning_effort="none", transport=httpx.MockTransport(handler)
    ).complete("s", "u")
    assert "reasoning_effort" not in bodies[0]
    assert bodies[1]["reasoning_effort"] == "none"


@pytest.mark.asyncio
async def test_transient_failures_are_retried():
    replies = iter([httpx.Response(503), httpx.Response(429), httpx.Response(200, json=_reply())])
    res = await _client(lambda r: next(replies), retries=2).complete("s", "u")
    assert res.text


@pytest.mark.asyncio
async def test_a_rate_limit_waits_as_long_as_the_server_asks(monkeypatch):
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(llm_client, "_sleep", fake_sleep)
    gemini_429 = {"error": {"code": 429, "details": [{"retryDelay": "17s"}]}}
    replies = iter([
        httpx.Response(429, json=gemini_429),
        httpx.Response(429, headers={"Retry-After": "3"}),
        httpx.Response(200, json=_reply()),
    ])
    await _client(lambda r: next(replies), retries=2).complete("s", "u")
    assert waits == [17.0, 3.0]


@pytest.mark.asyncio
async def test_a_client_error_fails_fast():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="invalid key")

    with pytest.raises(LLMUnavailable, match="401"):
        await _client(handler, retries=3).complete("s", "u")
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_connection_errors_surface_as_unavailable():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(LLMUnavailable, match="ConnectError"):
        await _client(handler, retries=1).complete("s", "u")


@pytest.mark.asyncio
async def test_cost_comes_from_token_prices(monkeypatch):
    monkeypatch.setattr(llm_client.settings, "llm_input_usd_per_mtok", 1.0)
    monkeypatch.setattr(llm_client.settings, "llm_output_usd_per_mtok", 4.0)
    reply = _reply(prompt_tokens=1000, completion_tokens=500)
    res = await _client(lambda r: httpx.Response(200, json=reply)).complete("s", "u")
    assert res.cost_usd == pytest.approx((1000 * 1.0 + 500 * 4.0) / 1_000_000)


@pytest.mark.asyncio
async def test_stream_yields_the_deltas():
    sse = (
        'data: {"choices":[{"delta":{"content":"Phải "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"báo trước"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    client = _client(lambda r: httpx.Response(200, text=sse))
    assert "".join([t async for t in client.stream("s", "u")]) == "Phải báo trước"


@pytest.mark.asyncio
async def test_anthropic_messages_request_and_response():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(key=request.headers["x-api-key"], body=json.loads(request.content))
        return httpx.Response(200, json={
            "content": [{"type": "text", "text": "Có [C1]."}],
            "usage": {"input_tokens": 50, "output_tokens": 5},
        })

    client = AnthropicClient("key", "model", transport=httpx.MockTransport(handler), retries=0)
    res = await client.complete("sys", "user")
    assert seen["key"] == "key"
    assert seen["body"]["system"] == "sys"
    assert seen["body"]["messages"] == [{"role": "user", "content": "user"}]
    assert (res.text, res.tokens) == ("Có [C1].", 55)


@pytest.mark.asyncio
async def test_the_call_budget_is_a_hard_ceiling():
    class Echo:
        async def complete(self, system, user, **kw):
            return LLMResponse(text="x", tokens=3, cost_usd=0.01)

    llm = MeteredLLM(Echo(), 2)
    await llm.complete("s", "u")
    await llm.complete("s", "u")
    assert (llm.calls, llm.tokens, llm.left) == (2, 6, 0)
    with pytest.raises(BudgetExceeded):
        await llm.complete("s", "u")


def test_a_misspelt_provider_is_a_startup_error_not_a_silent_mock():
    with pytest.raises(ValidationError):
        Settings(llm_provider="antropic")
