"""The document library: upload, index in the background, list, delete."""

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from grounded_rag.api.main import app
from grounded_rag.db.models import Document
from grounded_rag.db.session import SessionLocal
from grounded_rag.documents import doc_id_for, requeue_interrupted
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
    """Changed text, so content-hashed ids cannot hide old chunks."""
    old = "---\ntitle: v1\n---\nĐiều 1. A\n1. Bản cũ khoản một.\n2. Bản cũ khoản hai.\n"
    _upload("Thay thế.md", old.encode())
    assert _indexed("thay_the") == 2
    _upload("Thay thế.md", "---\ntitle: v2\n---\nĐiều 1. A\n1. Bản mới khoản một.\n".encode())
    texts = [c.text for c in get_store()._chunks if c.doc_id == "thay_the"]
    assert len(texts) == 1 and "Bản mới" in texts[0]


def test_a_failed_reupload_leaves_no_old_chunks_behind():
    _upload("Hỏng sau.md", "---\ntitle: v1\n---\nĐiều 1. A\n1. Khoản một.\n".encode())
    assert _indexed("hong_sau") == 1
    _upload("Hỏng sau.md", b"---\ntitle: v2\n---\n")
    assert _get("hong_sau")["status"] == "failed"
    assert _indexed("hong_sau") == 0


def test_malformed_front_matter_is_400_and_keeps_the_previous_file():
    _upload("Giữ nguyên.md", "---\ntitle: Tot\n---\nĐiều 1. A\n1. Khoản một.\n".encode())
    from grounded_rag.config import settings
    saved = (settings.upload_dir / "giu_nguyen.md").read_bytes()
    for bad in ("---\neffective_date: hom qua\n---\nĐiều 1. A\n".encode(),
                "---\ntitle: [chua dong\n---\nĐiều 1. A\n".encode()):
        r = _upload("Giữ nguyên.md", bad)
        assert r.status_code == 400, r.text
        assert r.json()["error"]["code"] == "bad_request"
    assert (settings.upload_dir / "giu_nguyen.md").read_bytes() == saved
    assert _get("giu_nguyen")["status"] == "ready"


def test_overlong_metadata_is_rejected_not_a_500():
    assert _upload("Dai.md", title="x" * 301).status_code == 422
    assert _upload("Dai.md", number="1" * 101).status_code == 422
    long_title = b"---\ntitle: " + b"y" * 301 + "\n---\nĐiều 1. A\n1. B.\n".encode()
    assert _upload("Dai.md", long_title).status_code == 400
    assert _upload("x" * 260 + ".md").status_code == 400


def test_deleting_a_document_while_it_is_indexed_leaves_no_orphans(monkeypatch):
    """The row can go away while its chunks are being embedded."""
    from grounded_rag import documents

    real = documents._index

    async def delete_midway(path, doc_id, meta):
        n = await real(path, doc_id, meta)
        async with SessionLocal() as s:
            await s.delete(await s.get(Document, doc_id))
            await s.commit()
        return n

    monkeypatch.setattr(documents, "_index", delete_midway)
    r = _upload("Đang xoá.md")
    assert r.status_code == 202
    assert _indexed("dang_xoa") == 0
    assert all(d["id"] != "dang_xoa" for d in client.get("/api/documents").json())


def test_cannot_delete_a_document_that_is_being_indexed():
    async def processing() -> None:
        async with SessionLocal() as s:
            s.add(Document(id="dang_chay", title="x", filename="x.md", path="x.md",
                           status="processing"))
            await s.commit()

    asyncio.run(processing())
    r = client.delete("/api/documents/dang_chay", headers=ADMIN)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"


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


def test_an_interrupted_document_without_its_file_is_failed():
    async def scenario() -> tuple[list[str], Document | None]:
        async with SessionLocal() as s:
            s.add(Document(id="dang_do", title="Dang do", filename="x.md", path="khong/co.md",
                           status="processing"))
            await s.commit()
        ids = await requeue_interrupted()
        async with SessionLocal() as s:
            return ids, await s.get(Document, "dang_do")

    ids, doc = asyncio.run(scenario())
    assert "dang_do" not in ids
    assert doc.status == "failed"
    assert doc.error == "interrupted by a restart"


