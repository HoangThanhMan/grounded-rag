"""Prometheus metrics, when prometheus-client is installed (the `obs` extra).
Without it every function here is a no-op, so no caller has to care.

Scraped from GET /metrics. The questions they answer: which step is slow,
how many LLM calls and tokens a configuration costs, and which layer of
defence is doing the refusing.
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
        "Answers by config, status and abstain reason",
        ["config", "status", "reason"],
    )
    LLM_TOKENS = Counter("grounded_rag_llm_tokens_total", "LLM tokens consumed", ["config"])
    LLM_CALLS = Counter("grounded_rag_llm_calls_total", "LLM calls made", ["config"])


def enabled() -> bool:
    return Histogram is not None


def observe_step(name: str, ms: int) -> None:
    if Histogram is not None:
        STEP_SECONDS.labels(step=name).observe(ms / 1000)


def observe_answer(answer: Answer) -> None:
    if Counter is None:
        return
    m = answer.meta
    reason = str(m.abstain_reason) if m.abstain_reason else ""
    ANSWERS.labels(config=m.config, status=str(answer.status), reason=reason).inc()
    LLM_TOKENS.labels(config=m.config).inc(m.tokens)
    LLM_CALLS.labels(config=m.config).inc(m.llm_calls)
