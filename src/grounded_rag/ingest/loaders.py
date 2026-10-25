"""Readers for the corpus. PDF and Markdown only, on purpose: that is the form
legal texts are published in, and every other format is out of scope.

Document metadata - title, number, issuing body, validity dates - comes from
YAML front matter at the top of a .md/.txt file, or from a sidecar
`<name>.meta.yaml` next to a PDF:

    ---
    title: Bộ luật Lao động 2019
    number: 45/2019/QH14
    issued_by: Quốc hội
    effective_date: 2021-01-01
    ---
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from grounded_rag.types import DocMeta

SUPPORTED = {".md", ".txt", ".pdf"}


@dataclass
class Document:
    doc_id: str                     # the filename stem
    text: str
    meta: DocMeta = field(default_factory=DocMeta)


def load_file(path: Path) -> Document:
    if path.suffix.lower() == ".pdf":
        text, meta = _load_pdf(path), _sidecar(path)
    else:
        text, meta = split_front_matter(path.read_text(encoding="utf-8"))
    return Document(doc_id=path.stem, text=text, meta=DocMeta.model_validate(meta))


def split_front_matter(raw: str) -> tuple[str, dict[str, Any]]:
    """(body, metadata). Text without front matter comes back unchanged."""
    if not raw.startswith("---"):
        return raw, {}
    head, sep, body = raw[3:].partition("\n---")
    if not sep:
        return raw, {}
    meta = yaml.safe_load(head)
    return body.lstrip("\n"), meta if isinstance(meta, dict) else {}


def _sidecar(path: Path) -> dict[str, Any]:
    meta_path = path.with_name(f"{path.stem}.meta.yaml")
    if not meta_path.exists():
        return {}
    meta = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    return meta if isinstance(meta, dict) else {}


def _load_pdf(path: Path) -> str:
    import pymupdf  # from the `models` extra

    with pymupdf.open(path) as doc:
        return "\n\n".join(page.get_text() for page in doc)


def iter_corpus(root: Path):
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in SUPPORTED:
            yield p
