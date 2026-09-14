"""Tracing. Every span is timed, logged at debug level, fed to Prometheus when
it is installed, and - inside `collect_steps()` - recorded so the answer can
carry its own trace in `meta.steps`. That trace is what makes the cost of the
corrective loop visible per question, in the API response and in eval reports.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
from collections.abc import Iterator
from typing import Any

from grounded_rag.observability import metrics
from grounded_rag.types import Step

log = logging.getLogger("grounded_rag.trace")

_steps: contextvars.ContextVar[list[Step] | None] = contextvars.ContextVar("steps", default=None)


@contextlib.contextmanager
def collect_steps() -> Iterator[list[Step]]:
    steps: list[Step] = []
    token = _steps.set(steps)
    try:
        yield steps
    finally:
        _steps.reset(token)


@contextlib.contextmanager
def trace(name: str, **attrs: Any) -> Iterator[dict[str, Any]]:
    """Yields the span's detail dict, so the body can record what it found -
    scores, token counts - once it knows."""
    detail = dict(attrs)
    started = time.perf_counter()
    try:
        yield detail
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        steps = _steps.get()
        if steps is not None:
            steps.append(Step(name=name, ms=ms, detail=detail))
        metrics.observe_step(name, ms)
        log.debug("span=%s ms=%d %s", name, ms, detail)
        # TODO(week3): forward to Langfuse when settings.langfuse_secret_key is set.
