from datetime import date
from pathlib import Path

from grounded_rag.ingest.loaders import load_file, split_front_matter


def test_front_matter_becomes_document_metadata(tmp_path):
    path = tmp_path / "luat_x.md"
    path.write_text(
        "---\ntitle: Luật X\neffective_date: 2021-01-01\nexpiry_date: 2025-07-01\n---\n"
        "Điều 1. Phạm vi\nNội dung.\n",
        encoding="utf-8",
    )
    doc = load_file(path)
    assert doc.doc_id == "luat_x"
    assert doc.meta.title == "Luật X"
    assert (doc.meta.effective_date, doc.meta.expiry_date) == (date(2021, 1, 1), date(2025, 7, 1))
    assert doc.text.startswith("Điều 1.")


def test_text_without_front_matter_is_untouched():
    assert split_front_matter("Điều 1. Phạm vi\n") == ("Điều 1. Phạm vi\n", {})


def test_sample_corpus_declares_its_metadata():
    doc = load_file(Path("data/sample_corpus/bo_luat_lao_dong_2019.md"))
    assert doc.meta.number == "45/2019/QH14"
    assert doc.meta.effective_date == date(2021, 1, 1)
