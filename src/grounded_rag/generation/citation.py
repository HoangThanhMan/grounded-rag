"""Parsing and validating the [C1] citation markers the prompt demands.

A citation pointing at a label that was never in the context is itself a
hallucination, and a cheap one to catch - so it is caught here, before the
NLI guard ever runs.
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
