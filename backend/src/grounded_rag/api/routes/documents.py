"""The document library: list for everyone, upload and delete for the admin."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from grounded_rag.api.deps import require_admin
from grounded_rag.api.schemas import DocumentOut
from grounded_rag.compute import run_model
from grounded_rag.config import settings
from grounded_rag.db.models import Document
from grounded_rag.db.session import get_session
from grounded_rag.documents import doc_id_for, index_document
from grounded_rag.ingest.loaders import load_file
from grounded_rag.retrieval.store import get_store

router = APIRouter(prefix="/api/documents", tags=["documents"])
Session = Annotated[AsyncSession, Depends(get_session)]
ALLOWED = {".md", ".pdf"}


@router.get("", response_model=list[DocumentOut])
async def list_documents(session: Session):
    return (await session.scalars(select(Document).order_by(Document.title))).all()


@router.post(
    "",
    status_code=202,
    response_model=DocumentOut,
    dependencies=[Depends(require_admin)],
)
async def upload_document(
    session: Session,
    background: BackgroundTasks,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form()] = None,
    number: Annotated[str | None, Form()] = None,
    effective_date: Annotated[date | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
):
    """Saves the file and returns at once; indexing runs after the response.
    Uploading a file with the same name replaces that document."""
    name = file.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400, "only .md and .pdf files are accepted")
    try:
        doc_id = doc_id_for(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    data = await _read_capped(file, settings.max_upload_mb * 1024 * 1024)

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{doc_id}{suffix}"
    path.write_bytes(data)
    # Markdown carries its own front matter; whatever the form says wins.
    meta = load_file(path).meta if suffix == ".md" else None

    doc = await session.get(Document, doc_id)
    if doc is None:
        doc = Document(id=doc_id)
        session.add(doc)
    elif doc.path != str(path):
        _remove_upload(doc.path)    # same name, other extension: the old file goes
    doc.title = title or (meta and meta.title) or Path(name).stem
    doc.number = number or (meta and meta.number) or None
    doc.issued_by = (meta and meta.issued_by) or None
    doc.effective_date = effective_date or (meta and meta.effective_date) or None
    doc.expiry_date = expiry_date or (meta and meta.expiry_date) or None
    doc.filename, doc.path = name, str(path)
    doc.status, doc.chunks, doc.error = "processing", 0, None
    await session.commit()
    await session.refresh(doc)

    background.add_task(index_document, doc_id)
    return doc


@router.delete("/{doc_id}", status_code=204, dependencies=[Depends(require_admin)])
async def delete_document(doc_id: str, session: Session) -> Response:
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, f"no document {doc_id!r}")
    await run_model(get_store().delete_document, doc_id)
    _remove_upload(doc.path)
    await session.delete(doc)
    await session.commit()
    return Response(status_code=204)


async def _read_capped(file: UploadFile, limit: int) -> bytes:
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"file is larger than {settings.max_upload_mb} MB")
    return data


def _remove_upload(path: str) -> None:
    """Only files the app saved itself: a document seeded from data/corpus
    keeps its source file when it leaves the library."""
    p = Path(path).resolve()
    if p.is_relative_to(settings.upload_dir.resolve()):
        p.unlink(missing_ok=True)
