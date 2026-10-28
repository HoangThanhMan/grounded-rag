"""The model pool: the oldest request's call goes first, and errors reach
the request that made the call."""

import threading

import pytest

from grounded_rag.compute import _OldestFirstPool, run_model


def test_queued_calls_run_oldest_request_first():
    pool = _OldestFirstPool(1)
    gate = threading.Event()
    order: list[str] = []
    busy = pool.submit(0.0, gate.wait)          # the one worker is busy
    done = [
        pool.submit(arrival, lambda name=name: order.append(name))
        for arrival, name in [(3.0, "late"), (1.0, "first"), (2.0, "second"), (1.0, "first-again")]
    ]
    gate.set()
    busy.result(timeout=2)
    for f in done:
        f.result(timeout=2)
    # by arrival; the same request's calls keep the order they were made in
    assert order == ["first", "first-again", "second", "late"]


@pytest.mark.asyncio
async def test_an_error_in_a_model_call_is_raised_in_the_request():
    def broken():
        raise ValueError("bad input")

    with pytest.raises(ValueError, match="bad input"):
        await run_model(broken)
