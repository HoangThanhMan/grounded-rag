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
