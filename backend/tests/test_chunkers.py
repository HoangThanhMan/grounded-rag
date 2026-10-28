import re
from datetime import date

from grounded_rag.ingest.chunkers import recursive_chunk, structural_chunk
from grounded_rag.types import DocMeta

LEGAL = """Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động
1. Người lao động có quyền đơn phương chấm dứt hợp đồng lao động nhưng phải báo trước ít nhất 45 ngày.
2. Người lao động không phải báo trước trong một số trường hợp.

Điều 36. Quyền của người sử dụng lao động
1. Người sử dụng lao động có quyền đơn phương chấm dứt hợp đồng lao động.
"""

TWO_CHAPTERS = """Chương I
NHỮNG QUY ĐỊNH CHUNG

Điều 1. Phạm vi điều chỉnh
Bộ luật này quy định tiêu chuẩn lao động.

Chương II
VIỆC LÀM

Điều 9. Việc làm
1. Việc làm là hoạt động lao động tạo ra thu nhập.
"""


def test_structural_chunker_splits_on_clauses():
    chunks = structural_chunk(LEGAL, "bllđ")
    assert len(chunks) == 3
    assert chunks[0].article == "Điều 35"
    assert chunks[0].clause == "Khoản 1"
    assert "45 ngày" in chunks[0].text


def test_every_clause_carries_its_article_heading():
    # "không phải báo trước trong một số trường hợp" alone does not say what about
    second = structural_chunk(LEGAL, "bllđ")[1]
    assert second.text.startswith("Điều 35. Quyền đơn phương chấm dứt hợp đồng lao động\n2. ")


def test_ref_uses_the_same_format_as_gold_chunks():
    assert structural_chunk(LEGAL, "bllđ")[0].ref == "bllđ:Điều 35:1"


def test_chapter_heading_is_metadata_not_body_text():
    first, second = structural_chunk(TWO_CHAPTERS, "bllđ")
    assert (first.chapter, second.chapter) == ("Chương I", "Chương II")
    assert "VIỆC LÀM" not in first.text
    assert first.clause is None and first.ref == "bllđ:Điều 1"


def test_a_wrapped_line_that_mentions_an_article_is_not_a_new_article():
    text = "Điều 5. Áp dụng\n1. Trường hợp quy định tại\nĐiều 35 của Bộ luật này thì áp dụng.\n"
    chunks = structural_chunk(text, "d")
    assert len(chunks) == 1
    assert "Điều 35 của Bộ luật này" in chunks[0].text


def test_long_clause_pieces_all_keep_the_heading():
    text = "Điều 7. Tiêu đề\n1. " + "một câu dài về quyền lợi. " * 60
    chunks = structural_chunk(text, "d", max_chars=300)
    assert len(chunks) > 1
    assert all(c.text.startswith("Điều 7. Tiêu đề\n") and len(c.text) <= 300 for c in chunks)


def test_every_piece_of_a_long_list_repeats_the_clause_lead_in():
    # the shape of Điều 2 khoản 1 Luật BHXH 2024: a lead-in, then items a) .. n)
    items = "\n".join(
        f"{c}) Nhóm đối tượng số {i} với phần mô tả khá dài về điều kiện tham gia."
        for i, c in enumerate("abcdeghiklmn")
    )
    text = f"Điều 2. Đối tượng áp dụng\n1. Người lao động thuộc đối tượng bao gồm:\n{items}\n"
    chunks = structural_chunk(text, "d", max_chars=300)
    assert len(chunks) > 1
    for c in chunks:
        assert c.text.startswith("Điều 2. Đối tượng áp dụng\n1. Người lao động thuộc đối tượng bao gồm:\n")
        assert len(c.text) <= 300 and c.ref == "d:Điều 2:1"


def test_document_metadata_is_stamped_on_every_chunk():
    meta = DocMeta(title="Bộ luật Lao động 2019", effective_date=date(2021, 1, 1))
    for chunker in (structural_chunk, recursive_chunk):
        chunks = chunker(LEGAL, "bllđ", meta=meta)
        assert {(c.doc_title, c.effective_date) for c in chunks} == {
            ("Bộ luật Lao động 2019", date(2021, 1, 1))
        }


def test_chunk_ids_are_content_addressed_so_ingest_is_idempotent():
    first = structural_chunk(LEGAL, "bllđ")
    second = structural_chunk(LEGAL, "bllđ")
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_structural_falls_back_when_there_is_no_legal_structure():
    plain = "Một đoạn văn bình thường không có điều khoản nào cả."
    assert structural_chunk(plain, "doc")[0].article is None


