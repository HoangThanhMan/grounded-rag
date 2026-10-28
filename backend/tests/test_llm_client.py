"""The provider client against httpx.MockTransport: the request each one sends,
the response each one parses, and how failures surface."""

import json

import httpx
import pytest
from pydantic import ValidationError

from grounded_rag.config import Settings
from grounded_rag.generation import llm_client
from grounded_rag.generation.llm_client import LLMUnavailable, OpenAICompatClient


@pytest.fixture(autouse=True)
def no_backoff(monkeypatch):
    monkeypatch.setattr(llm_client, "_BACKOFF_S", 0.0)
    monkeypatch.setattr(llm_client, "_SERVER_BACKOFF_S", 0.0)


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
async def test_stream_yields_the_deltas():
    sse = (
        'data: {"choices":[{"delta":{"content":"Phải "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"báo trước"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    client = _client(lambda r: httpx.Response(200, text=sse))
    assert "".join([t async for t in client.stream("s", "u")]) == "Phải báo trước"


@pytest.mark.asyncio
async def test_stream_retries_a_429_before_the_first_token():
    sse = (
        'data: {"choices":[{"delta":{"content":"Xin "}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"chào"}}]}\n\n'
        "data: [DONE]\n\n"
    )
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(429, headers={"retry-after": "0"})
        return httpx.Response(200, text=sse)

    client = _client(handler, retries=2)
    assert "".join([t async for t in client.stream("s", "u")]) == "Xin chào"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_stream_raises_unavailable_after_retries():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(LLMUnavailable, match="503"):
        _ = [t async for t in _client(handler, retries=2).stream("s", "u")]
    assert len(calls) == 3


@pytest.mark.asyncio
async def test_stream_does_not_retry_a_client_error():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(401, text="invalid key")

    with pytest.raises(LLMUnavailable, match="401"):
        _ = [t async for t in _client(handler, retries=2).stream("s", "u")]
    assert len(calls) == 1


def test_a_misspelt_provider_is_a_startup_error_not_a_silent_mock():
    with pytest.raises(ValidationError):
        Settings(llm_provider="antropic")


def test_a_dropped_provider_is_a_startup_error():
    # one OpenAI-compatible client now covers Gemini, Groq and Ollama
    with pytest.raises(ValidationError):
        Settings(llm_provider="gemini")


@pytest.mark.asyncio
async def test_calls_share_one_connection_pool_until_closed():
    client = _client(lambda request: httpx.Response(200, json=_reply()), retries=0)
    await client.complete("s", "u")
    pool = client._http.get()
    await client.complete("s", "u")
    assert client._http.get() is pool
    await client.aclose()
    assert pool.is_closed


@pytest.mark.asyncio
async def test_mock_condense_returns_the_question():
    from grounded_rag.generation.llm_client import MockClient
    from grounded_rag.generation.prompts import CONDENSE_SYSTEM_PROMPT, build_condense_prompt
    from grounded_rag.types import Turn

    history = [Turn(role="user", content="Nghỉ việc báo trước mấy ngày?"),
               Turn(role="assistant", content="Ít nhất 45 ngày [C1].")]
    prompt = build_condense_prompt(history, "Còn hợp đồng xác định thời hạn?")
    res = await MockClient().complete(CONDENSE_SYSTEM_PROMPT, prompt)
    assert res.text == "Còn hợp đồng xác định thời hạn?"


@pytest.mark.asyncio
async def test_a_stream_that_stops_without_finishing_is_unavailable():
    cut = 'data: {"choices":[{"delta":{"content":"Phải "}}]}\n\n'
    with pytest.raises(LLMUnavailable, match="ended before"):
        _ = [t async for t in _client(lambda r: httpx.Response(200, text=cut)).stream("s", "u")]


@pytest.mark.asyncio
async def test_a_finish_reason_without_done_is_a_finished_stream():
    sse = 'data: {"choices":[{"delta":{"content":"Xong"},"finish_reason":"stop"}]}\n\n'
    client = _client(lambda r: httpx.Response(200, text=sse))
    assert "".join([t async for t in client.stream("s", "u")]) == "Xong"


@pytest.mark.asyncio
async def test_a_stream_cut_at_max_tokens_is_logged(caplog):
    sse = ('data: {"choices":[{"delta":{"content":"Công dân"},"finish_reason":"length"}]}\n\n'
           "data: [DONE]\n\n")
    client = _client(lambda r: httpx.Response(200, text=sse))
    with caplog.at_level("WARNING"):
        _ = [t async for t in client.stream("s", "u")]
    assert "max_tokens" in caplog.text


@pytest.mark.asyncio
async def test_a_stream_reports_how_it_finished():
    sse = ('data: {"choices":[{"delta":{"content":"Công dân"},"finish_reason":"length"}]}\n\n'
           "data: [DONE]\n\n")
    stream = _client(lambda r: httpx.Response(200, text=sse)).stream("s", "u")
    _ = [t async for t in stream]
    assert stream.finish_reason == "length"


@pytest.mark.asyncio
async def test_garbage_from_the_provider_is_unavailable_not_a_crash():
    sse = 'data: {"choices": [oops\n\n'
    with pytest.raises(LLMUnavailable, match="unreadable"):
        _ = [t async for t in _client(lambda r: httpx.Response(200, text=sse)).stream("s", "u")]


@pytest.mark.asyncio
async def test_a_timeout_before_the_first_token_is_retried():
    sse = 'data: {"choices":[{"delta":{"content":"Xong"},"finish_reason":"stop"}]}\n\n'
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ReadTimeout("slow")
        return httpx.Response(200, text=sse)

    assert "".join([t async for t in _client(handler, retries=1).stream("s", "u")]) == "Xong"


@pytest.mark.asyncio
async def test_a_retry_starts_with_a_clean_finish_reason():
    """A first attempt that said "length" and then dropped must not make the
    retry look finished when it is cut off too."""
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(200, stream=_Broken(
                b'data: {"choices":[{"delta":{},"finish_reason":"length"}]}\n\n'))
        return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"A"}}]}\n\n')

    with pytest.raises(LLMUnavailable, match="ended before"):
        _ = [t async for t in _client(handler, retries=1).stream("s", "u")]


class _Broken(httpx.AsyncByteStream):
    """Sends one chunk, then the connection drops."""

    def __init__(self, first: bytes) -> None:
        self.first = first

    async def __aiter__(self):
        yield self.first
        raise httpx.ReadError("connection reset")
