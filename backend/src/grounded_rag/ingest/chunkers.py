"""Chunking strategies.

Two of them, because the evaluation compares them:
  recursive  - generic, splits on paragraph/sentence boundaries at a size budget
  structural - splits Vietnamese legal text on Điều / Khoản boundaries, so a
               citation lands on a real clause instead of an arbitrary window

Structural chunks are heading-aware: each one starts with its article heading
("Điều 35. Quyền đơn phương chấm dứt ..."). A clause that on its own says only
"phải báo trước ít nhất 45 ngày" still carries what it is about - for the
retriever, and for the model reading it as a source. Above the article, its
`context` names the law, chapter and section: Điều 95 of the 2024 social
insurance law pays 2,000,000 đồng per child, but only under "Chương VI. Bảo
hiểm xã hội tự nguyện".
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from grounded_rag.types import Chunk, DocMeta

# The title follows on the same line ("Mục 1. CHẾ ĐỘ HƯU TRÍ") or the next
CHAPTER_RE = re.compile(r"^\s*(?:Chương|CHƯƠNG)\s+([IVXLCDM]+|\d+)\b[\s.:-]*(.*)$")
SECTION_RE = re.compile(r"^\s*(?:Mục|MỤC)\s+(\d+)\b[\s.:-]*(.*)$")
# The '.' or ':' is required: a wrapped line that happens to start with
# "Điều 35 của Bộ luật này" is body text, not a new article.
ARTICLE_RE = re.compile(r"^\s*(Điều\s+\d+[a-z]?)\s*[.:]\s*(.*)$")
CLAUSE_RE = re.compile(r"^\s*(\d+)\.\s+", re.MULTILINE)
SEPARATORS = ["\n\n", "\n", ". ", " "]
# what lower-casing a capitalised title must not lower-case
PROPER_NOUNS = ["Việt Nam"]


def _chunk_id(doc_id: str, text: str) -> str:
    """Content-addressed, so re-ingesting the same document is idempotent."""
    digest = hashlib.sha256(f"{doc_id}::{text}".encode()).hexdigest()[:16]
    return f"{doc_id}:{digest}"


def _make(doc_id: str, text: str, meta: DocMeta, **structure: str | None) -> Chunk:
    # the context is part of what is embedded, so it is part of the id
    context = structure.get("context")
    return Chunk(
        chunk_id=_chunk_id(doc_id, f"{context}\n{text}" if context else text),
        doc_id=doc_id,
        text=text,
        doc_title=meta.title,
        effective_date=meta.effective_date,
        expiry_date=meta.expiry_date,
        **structure,
    )


def recursive_chunk(
    text: str,
    doc_id: str,
    *,
    meta: DocMeta | None = None,
    max_chars: int = 1200,
    overlap: int = 150,
) -> list[Chunk]:
    meta = meta or DocMeta()
    pieces = _split_recursive(text.strip(), max_chars, SEPARATORS)
    chunks: list[Chunk] = []
    for i, piece in enumerate(pieces):
        # The separator the split consumed has to come back: gluing the overlap
        # straight on turned "...người lao động" + "1. Người" into "động1".
        tail = _tail(pieces[i - 1], overlap) if i else ""
        body = f"{tail}\n{piece}".strip() if tail else piece.strip()
        if body:
            chunks.append(_make(doc_id, body, meta))
    return chunks


def _tail(text: str, n: int) -> str:
    """The last n characters, starting on a word boundary. n=0 means none -
    unlike text[-0:], which is the whole string."""
    if n <= 0:
        return ""
    if len(text) <= n:
        return text
    tail = text[-n:]
    return tail.split(" ", 1)[1] if " " in tail else tail


def _split_recursive(text: str, max_chars: int, seps: list[str]) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    if not seps:
        return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]

    sep, rest = seps[0], seps[1:]
    out: list[str] = []
    buf = ""
    for part in text.split(sep):
        candidate = f"{buf}{sep}{part}" if buf else part
        if len(candidate) <= max_chars:
            buf = candidate
        else:
            if buf:
                out.append(buf)
            buf = part if len(part) <= max_chars else ""
            if not buf:
                out.extend(_split_recursive(part, max_chars, rest))
    if buf:
        out.append(buf)
    return [p for p in out if p.strip()]


def structural_chunk(
    text: str, doc_id: str, *, meta: DocMeta | None = None, max_chars: int = 1800
) -> list[Chunk]:
    """One chunk per clause (Khoản), falling back to one per article (Điều)."""
    meta = meta or DocMeta()
    chunks: list[Chunk] = []
    for art in _parse_articles(text):
        heading = f"{art.label}. {art.title}" if art.title else art.label
        budget = max(max_chars - len(heading) - 1, 200)
        for clause_no, clause_text in _split_clauses(art.body):
            if not clause_text:
                continue
            body = f"{clause_no}. {clause_text}" if clause_no else clause_text
            # A very long clause still has to fit the context window. Every
            # piece keeps the heading, so none of them loses its subject.
            for piece in _pieces(body, budget):
                chunks.append(
                    _make(
                        doc_id,
                        f"{heading}\n{piece}",
                        meta,
                        article=art.label,
                        clause=f"Khoản {clause_no}" if clause_no else None,
                        chapter=art.chapter,
                        context=" › ".join(p for p in (meta.title, *art.headings) if p),
                    )
                )
    # no legal structure found - fall back rather than return nothing
    return chunks or recursive_chunk(text, doc_id, meta=meta)


def _pieces(body: str, budget: int) -> list[str]:
    """A clause that fits is one piece. A longer one is cut on line boundaries,
    and when it is a list, every piece repeats the clause's lead-in ("1. Người
    lao động ... bao gồm:"), so item i) never loses what it is an item of."""
    if len(body) <= budget:
        return [body]
    lead, _, rest = body.partition("\n")
    if not rest or not lead.endswith(":") or len(lead) > budget // 2:
        return _split_recursive(body, budget, SEPARATORS)
    return [f"{lead}\n{p}" for p in _split_recursive(rest, budget - len(lead) - 1, SEPARATORS)]


