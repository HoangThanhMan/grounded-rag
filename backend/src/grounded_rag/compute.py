"""Where the CPU-bound model calls run: off the event loop, a few at a time.

The embedder and the reranker are synchronous torch calls of up to seconds
each, and indexing an uploaded law embeds hundreds of chunks. Called straight
from an `async def` handler they hold the event loop, and every other
request - /healthz included - waits behind them.

Why not `asyncio.to_thread`: the default executor is shared with everything
else and sized for I/O, so N requests would run N forward passes at once,
each with torch's full set of intra-op threads, and oversubscribe the CPU.
Here `settings.model_workers` threads is the whole concurrency limit.

A stop-gap until the models move out of the API process: then this
becomes plain async I/O.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from grounded_rag.config import settings


@functools.lru_cache(maxsize=1)
def _pool() -> ThreadPoolExecutor:
    return ThreadPoolExecutor(settings.model_workers, thread_name_prefix="model")


async def run_model[**P, R](fn: Callable[P, R], *args: P.args, **kwargs: P.kwargs) -> R:
    """`fn(*args, **kwargs)` on the model pool. The context is copied, as
    `asyncio.to_thread` does, so trace spans opened inside still land in the
    request's own trace."""
    ctx = contextvars.copy_context()
    call = functools.partial(ctx.run, fn, *args, **kwargs)
    return await asyncio.get_running_loop().run_in_executor(_pool(), call)
