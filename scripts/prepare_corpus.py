"""Download the corpus from the official gazette (Công báo) and turn it into
the Markdown the structural chunker expects.

    python scripts/prepare_corpus.py            # -> data/corpus/*.md

Công báo PDFs have a text layer, but it is laid out for print: every line is
hard-wrapped, and every page repeats a "CÔNG BÁO/Số ..." header and a page
number - often in the middle of a clause. This script undoes that, then checks
the result (every article present, clauses numbered 1..n) before writing it.
Needs the `models` extra (pymupdf).
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

import httpx
import yaml

RAW_DIR = Path(".cache/corpus_raw")
OUT_DIR = Path("data/corpus")
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)

# The original texts as published. Later amendments are not merged in.
DOCUMENTS = {
    "bo_luat_lao_dong_2019": {
        "url": "https://congbaocdn.chinhphu.vn/CongBaoCP/VanBan/2019/11/30232/"
        "29070-1-2019993-99445-2019-qh14.pdf",
        "articles": 220,
        "meta": {
            "title": "Bộ luật Lao động 2019",
            "number": "45/2019/QH14",
            "issued_by": "Quốc hội",
            "effective_date": date(2021, 1, 1),
            "source": "Công báo số 993 + 994, ngày 26-12-2019",
        },
    },
    "luat_bao_hiem_xa_hoi_2024": {
        "url": "https://datafiles.chinhphu.vn/cpp/files/vbpq/2024/9/41-2024-qh15.pdf",
        "articles": 141,
        "meta": {
            "title": "Luật Bảo hiểm xã hội 2024",
            "number": "41/2024/QH15",
            "issued_by": "Quốc hội",
            "effective_date": date(2025, 7, 1),
            "source": "Công báo số 987 + 988, ngày 25-8-2024",
        },
    },
}

_DROP = [
    re.compile(r"^CÔNG BÁO/Số\b"),                                # running header
    re.compile(r"^\d{1,3}$"),                                     # page number
    re.compile(r"^(Người ký|Email|Cơ quan|Thời gian ký)\s*:"),     # e-signature stamp
]
HEADING = re.compile(r"^(Chương\s+[IVXLC]+|Mục\s+\d+)\b")
ARTICLE = re.compile(r"^Điều\s+\d+[a-z]?\.")
CLAUSE = re.compile(r"^\d{1,2}\.\s")
POINT = re.compile(r"^[a-zđ]\)\s")
# the closing formula, followed only by the signature
ADOPTED = re.compile(r"^(Bộ luật|Luật) này (đã )?được Quốc hội\b")


def download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    r = httpx.get(url, headers={"User-Agent": UA}, follow_redirects=True, timeout=120)
    r.raise_for_status()
    if not r.content.startswith(b"%PDF"):
        raise SystemExit(f"{url} did not return a PDF ({r.headers.get('content-type')})")
    dest.write_bytes(r.content)
    return dest


def extract(pdf: Path) -> str:
    import pymupdf

    with pymupdf.open(pdf) as doc:
        return "\n".join(page.get_text() for page in doc)


def clean(raw: str) -> str:
    """Print layout -> one logical line per heading, article, clause or point."""
    lines = [" ".join(line.split()) for line in raw.splitlines()]
    lines = [ln for ln in lines if ln and not any(p.match(ln) for p in _DROP)]
    start = next(i for i, ln in enumerate(lines) if HEADING.match(ln) or ARTICLE.match(ln))
    end = next((i for i, ln in enumerate(lines) if ADOPTED.match(ln)), len(lines))

    out: list[str] = []
    kind = ""  # what the line being built is: heading | title | article | body
    for line in lines[start:end]:
        if HEADING.match(line):
            out.append(line)
            kind = "heading"
        elif kind in ("heading", "title") and _all_caps(line):
            # a chapter or section title, possibly wrapped over several lines
            if kind == "heading":
                out.append(line)
            else:
                out[-1] += f" {line}"
            kind = "title"
        elif ARTICLE.match(line) or CLAUSE.match(line) or POINT.match(line):
            out.append(line)
            kind = "article" if ARTICLE.match(line) else "body"
        elif kind == "article" and not line[0].islower():
            # An article title wraps mid-phrase, so its continuation starts in
            # lower case. An upper-case line is the article's first paragraph.
            out.append(line)
            kind = "body"
        elif out and kind not in ("heading", "title"):
            out[-1] += f" {line}"
        else:
            out.append(line)
            kind = "body"
    return "\n".join(out) + "\n"


def check(text: str, expected_articles: int) -> list[str]:
    """Every article once, clauses numbered 1..n inside each article."""
    problems: list[str] = []
    seen: list[int] = []
    clauses: dict[int, list[int]] = {}
    for line in text.splitlines():
        if m := re.match(r"^Điều (\d+)\.", line):
            seen.append(int(m.group(1)))
            clauses[seen[-1]] = []
        elif (m := CLAUSE.match(line)) and seen:
            clauses[seen[-1]].append(int(m.group(0).split(".")[0]))
    missing = sorted(set(range(1, expected_articles + 1)) - set(seen))
    if missing:
        problems.append(f"missing articles: {missing}")
    if len(seen) != len(set(seen)):
        problems.append(f"duplicated articles: {sorted({n for n in seen if seen.count(n) > 1})}")
    for article, nums in clauses.items():
        if nums and nums != list(range(1, len(nums) + 1)):
            problems.append(f"Điều {article}: clause numbers {nums}")
    return problems


def _all_caps(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def main() -> None:
    from grounded_rag.ingest.chunkers import recursive_chunk, structural_chunk

    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", default=None, help="doc ids to rebuild")
    args = ap.parse_args()

    failed = False
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for doc_id, spec in DOCUMENTS.items():
        if args.only and doc_id not in args.only:
            continue
        pdf = download(spec["url"], RAW_DIR / f"{doc_id}.pdf")
        text = clean(extract(pdf))
        problems = check(text, spec["articles"])
        front = yaml.safe_dump(spec["meta"], allow_unicode=True, sort_keys=False)
        out = OUT_DIR / f"{doc_id}.md"
        out.write_text(f"---\n{front}---\n{text}", encoding="utf-8")

        structural = structural_chunk(text, doc_id)
        print(
            f"{out}: {len(text):,} chars, {spec['articles']} articles expected, "
            f"{len(structural)} structural chunks (longest {max(len(c.text) for c in structural)} "
            f"chars), {len(recursive_chunk(text, doc_id))} recursive chunks"
        )
        for p in problems:
            print(f"  ! {p}")
        failed |= any(p.startswith("missing") for p in problems)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
