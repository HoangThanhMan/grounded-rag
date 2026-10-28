"""The document library: what is indexed, and indexing it.

Indexing runs after the upload request has returned (FastAPI's
BackgroundTasks), and its state lives in the `documents` table - which is all
the UI needs to show progress. The price of not having a job queue: a restart
mid-index loses the job. `fail_stale_processing` runs at startup so such a
document says "failed" instead of "processing" forever; uploading it again
retries.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from pathlib import Path

from sqlalchemy import select, update

from grounded_rag.compute import run_model
from grounded_rag.db.models import Document
from grounded_rag.db.session import SessionLocal
from grounded_rag.ingest.loaders import iter_corpus, load_file
from grounded_rag.ingest.pipeline import ingest_file
from grounded_rag.types import DocMeta

log = logging.getLogger("grounded_rag.documents")


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
    """Never raises: whatever goes wrong ends up in the row's `error`."""
    async with SessionLocal() as session:
        doc = await session.get(Document, doc_id)
        if doc is None:
            return
        try:
            doc.chunks = await run_model(ingest_file, Path(doc.path), doc_id, meta_of(doc))
            doc.status, doc.error = "ready", None
        except Exception as e:
            log.exception("indexing %s failed", doc_id)
            doc.status, doc.chunks, doc.error = "failed", 0, str(e) or type(e).__name__
        await session.commit()


async def seed_corpus(directory: Path) -> int:
    """Register and index every file of `directory` the library does not
    know yet. Returns how many it indexed."""
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
