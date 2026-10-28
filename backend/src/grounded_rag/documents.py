"""The document library: what is indexed, and indexing it.

Indexing runs after the upload request has returned (FastAPI's
BackgroundTasks), and its state lives in the `documents` table - which is all
the UI needs to show progress. With no job queue, a restart mid-index loses
the job; at startup `requeue_interrupted` and `mark_missing` find such
documents and they are indexed again from their files.

A deleted document keeps its row as a tombstone (status "deleted"), so the
corpus seeder does not bring a law back that an admin removed.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select

from grounded_rag.compute import run_model
from grounded_rag.db.models import Document, now
from grounded_rag.db.session import SessionLocal
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.ingest.pipeline import DocumentError, chunk_file
from grounded_rag.retrieval.lexical import tokenize
from grounded_rag.retrieval.store import get_store
from grounded_rag.types import DocMeta

log = logging.getLogger("grounded_rag.documents")
# Chunks embedded per model-pool call. A question asked during an upload
# waits for one batch - seconds on CPU - not for the whole law.
INDEX_BATCH = 32
# A document "processing" for longer than this has lost its job: it no longer
# blocks a delete or a re-upload.
STUCK_AFTER = timedelta(minutes=30)
RECORD_RETRY_S = 1.0


def doc_id_for(filename: str) -> str:
    """"Bộ luật Lao động 2019.md" -> "bo_luat_lao_dong_2019": the id chunks are
    cited by, so it has to survive URLs, Qdrant payloads and log lines."""
    stem = Path(filename).stem.replace("đ", "d").replace("Đ", "D")
    ascii_ = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_")
    if not slug:
        raise ValueError(f"no usable characters in the file name: {filename!r}")
    return slug[:120]


def meta_of(doc: Document) -> DocMeta:
    return DocMeta(
        title=doc.title,
        number=doc.number,
        issued_by=doc.issued_by,
        effective_date=doc.effective_date,
        expiry_date=doc.expiry_date,
    )


def is_busy(doc: Document) -> bool:
    if doc.status != "processing":
        return False
    updated = doc.updated_at if doc.updated_at.tzinfo else doc.updated_at.replace(tzinfo=UTC)
    return datetime.now(UTC) - updated < STUCK_AFTER


async def index_document(doc_id: str) -> None:
    """Never raises: whatever goes wrong ends up in the row's `error`.

    No session is held while the models work, and the row is read again
    afterwards: it may have been deleted meanwhile, and then the chunks just
    written must go too. A failed index leaves no chunks behind: half a law,
    answered from while the library says "failed", is worse than none."""
    async with SessionLocal() as session:
        doc = await session.get(Document, doc_id)
        if doc is None or doc.status == "deleted":
            return
        path, meta = Path(doc.path), meta_of(doc)

    chunks, error = 0, None
    try:
        chunks = await _index(path, doc_id, meta)
    except Exception as e:
        log.exception("indexing %s failed", doc_id)
        # what the library page shows; the details are in the log
        error = str(e) if isinstance(e, DocumentError) else "indexing failed, see the server log"
        try:
            await run_model(get_store().delete_document, doc_id)
        except Exception:
            log.exception("could not remove the partial index of %s", doc_id)
    await _record(doc_id, chunks, error)


async def _record(doc_id: str, chunks: int, error: str | None) -> None:
    """A database blip here would leave the document "processing" - and its
    upload and delete refused - so it is retried before giving up."""
    for attempt in range(3):
        try:
            async with SessionLocal() as session:
                doc = await session.get(Document, doc_id)
                if doc is None or doc.status == "deleted":
                    await run_model(get_store().delete_document, doc_id)
                    return
                doc.status = "failed" if error else "ready"
                doc.chunks, doc.error = (0, error) if error else (chunks, None)
                await session.commit()
                return
        except Exception:
            log.exception("recording the index of %s failed (attempt %d)", doc_id, attempt + 1)
            if attempt < 2:
                await asyncio.sleep(RECORD_RETRY_S * (attempt + 1))
    log.error("gave up recording the index of %s; it stays processing until it is "
              "re-indexed at the next start", doc_id)


async def _index(path: Path, doc_id: str, meta: DocMeta) -> int:
    store = get_store()
    # First: whatever happens next, the previous version is not answered from.
    await run_model(store.delete_document, doc_id)
    chunks = await run_model(chunk_file, path, doc_id, meta)
    avg_len = sum(len(tokenize(c.text)) for c in chunks) / len(chunks)
    for i in range(0, len(chunks), INDEX_BATCH):
        await run_model(store.upsert, chunks[i : i + INDEX_BATCH], avg_len)
    return len(chunks)


async def mark_missing() -> list[str]:
    """Every document the library lists but the index does not hold, set
    back to `processing` and returned, for `index_document` to redo from the
    file it was indexed from. The mock index lives in the process and is
    empty after a restart; a first start can be interrupted mid-corpus; a
    Qdrant volume can be wiped. Needs no model, so it runs before any loads."""
    store = get_store()
    async with SessionLocal() as session:
        missing = []
        live = select(Document).where(Document.status.not_in(["deleted", "processing"]))
        for doc in (await session.scalars(live)).all():
            if Path(doc.path).is_file() and not await asyncio.to_thread(
                store.has_document, doc.id
            ):
                doc.status, doc.error = "processing", None
                missing.append(doc.id)
        # A deleted document's chunks can come back - `make ingest` does not
        # read the library - and its tombstone hides it from every other route.
        tombstones = select(Document.id).where(Document.status == "deleted")
        for doc_id in (await session.scalars(tombstones)).all():
            if await asyncio.to_thread(store.has_document, doc_id):
                await run_model(store.delete_document, doc_id)
        await session.commit()
    return missing


async def reindex_missing() -> int:
    missing = await mark_missing()
    for doc_id in missing:
        await index_document(doc_id)
    return len(missing)


async def register_corpus(directory: Path) -> list[str]:
    """Add every file of `directory` the library does not know yet, as
    `processing`, and return their ids. Reads front matter only - no model -
    so a first start lists the corpus at once and indexes it afterwards."""
    async with SessionLocal() as session:
        known = set((await session.scalars(select(Document.id))).all())
        fresh: list[str] = []
        for path in iter_corpus(directory):
            doc_id = doc_id_for(path.name)
            if doc_id in known:
                continue
            meta = load_file(path).meta
            session.add(
                Document(
                    id=doc_id,
                    title=meta.title or path.stem,
                    number=meta.number,
                    issued_by=meta.issued_by,
                    effective_date=meta.effective_date,
                    expiry_date=meta.expiry_date,
                    filename=path.name,
                    path=str(path),
                    status="processing",
                )
            )
            fresh.append(doc_id)
        await session.commit()
    return fresh


async def seed_corpus(directory: Path) -> int:
    """Register and index every file of `directory` the library does not
    know yet. Returns how many it indexed."""
    fresh = await register_corpus(directory)
    for doc_id in fresh:
        await index_document(doc_id)
    return len(fresh)


async def requeue_interrupted() -> list[str]:
    """Documents a restart caught mid-index. With their file still there they
    stay "processing" and are returned, to be indexed again from scratch;
    without it they are failed."""
    async with SessionLocal() as session:
        requeued = []
        for doc in (await session.scalars(
            select(Document).where(Document.status == "processing")
        )).all():
            if Path(doc.path).is_file():
                # busy again: no upload or delete may race the re-index
                doc.updated_at = now()
                requeued.append(doc.id)
            else:
                await run_model(get_store().delete_document, doc.id)
                doc.status, doc.error = "failed", "interrupted by a restart"
        await session.commit()
    return requeued


async def delete_document(doc: Document) -> None:
    """The chunks go; the row stays as a tombstone, so a seeded law is not
    seeded again at the next start. Uploading the file again revives it."""
    await run_model(get_store().delete_document, doc.id)
    doc.status, doc.chunks, doc.error, doc.updated_at = "deleted", 0, None, now()
