"""Parsing and validating the [C1] citation markers the prompt demands.

A citation pointing at a label that was never in the context is itself a
hallucination, and a cheap one to catch: no model has to run.
"""

from __future__ import annotations

import re

CITATION_RE = re.compile(r"\[(C\d+)\]")


def extract_citations(text: str) -> list[str]:
    """Citation labels in order of first appearance, de-duplicated."""
    seen: dict[str, None] = {}
    for label in CITATION_RE.findall(text):
        seen.setdefault(label, None)
    return list(seen)


def strip_citations(text: str) -> str:
    return re.sub(r"\s*\[(C\d+)\]", "", text).strip()


def invalid_citations(text: str, valid_labels: list[str]) -> list[str]:
    """Labels the model cited that were never given to it."""
    valid = set(valid_labels)
    return [c for c in extract_citations(text) if c not in valid]


def label_for(index: int) -> str:
    return f"C{index + 1}"


def finalize(text: str, valid_labels: list[str]) -> tuple[str, list[str]]:
    """The answer with every citation to an unknown label removed, and the
    labels left, in order. No label left means nothing in the answer is tied
    to a source - the caller refuses rather than show it."""
    for label in invalid_citations(text, valid_labels):
        text = re.sub(rf"\s*\[{label}\]", "", text)
    return text.strip(), extract_citations(text)
