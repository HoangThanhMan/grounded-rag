"""Where the CPU-bound model calls run: off the event loop, a few at a time,
the oldest request first.

The embedder, the reranker and the NLI model are synchronous torch calls of
up to seconds each. Called straight from an `async def` handler they hold the
event loop, and every other request - /healthz included - waits behind them.

Why not `asyncio.to_thread`: the default executor is shared with everything
else and sized for I/O, so N requests would run N forward passes at once,
each with torch's full set of intra-op threads, and oversubscribe the CPU.
Here `settings.model_workers` threads is the whole concurrency limit.

Why not a plain ThreadPoolExecutor: its queue is FIFO, and a request makes
several model calls (rerank, then verify) with LLM calls in between.
Requests arriving together then interleave - the first one's verify queues
behind everyone else's rerank - and all of them finish near the time the
last one would have. Ordered by the request's arrival, the oldest request's
next call goes first instead. Five concurrent /chat (rerank 1 s, LLM 0.3 s,
verify 0.5 s, one worker): mean latency 6.5 s FIFO, 5.0 s oldest-first; the
slowest request 7.5 s -> 7.8 s. Same total work, finished in a better order.

A stop-gap until the models move out of the API process: then this
becomes plain async I/O.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import itertools
import queue
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from grounded_rag.config import settings

_arrival: contextvars.ContextVar[float | None] = contextvars.ContextVar("arrival", default=None)


def mark_arrival() -> None:
    """Called once when a request starts. Every model call it makes from
    then on queues with this time as its priority."""
    _arrival.set(time.monotonic())


class _OldestFirstPool:
    def __init__(self, workers: int) -> None:
        self._queue: queue.PriorityQueue[tuple[float, int, Callable[[], Any], Future]] = (
            queue.PriorityQueue()
        )
        self._seq = itertools.count()     # FIFO among calls of the same request
        for i in range(workers):
            threading.Thread(target=self._work, name=f"model-{i}", daemon=True).start()

    def submit(self, priority: float, fn: Callable[[], Any]) -> Future:
        fut: Future = Future()
        self._queue.put((priority, next(self._seq), fn, fut))
        return fut

    def _work(self) -> None:
        while True:
            _, _, fn, fut = self._queue.get()
            # the request was cancelled (client gone) while this call waited
            if not fut.set_running_or_notify_cancel():
                continue
            try:
                fut.set_result(fn())
            except BaseException as e:  # re-raised in the task awaiting the future
                fut.set_exception(e)


@functools.lru_cache(maxsize=1)
def _pool() -> _OldestFirstPool:
    return _OldestFirstPool(settings.model_workers)


async def run_model[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """`fn(*args, **kwargs)` on the model pool. The context is copied, as
    `asyncio.to_thread` does, so trace spans opened inside still land in the
    request's own trace."""
    ctx = contextvars.copy_context()
    call = functools.partial(ctx.run, fn, *args, **kwargs)
    priority = _arrival.get() or time.monotonic()
    return await asyncio.wrap_future(_pool().submit(priority, call))
