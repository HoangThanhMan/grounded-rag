"""The document library: upload, index in the background, list, delete."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grounded_rag.api.main import app
from grounded_rag.db.models import Document
from grounded_rag.db.session import SessionLocal
from grounded_rag.documents import doc_id_for, fail_stale_processing
from grounded_rag.retrieval.store import get_store

SAMPLE = Path("data/sample_corpus/bo_luat_lao_dong_2019.md")
ADMIN = {"X-API-Key": "test"}

client = TestClient(app)


def _upload(name: str = "Bộ luật Lao động 2019.md", body: bytes | None = None, **form):
    content = SAMPLE.read_bytes() if body is None else body
    return client.post(
        "/api/documents", files={"file": (name, content, "text/markdown")}, data=form,
        headers=ADMIN,
    )


def _get(doc_id: str) -> dict:
    return next(d for d in client.get("/api/documents").json() if d["id"] == doc_id)


def _indexed(doc_id: str) -> int:
    store = get_store()
    return sum(c.doc_id == doc_id for c in getattr(store, "_chunks", []))


def test_doc_id_from_vietnamese_filename():
    assert doc_id_for("Bộ luật Lao động 2019.md") == "bo_luat_lao_dong_2019"
    assert doc_id_for("Luật BHXH (sửa đổi) – 2024.pdf") == "luat_bhxh_sua_doi_2024"


def test_doc_id_of_a_name_with_no_letters_is_an_error():
    with pytest.raises(ValueError):
        doc_id_for("—.md")


def test_upload_indexes_in_background():
    r = _upload()
    assert r.status_code == 202
    assert r.json()["status"] == "processing"
    assert r.json()["id"] == "bo_luat_lao_dong_2019"
    # TestClient runs background tasks before it returns the response
    doc = _get("bo_luat_lao_dong_2019")
    assert doc["status"] == "ready"
    assert doc["chunks"] > 0
    assert doc["title"] == "Bộ luật Lao động 2019 (trích)"   # from the front matter
    assert doc["effective_date"] == "2021-01-01"


def test_form_metadata_wins_over_front_matter():
    _upload(title="BLLĐ 2019", effective_date="2021-01-01")
    assert _get("bo_luat_lao_dong_2019")["title"] == "BLLĐ 2019"


def test_reupload_replaces_chunks():
    _upload()
    first = _indexed("bo_luat_lao_dong_2019")
    _upload()
    assert _indexed("bo_luat_lao_dong_2019") == first > 0


def test_empty_document_fails():
    r = _upload("Trống.md", b"---\ntitle: Trong\n---\n")
    assert r.status_code == 202
    doc = _get("trong")
    assert doc["status"] == "failed"
    assert "no text" in doc["error"]
    assert doc["chunks"] == 0


def test_rejects_other_extensions():
    assert _upload("hop_dong.docx", b"x").status_code == 400


def test_rejects_files_over_the_size_limit():
    big = b"a" * (10 * 1024 * 1024 + 1)
    assert _upload("lon.md", big).status_code == 413


def test_admin_routes_need_the_key():
    files = {"file": ("a.md", b"x", "text/markdown")}
    assert client.post("/api/documents", files=files).status_code == 401
    wrong = client.post("/api/documents", files=files, headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401
    assert client.delete("/api/documents/a", headers={"X-API-Key": "nope"}).status_code == 401


def test_delete_removes_from_store_and_db():
    _upload("Xoá tôi.md")
    assert _indexed("xoa_toi") > 0
    assert client.delete("/api/documents/xoa_toi", headers=ADMIN).status_code == 204
    assert _indexed("xoa_toi") == 0
    assert all(d["id"] != "xoa_toi" for d in client.get("/api/documents").json())
    assert client.delete("/api/documents/xoa_toi", headers=ADMIN).status_code == 404


def test_stale_processing_marked_failed():
    async def scenario() -> tuple[int, Document | None]:
        async with SessionLocal() as s:
            s.add(Document(id="dang_do", title="Dang do", filename="x.md", path="x.md",
                           status="processing"))
            await s.commit()
        n = await fail_stale_processing()
        async with SessionLocal() as s:
            return n, await s.get(Document, "dang_do")

    n, doc = asyncio.run(scenario())
    assert n >= 1
    assert doc.status == "failed"
    assert doc.error == "interrupted by a restart"


def test_seed_corpus_indexes_new_files_once():
    from grounded_rag.documents import seed_corpus

    assert asyncio.run(seed_corpus(Path("data/sample_corpus"))) in (0, 1)
    assert asyncio.run(seed_corpus(Path("data/sample_corpus"))) == 0
    assert _get("bo_luat_lao_dong_2019")["status"] == "ready"