def test_seed_corpus_indexes_new_files_once():
    from grounded_rag.documents import seed_corpus

    assert asyncio.run(seed_corpus(Path("data/sample_corpus"))) in (0, 1)
    assert asyncio.run(seed_corpus(Path("data/sample_corpus"))) == 0
    assert _get("bo_luat_lao_dong_2019")["status"] == "ready"


def _law(tmp_path: Path, name: str, clauses: int = 3) -> Path:
    body = "\n".join(f"{i}. Khoản số {i} quy định nội dung thứ {i}." for i in range(1, clauses + 1))
    path = tmp_path / name
    path.write_text(f"---\ntitle: {name}\neffective_date: 2020-01-01\n---\n"
                    f"Điều 1. Phạm vi\n{body}\n", encoding="utf-8")
    return path


def test_reindex_missing_restores_a_ready_document_whose_chunks_are_gone(tmp_path):
    """The mock store lives in the process: after a restart the library still
    says ready, the index is empty."""
    from grounded_rag.documents import reindex_missing, seed_corpus

    _law(tmp_path, "luat_mat_index.md")
    asyncio.run(seed_corpus(tmp_path))
    assert _get("luat_mat_index")["status"] == "ready"
    get_store().delete_document("luat_mat_index")          # what a restart does
    assert asyncio.run(reindex_missing()) >= 1
    assert _indexed("luat_mat_index") == 3
    assert _get("luat_mat_index")["status"] == "ready"


def test_seeding_retries_a_corpus_file_that_failed(tmp_path):
    """A first start interrupted mid-index must not leave the law failed for good."""
    from grounded_rag.documents import reindex_missing

    path = _law(tmp_path, "luat_bi_ngat.md")

    async def interrupted() -> None:
        async with SessionLocal() as s:
            s.add(Document(id="luat_bi_ngat", title="x", filename=path.name, path=str(path),
                           status="failed", error="interrupted by a restart"))
            await s.commit()

    asyncio.run(interrupted())
    asyncio.run(reindex_missing())
    assert _get("luat_bi_ngat")["status"] == "ready"


def test_indexing_hands_the_model_pool_back_between_batches(tmp_path, monkeypatch):
    """One run_model call per batch, so a question asked during an upload
    waits for one batch, not for the whole law."""
    from grounded_rag import documents

    calls = []
    real = documents.run_model

    async def counting(fn, *args, **kw):
        calls.append(fn)
        return await real(fn, *args, **kw)

    monkeypatch.setattr(documents, "run_model", counting)
    _law(tmp_path, "luat_dai.md", clauses=documents.INDEX_BATCH * 2 + 1)
    asyncio.run(documents.seed_corpus(tmp_path))
    assert _get("luat_dai")["chunks"] == documents.INDEX_BATCH * 2 + 1
    assert len(calls) >= 3


def test_cannot_reupload_a_document_that_is_being_indexed():
    async def processing() -> None:
        async with SessionLocal() as s:
            s.add(Document(id="dang_chay_lai", title="x", filename="x.md", path="x.md",
                           status="processing"))
            await s.commit()

    asyncio.run(processing())
    assert _upload("dang_chay_lai.md").status_code == 409


def test_startup_marks_unindexed_documents_before_any_model_loads(tmp_path):
    """Loading a model takes minutes on a first start; until the index holds
    a document, the library must not call it ready."""
    from grounded_rag.documents import mark_missing, seed_corpus

    _law(tmp_path, "luat_cho_index.md")
    asyncio.run(seed_corpus(tmp_path))
    get_store().delete_document("luat_cho_index")
    assert "luat_cho_index" in asyncio.run(mark_missing())
    assert _get("luat_cho_index")["status"] == "processing"


def test_a_first_start_lists_the_corpus_before_any_model_loads(tmp_path):
    from grounded_rag.documents import register_corpus

    _law(tmp_path, "luat_moi_dang_ky.md")
    assert asyncio.run(register_corpus(tmp_path)) == ["luat_moi_dang_ky"]
    assert _get("luat_moi_dang_ky")["status"] == "processing"
    assert _indexed("luat_moi_dang_ky") == 0
    assert asyncio.run(register_corpus(tmp_path)) == []      # once


