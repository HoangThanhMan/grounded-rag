"""Tracing. Every span is timed, logged at debug level, fed to Prometheus when
it is installed, and - inside `collect_steps()` - recorded so the answer can
carry its own trace in `meta.steps`. That trace is what makes the cost of the
corrective loop visible per question, in the API response and in eval reports.

With LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY set and the `obs` extra
installed, `export()` also sends each answer to Langfuse as one trace: a span
per step, a generation per LLM call, the guard's verdicts as scores. Export is
best effort - tracing that can fail a request is worse than no tracing.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from grounded_rag.config import settings
from grounded_rag.observability import metrics
from grounded_rag.types import Answer, Step, Verdict

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
    wall = datetime.now(UTC)
    started = time.perf_counter()
    try:
        yield detail
    finally:
        ms = int((time.perf_counter() - started) * 1000)
        steps = _steps.get()
        if steps is not None:
            steps.append(Step(name=name, ms=ms, detail=detail, started=wall))
        metrics.observe_step(name, ms)
        log.debug("span=%s ms=%d %s", name, ms, detail)


_client: Any = None


def langfuse_client() -> Any:
    """The Langfuse client, or None when tracing is not configured. Built once."""
    global _client
    if _client is None:
        if not (settings.langfuse_public_key and settings.langfuse_secret_key):
            _client = False
        else:
            try:
                from langfuse import Langfuse  # the `obs` extra, v2 SDK
            except ImportError:
                log.warning("LANGFUSE_* is set but the `obs` extra is not installed")
                _client = False
            else:
                _client = Langfuse(
                    public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key,
                    host=settings.langfuse_host,
                )
    return _client or None


def export(question: str, answer: Answer, client: Any = None) -> str | None:
    """Send one answered question to Langfuse. Returns the trace id, or None
    when tracing is off or the export failed."""
    client = client or langfuse_client()
    if client is None:
        return None
    try:
        return _export(client, question, answer)
    except Exception:  # noqa: BLE001 - never let tracing break an answer
        log.warning("langfuse export failed", exc_info=True)
        return None


def _export(client: Any, question: str, answer: Answer) -> str:
    meta = answer.meta
    first = next((s.started for s in meta.steps if s.started), None)
    trace = client.trace(
        name="answer",
        input={"question": question},
        output={"answer": answer.answer, "status": answer.status},
        metadata={
            "config": meta.config,
            "abstain_reason": meta.abstain_reason,
            "regenerated": meta.regenerated,
            "llm_calls": meta.llm_calls,
            "latency_ms": meta.latency_ms,
            "sources": [s.chunk.ref for s in answer.sources],
        },
        tags=[meta.config, str(answer.status)],
        timestamp=first,
    )
    for step in meta.steps:
        start = step.started or first
        end = start + timedelta(milliseconds=step.ms) if start else None
        if step.name == "generate":
            trace.generation(
                name="generate", start_time=start, end_time=end, metadata=step.detail,
                model=settings.llm_model,
                usage={"total": step.detail.get("tokens", 0)},
            )
        else:
            trace.span(name=step.name, start_time=start, end_time=end, metadata=step.detail)
    verified = [c for c in answer.claims if c.verdict is not None]
    if verified:
        supported = sum(c.verdict is Verdict.SUPPORTED for c in verified)
        trace.score(name="claims_supported", value=supported / len(verified),
                    comment=f"{supported}/{len(verified)} claims")
    for i, claim in enumerate(verified):
        trace.score(name="entailment", value=claim.entailment or 0.0,
                    comment=f"claim {i + 1} [{claim.verdict}] {claim.text[:200]}")
    return trace.id
