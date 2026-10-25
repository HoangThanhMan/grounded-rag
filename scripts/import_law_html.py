"""Import a law from a full-text HTML page into the corpus Markdown.

    python scripts/import_law_html.py <url> luat_bao_hiem_xa_hoi_2014 --articles 125 \\
        --title "Luật Bảo hiểm xã hội 2014" --number 58/2014/QH13 \\
        --effective 2016-01-01 --expiry 2025-07-01

For a document whose only official PDF is a scan with no text layer (Luật Bảo
hiểm xã hội 2014 on datafiles.chinhphu.vn), prepare_corpus.py has nothing to
read. A third-party full-text page is the fallback, and a third-party copy can
drop or renumber text, so the same checks run here as there - every article
present and in order, clauses numbered 1..n - and the articles a question
depends on are compared against the official scan by hand (LABELING.md).

The text is the law as first published: amendments made later are not merged
in. Validity is per document, so a question may rely on this document only for
a provision no later act amended before `expiry`.
"""

from __future__ import annotations

import argparse
import html
import re
from datetime import date
from pathlib import Path

import httpx
import yaml

OUT_DIR = Path("data/corpus")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0"
ARTICLE = re.compile(r"^Điều (\d+)\.")
CLAUSE = re.compile(r"^(\d+)\. ")
# some sites render each chapter as a tab and each section as a toggle:
#   [tab title="Chương 3" ...]   [toggle title="Mục 2. CHẾ ĐỘ THAI SẢN" ...]
TAB_CHAPTER = re.compile(r"^\[tab title=\W*Chương (\d+)")
TOGGLE_SECTION = re.compile(r"^\[toggle title=\W*Mục (\d+)\. ([^”\"″]+)")
SHORTCODE = re.compile(r"^\[/?(tabs?|toggles?)\b")
ROMAN = [(10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]


def roman(n: int) -> str:
    out = ""
    for value, letters in ROMAN:
        while n >= value:
            out, n = out + letters, n - value
    return out


def page_lines(raw: str) -> list[str]:
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", raw, flags=re.S | re.I)
    text = re.sub(r"<br\s*/?>|</p>|</div>|</h\d>|</li>|</tr>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", text))
    lines = []
    for line in (re.sub(r"\s+", " ", raw_line).strip() for raw_line in text.split("\n")):
        if m := TAB_CHAPTER.match(line):
            lines.append(f"Chương {roman(int(m.group(1)))}")
        elif m := TOGGLE_SECTION.match(line):
            lines += [f"Mục {m.group(1)}", m.group(2).strip()]
        elif line and not SHORTCODE.match(line):
            lines.append(line)
    return lines


def law_body(lines: list[str], articles: int) -> list[str]:
    """From the first chapter heading to the end of the last article: the
    preamble, signature block and site chrome are not part of the law."""
    start = next(i for i, line in enumerate(lines) if re.match(r"^Chương I\b", line))
    last = max(i for i, line in enumerate(lines) if line.startswith(f"Điều {articles}."))
    end = last + 1
    while end < len(lines) and (CLAUSE.match(lines[end]) or re.match(r"^[a-zđ]\) ", lines[end])):
        end += 1
    return lines[start:end]


def check(body: list[str], articles: int) -> list[str]:
    problems = []
    seen = [int(m.group(1)) for line in body if (m := ARTICLE.match(line))]
    if seen != list(range(1, articles + 1)):
        problems.append(f"articles not 1..{articles} in order: {len(seen)} found")
    clause_no = 0
    for line in body:
        if ARTICLE.match(line):
            clause_no = 0
        elif m := CLAUSE.match(line):
            n = int(m.group(1))
            if n != clause_no + 1:
                problems.append(f"clause {n} after {clause_no}: {line[:60]}")
            clause_no = n
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("doc_id")
    ap.add_argument("--articles", type=int, required=True)
    ap.add_argument("--title", required=True)
    ap.add_argument("--number", required=True)
    ap.add_argument("--issued-by", default="Quốc hội")
    ap.add_argument("--effective", type=date.fromisoformat, required=True)
    ap.add_argument("--expiry", type=date.fromisoformat)
    ap.add_argument("--note", default="",
                    help="which articles were checked against the official copy, and how")
    args = ap.parse_args()

    raw = httpx.get(args.url, headers={"User-Agent": UA}, follow_redirects=True, timeout=60).text
    body = law_body(page_lines(raw), args.articles)
    problems = check(body, args.articles)
    if problems:
        raise SystemExit("not written:\n  " + "\n  ".join(problems[:20]))
    meta = {"title": args.title, "number": args.number, "issued_by": args.issued_by,
            "effective_date": args.effective, "expiry_date": args.expiry,
            "source": f"{args.url} (full text, third-party copy). {args.note}".strip()}
    out = OUT_DIR / f"{args.doc_id}.md"
    out.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
                   + "---\n" + "\n".join(body) + "\n", encoding="utf-8")
    print(f"{out}: {args.articles} articles, {len(body)} lines")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