def test_recursive_chunker_respects_the_size_budget():
    text = "câu. " * 500
    chunks = recursive_chunk(text, "doc", max_chars=200, overlap=0)
    assert len(chunks) > 1
    # no overlap means no overlap - not the whole previous piece again
    assert all(len(c.text) <= 200 for c in chunks)


def test_recursive_overlap_never_glues_two_words_into_one():
    # found on the real corpus: "...của người lao động" + "1. Người" -> "động1"
    text = "\n".join(f"Dòng số {i} nói về quyền của người lao động" for i in range(80))
    words = set(re.findall(r"\w+", text))
    chunks = recursive_chunk(text, "d", max_chars=200, overlap=50)
    assert len(chunks) > 1
    for c in chunks:
        assert set(re.findall(r"\w+", c.text)) <= words


VOLUNTARY = """Chương III
BẢO HIỂM XÃ HỘI BẮT BUỘC
Mục 1
CHẾ ĐỘ THAI SẢN
Điều 59. Trợ cấp thai sản
1. Trợ cấp thai sản một tháng bằng 100% mức bình quân tiền lương.

Chương VI
BẢO HIỂM XÃ HỘI TỰ NGUYỆN
Mục 1. TRỢ CẤP THAI SẢN
Điều 95. Trợ cấp thai sản
1. Mức trợ cấp thai sản là 2.000.000 đồng cho mỗi con.

Chương VII
ĐIỀU KHOẢN THI HÀNH
Điều 141. Hiệu lực thi hành
1. Luật này có hiệu lực từ ngày 01 tháng 7 năm 2025.
"""
BHXH = DocMeta(title="Luật Bảo hiểm xã hội 2024")


def test_every_clause_knows_the_law_chapter_and_section_it_sits_in():
    # Điều 95 alone reads like every worker's maternity pay; only its chapter
    # says it is the voluntary scheme's
    mandatory, voluntary, _ = structural_chunk(VOLUNTARY, "bhxh", meta=BHXH)
    assert mandatory.context == (
        "Luật Bảo hiểm xã hội 2024 › Chương III. Bảo hiểm xã hội bắt buộc"
        " › Mục 1. Chế độ thai sản"
    )
    assert voluntary.context == (
        "Luật Bảo hiểm xã hội 2024 › Chương VI. Bảo hiểm xã hội tự nguyện"
        " › Mục 1. Trợ cấp thai sản"
    )
    assert voluntary.text.startswith("Điều 95. Trợ cấp thai sản\n1. ")


def test_a_new_chapter_closes_the_section_before_it():
    last = structural_chunk(VOLUNTARY, "bhxh", meta=BHXH)[-1]
    assert last.context == "Luật Bảo hiểm xã hội 2024 › Chương VII. Điều khoản thi hành"


def test_retrieval_reads_the_context_before_the_clause():
    voluntary = structural_chunk(VOLUNTARY, "bhxh", meta=BHXH)[1]
    assert voluntary.search_text == f"{voluntary.context}\n{voluntary.text}"


def test_the_same_clause_under_another_chapter_is_another_chunk():
    moved = VOLUNTARY.replace("BẢO HIỂM XÃ HỘI TỰ NGUYỆN", "BẢO HIỂM XÃ HỘI KHÁC")
    before = structural_chunk(VOLUNTARY, "bhxh", meta=BHXH)[1]
    after = structural_chunk(moved, "bhxh", meta=BHXH)[1]
    assert before.text == after.text
    assert before.chunk_id != after.chunk_id


def test_naive_chunks_get_no_context():
    # the evaluation's baseline stays naive
    chunk = recursive_chunk(VOLUNTARY, "bhxh", meta=BHXH)[0]
    assert chunk.context is None
    assert chunk.search_text == chunk.text


def test_a_capitalised_title_keeps_its_proper_nouns():
    text = ("Mục 3\nNGƯỜI LAO ĐỘNG VIỆT NAM ĐI LÀM VIỆC Ở NƯỚC NGOÀI\n"
            "Điều 151. Điều kiện\n1. Có giấy phép lao động.\n")
    assert structural_chunk(text, "d")[0].context == (
        "Mục 3. Người lao động Việt Nam đi làm việc ở nước ngoài")
