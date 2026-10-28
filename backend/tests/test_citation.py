import re

from grounded_rag.generation.citation import (
    extract_citations,
    invalid_citations,
    strip_citations,
)


def test_extract_in_order_without_duplicates():
    text = "Câu một [C1]. Câu hai [C3][C1]."
    assert extract_citations(text) == ["C1", "C3"]


def test_strip_removes_markers_and_spacing():
    assert strip_citations("Báo trước 45 ngày [C1].") == "Báo trước 45 ngày."


def test_citation_to_a_label_never_supplied_is_flagged():
    # the cheapest hallucination to catch: no model needed
    assert invalid_citations("A [C1]. B [C9].", ["C1", "C2"]) == ["C9"]


def test_no_citation_is_not_an_invalid_citation():
    assert invalid_citations("Không có trích dẫn.", ["C1"]) == []


def test_only_the_label_sits_inside_brackets():
    """A source header of "[C1 (Điều 105, Khoản 1)]", and later "[C1] Điều 105,
    Khoản 1", put an article number next to the label, and small models cited
    the article number. Every claim then came back uncited."""
    from grounded_rag.generation.prompts import build_user_prompt
    from grounded_rag.types import Chunk, RetrievedChunk

    src = RetrievedChunk(
        chunk=Chunk(chunk_id="x", doc_id="d", text="1. Không quá 08 giờ.",
                    article="Điều 105", clause="Khoản 1"),
        score=0.9, label="C1",
    )
    prompt = build_user_prompt("Bao nhiêu giờ?", [src])
    assert "[C1]\n1. Không quá 08 giờ." in prompt
    assert "Khoản 1" not in prompt
    # the only bracketed token in the documents block is the label itself
    documents = prompt.split("CÂU HỎI:")[0]
    assert extract_citations(documents) == ["C1"]
    assert re.findall(r"\[[^\]]*\]", documents) == ["[C1]"]