def test_a_failed_index_leaves_no_partial_chunks(tmp_path, monkeypatch):
    """Half a law answered from, while the library says failed, is worse than none."""
    from grounded_rag import documents

    store = get_store()
    real, calls = store.upsert, []

    def flaky(chunks, avg_len=None):
        calls.append(1)
        if len(calls) == 2:
            raise ConnectionError("qdrant went away")
        return real(chunks, avg_len)

    monkeypatch.setattr(store, "upsert", flaky)
    _law(tmp_path, "luat_dut_giua.md", clauses=documents.INDEX_BATCH * 2 + 1)
    asyncio.run(documents.seed_corpus(tmp_path))
    doc = _get("luat_dut_giua")
    assert doc["status"] == "failed"
    assert _indexed("luat_dut_giua") == 0
    assert "qdrant" not in doc["error"]          # internals stay in the log


def test_an_index_cut_off_by_a_restart_is_redone(tmp_path):
    from grounded_rag import documents

    path = _law(tmp_path, "luat_bi_cat.md", clauses=5)
    chunks = documents.chunk_file(path, "luat_bi_cat", documents.DocMeta())
    get_store().upsert(chunks[:2])                    # what the first batch left

    async def interrupted() -> None:
        async with SessionLocal() as s:
            s.add(Document(id="luat_bi_cat", title="x", filename=path.name, path=str(path),
                           status="processing"))
            await s.commit()

    asyncio.run(interrupted())
    assert "luat_bi_cat" in asyncio.run(requeue_interrupted())
    asyncio.run(documents.index_document("luat_bi_cat"))
    assert _get("luat_bi_cat")["status"] == "ready"
    assert _indexed("luat_bi_cat") == 5


def test_a_deleted_seed_law_stays_deleted_after_a_restart(tmp_path):
    from grounded_rag.documents import mark_missing, register_corpus, seed_corpus

    _law(tmp_path, "luat_da_xoa.md")
    asyncio.run(seed_corpus(tmp_path))
    assert client.delete("/api/documents/luat_da_xoa", headers=ADMIN).status_code == 204
    assert (tmp_path / "luat_da_xoa.md").exists()        # the corpus file is not the app's
    assert asyncio.run(register_corpus(tmp_path)) == []
    assert "luat_da_xoa" not in asyncio.run(mark_missing())
    assert all(d["id"] != "luat_da_xoa" for d in client.get("/api/documents").json())
    assert client.delete("/api/documents/luat_da_xoa", headers=ADMIN).status_code == 404
    _upload("luat_da_xoa.md", "---\ntitle: x\n---\nĐiều 1. A\n1. Trở lại.\n".encode())  # revived
    assert _get("luat_da_xoa")["status"] == "ready"


def test_a_database_blip_when_recording_the_result_is_retried(tmp_path, monkeypatch):
    from grounded_rag import documents

    monkeypatch.setattr(documents, "RECORD_RETRY_S", 0)
    real, opened = documents.SessionLocal, []

    def flaky_session():
        opened.append(1)
        if len(opened) == 2:                      # the session that records the result
            raise ConnectionError("database restarting")
        return real()

    _law(tmp_path, "luat_db_chap_chon.md")
    asyncio.run(documents.register_corpus(tmp_path))
    monkeypatch.setattr(documents, "SessionLocal", flaky_session)
    asyncio.run(documents.index_document("luat_db_chap_chon"))
    assert _get("luat_db_chap_chon")["status"] == "ready"


def test_a_document_stuck_processing_for_long_can_be_deleted():
    from datetime import UTC, datetime, timedelta

    async def stuck() -> None:
        async with SessionLocal() as s:
            s.add(Document(id="ket_lau", title="x", filename="x.md", path="x.md",
                           status="processing",
                           updated_at=datetime.now(UTC) - timedelta(hours=2)))
            await s.commit()

    asyncio.run(stuck())
    assert client.delete("/api/documents/ket_lau", headers=ADMIN).status_code == 204
