"""Claim verification with a self-hosted NLI model.

premise = the cited chunk, hypothesis = the claim, score = P(entailment).

Why NLI and not an LLM judge: see docs/adr/0001-nli-over-llm-judge.md.

The model is loaded lazily so that importing this module - which the unit
tests and the mock pipeline both do - never pulls a 600MB checkpoint.
"""

from __future__ import annotations

import functools
import hashlib
from typing import Protocol

from grounded_rag.config import settings


class Verifier(Protocol):
    def entailment(self, premise: str, hypothesis: str) -> float: ...


class MockVerifier:
    """Deterministic stand-in used by tests and by LLM_PROVIDER=mock.

    Scores on token overlap. Good enough to exercise the policy layer end to
    end; useless as a real signal, which is exactly why it is called Mock.
    """

    def entailment(self, premise: str, hypothesis: str) -> float:
        p = set(premise.lower().split())
        h = set(hypothesis.lower().split())
        if not h:
            return 0.0
        return len(p & h) / len(h)


class NLIVerifier:
    """The real thing. Requires the `models` extra."""

    def __init__(self, model_name: str | None = None) -> None:
        self.model_name = model_name or settings.nli_model
        self._pipe = None
        self._cache: dict[str, float] = {}

    def _load(self):
        if self._pipe is None:
            from transformers import pipeline  # imported late on purpose

            self._pipe = pipeline("text-classification", model=self.model_name, top_k=None)
        return self._pipe

    def entailment(self, premise: str, hypothesis: str) -> float:
        key = hashlib.sha256(f"{premise}||{hypothesis}".encode()).hexdigest()
        if key in self._cache:
            return self._cache[key]

        pipe = self._load()
        # Truncate the premise, never the claim: several cited chunks joined
        # together easily pass the model's 512-token limit.
        out = pipe({"text": premise, "text_pair": hypothesis}, truncation="only_first")
        # A single input comes back as a flat list of label scores in current
        # transformers, nested one level deeper in older ones.
        scores = out[0] if out and isinstance(out[0], list) else out
        value = next(
            (s["score"] for s in scores if s["label"].lower().startswith("entail")), 0.0
        )
        self._cache[key] = value
        return value


@functools.lru_cache(maxsize=1)
def get_verifier() -> Verifier:
    if settings.llm_provider == "mock":
        return MockVerifier()
    return NLIVerifier()
