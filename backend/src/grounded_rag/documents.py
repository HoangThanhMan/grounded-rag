"""The document library: what is indexed, and indexing it.

Indexing runs after the upload request has returned (FastAPI's
BackgroundTasks), and its state lives in the `documents` table - which is all
the UI needs to show progress. The price of not having a job queue: a restart
mid-index loses the job. `fail_stale_processing` runs at startup so such a
document says "failed" instead of "processing" forever; uploading it again
retries.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from pathlib import Path

from sqlalchemy import select, update

from grounded_rag.compute import run_model
from grounded_rag.db.models import Document
from grounded_rag.db.session import SessionLocal
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.ingest.pipeline import chunk_file
from grounded_rag.retrieval.lexical import tokenize
from grounded_rag.retrieval.store import get_store
from grounded_rag.types import DocMeta

log = logging.getLogger("grounded_rag.documents")
# Chunks embedded per model-pool call. A question asked during an upload
# waits for one batch - seconds on CPU - not for the whole law.
INDEX_BATCH = 32


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


async def index_document(doc_id: str) -> None:
    """Never raises: whatever goes wrong ends up in the row's `error`.

    No session is held while the models work, and the row is read again
    afterwards: it may have been deleted meanwhile, and then the chunks just
    written must go too."""
    async with SessionLocal() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            return
        path, meta = Path(doc.path), meta_of(doc)

    chunks, error = 0, None
    try:
        chunks = await _index(path, doc_id, meta)
    except Exception as e:
        log.exception("indexing %s failed", doc_id)
        error = str(e) or type(e).__name__

    async with SessionLocal() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            await run_model(get_store().delete_document, doc_id)
            return
        doc.status = "failed" if error else "ready"
        doc.chunks, doc.error = (0, error) if error else (chunks, None)
        await session.commit()


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
        for doc in (await session.scalars(select(Document))).all():
            if Path(doc.path).is_file() and not await asyncio.to_thread(
                store.has_document, doc.id
            ):
                doc.status, doc.error = "processing", None
                missing.append(doc.id)
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


async def fail_stale_processing() -> int:
    async with SessionLocal() as session:
        res = await session.execute(
            update(Document)
            .where(Document.status == "processing")
            .values(status="failed", error="interrupted by a restart")
        )
        await session.commit()
        return res.rowcount or 0