@dataclass
class _Article:
    label: str                      # "Điều 35"
    title: str                      # "Quyền đơn phương chấm dứt ..."
    chapter: str | None             # "Chương III"
    headings: tuple[str, ...] = ()  # ("Chương III. Hợp đồng lao động", "Mục 1. ...")
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()


def _parse_articles(text: str) -> list[_Article]:
    """Line by line, so chapter and section headings close the article before
    them instead of leaking into its last clause."""
    articles: list[_Article] = []
    chapter: str | None = None
    # [chapter heading, section heading]; a heading whose title is on the
    # next line waits for it there
    headings: list[str] = []
    titled = True
    current: _Article | None = None
    for line in text.splitlines():
        if m := CHAPTER_RE.match(line):
            chapter, current = f"Chương {m.group(1)}", None
            headings, titled = [_heading(chapter, m.group(2))], bool(m.group(2).strip())
        elif m := SECTION_RE.match(line):
            current = None
            headings = [*headings[:1], _heading(f"Mục {m.group(1)}", m.group(2))]
            titled = bool(m.group(2).strip())
        elif m := ARTICLE_RE.match(line):
            current = _Article(m.group(1), m.group(2).strip(), chapter, tuple(headings))
            articles.append(current)
            titled = True
        elif not titled and line.strip():
            headings[-1] = _heading(headings[-1], line)
            titled = True
        elif current is not None:
            current.lines.append(line)
    return articles


def _heading(label: str, title: str) -> str:
    """ "Chương VI" + "BẢO HIỂM XÃ HỘI TỰ NGUYỆN" -> "Chương VI. Bảo hiểm xã hội
    tự nguyện". The gazette sets titles in capitals; read in a sentence, they
    shout."""
    title = title.strip()
    if title.isupper():
        title = title.capitalize()
        for name in PROPER_NOUNS:
            title = re.sub(rf"\b{name}\b", name, title, flags=re.IGNORECASE)
    return f"{label}. {title}" if title else label


def _split_clauses(body: str) -> list[tuple[str | None, str]]:
    marks = list(CLAUSE_RE.finditer(body))
    if not marks:
        return [(None, body)]
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        out.append((m.group(1), body[m.end() : end].strip()))
    return out


def get_chunker(name: str):
    return {"recursive": recursive_chunk, "structural": structural_chunk}[name]
