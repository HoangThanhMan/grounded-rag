"""Claim verification with a self-hosted NLI model.

premise = the cited chunk, hypothesis = the claim, score = P(entailment).

Why NLI and not an LLM judge: see docs/adr/0001-nli-over-llm-judge.md.

The model is loaded lazily so that importing this module - which the unit
tests and the mock pipeline both do - never pulls a 600MB checkpoint.
"""

from __future__ import annotations

import functools
import hashlib
import re
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


_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
_ITEM = re.compile(r"^\s*[a-zđ]\)\s")
# sentences, and the halves of a sentence joined by ";" - "không quá 60 ngày
# ...; trường hợp quá 60 ngày thì ..." states a rule and its exception
# ("1. Không ..." is a clause number, not the end of a sentence)
_SENTENCE = re.compile(r"(?<=[^\d\s]\.)\s+(?=[A-ZĐÀÁẢÃẠÂĂÊÔƠƯ])|(?<=;)\s+")


def numbers(text: str) -> set[str]:
    """Every number in the text, spelled the way the law and a model would
    agree on: "08" and "8" are the same number, "1.000" and "1000" too."""
    out = set()
    for raw in _NUMBER.findall(text):
        digits = raw.replace(".", "").replace(",", "")
        out.add(digits.lstrip("0") or "0")
    return out


def numbers_supported(premise: str, hypothesis: str) -> bool:
    """A claim that states a number the premise never mentions is not entailed,
    whatever the NLI model thinks: it scores "48 giờ" -> "40 giờ" at 0.72.
    The legal answer *is* the number, and this check costs nothing."""
    return numbers(hypothesis) <= numbers(premise)


def premise_views(premise: str) -> list[str]:
    """The premise whole, plus the parts a single claim usually restates.

    A clause is a heading, a lead-in and a list, or several sentences. A claim
    restates one item of it, and read against the whole clause the model
    scores a correct "tối đa 36 tháng" 0.46: the evidence is one line among
    unrelated ones. Each view keeps the article heading and the list's lead-in,
    so an item is never read without the subject and condition it belongs to.
    """
    lines = [line for line in premise.split("\n") if line.strip()]
    if len(lines) < 2:
        return [premise]
    head = lines[0] if lines[0].startswith("Điều ") else ""
    views = [premise]
    lead = ""
    for line in lines[1 if head else 0 :]:
        if _ITEM.match(line):
            views.append("\n".join(p for p in (head, lead, line) if p))
            continue
        lead = line if line.rstrip().endswith(":") else ""
        if lead:
            continue
        sentences = _SENTENCE.split(line)
        parts = sentences if len(sentences) > 1 else [line]
        views.extend("\n".join(p for p in (head, s) if p) for s in parts)
    return list(dict.fromkeys(views))


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
        """Best score over the premise's views, zero when a number is invented."""
        if not numbers_supported(premise, hypothesis):
            return 0.0
        return max(self.raw_entailment(view, hypothesis) for view in premise_views(premise))

    def raw_entailment(self, premise: str, hypothesis: str) -> float:
        """The model alone, on the premise as given."""
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
