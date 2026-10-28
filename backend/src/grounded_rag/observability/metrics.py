"""Prometheus metrics, when prometheus-client is installed (the `obs` extra).
Without it every function here is a no-op, so no caller has to care.

Scraped from GET /metrics. The questions they answer: which step is slow,
and how often - and why - the app refuses to answer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from grounded_rag.types import Answer

try:
    from prometheus_client import Counter, Histogram
except ImportError:  # pragma: no cover - optional dependency
    Counter = Histogram = None

if Histogram is not None:
    STEP_SECONDS = Histogram(
        "grounded_rag_step_seconds",
        "Latency of one pipeline step",
        ["step"],
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 4, 8, 16),
    )
    ANSWERS = Counter(
        "grounded_rag_answers_total",
        "Answers by status and abstain reason",
        ["status", "reason"],
    )
    ESCALATIONS = Counter(
        "grounded_rag_escalations_total",
        "Answers a stronger model was asked to redo, by how the second try ended",
        ["status"],
    )


def enabled() -> bool:
    return Histogram is not None


def observe_step(name: str, ms: int) -> None:
    if Histogram is not None:
        STEP_SECONDS.labels(step=name).observe(ms / 1000)


def observe_answer(answer: Answer) -> None:
    if Counter is None:
        return
    reason = str(answer.meta.abstain_reason) if answer.meta.abstain_reason else ""
    ANSWERS.labels(status=str(answer.status), reason=reason).inc()
    if answer.meta.escalated:
        ESCALATIONS.labels(status=str(answer.status)).inc()
