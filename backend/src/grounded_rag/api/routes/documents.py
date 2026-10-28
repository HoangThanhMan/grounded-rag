"""The document library: list for everyone, upload and delete for the admin."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

import yaml
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
from grounded_rag.config import settings
from grounded_rag.db.models import Document
from grounded_rag.db.session import get_session
from grounded_rag.documents import delete_document as tombstone
from grounded_rag.documents import doc_id_for, index_document, is_busy
from grounded_rag.ingest.loaders import load_file
from grounded_rag.types import DocMeta

router = APIRouter(prefix="/api/documents", tags=["documents"])
Session = Annotated[AsyncSession, Depends(get_session)]
ALLOWED = {".md", ".pdf"}
MAX_NAME = 255


@router.get("", response_model=list[DocumentOut])
async def list_documents(session: Session):
    return (
        await session.scalars(
            select(Document).where(Document.status != "deleted").order_by(Document.title)
        )
    ).all()


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
    title: Annotated[str | None, Form(max_length=300)] = None,
    number: Annotated[str | None, Form(max_length=100)] = None,
    effective_date: Annotated[date | None, Form()] = None,
    expiry_date: Annotated[date | None, Form()] = None,
):
    """Saves the file and returns at once; indexing runs after the response.
    Uploading a file with the same name replaces that document."""
    name = file.filename or ""
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(400, "only .md and .pdf files are accepted")
    if len(name) > MAX_NAME:
        raise HTTPException(400, f"the file name is longer than {MAX_NAME} characters")
    try:
        doc_id = doc_id_for(name)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    existing = await session.get(Document, doc_id)
    if existing is not None and is_busy(existing):
        raise HTTPException(409, f"{doc_id!r} is still being indexed, try again when it is done")
    data = await _read_capped(file, settings.max_upload_mb * 1024 * 1024)

    # Checked in a file of its own first: a broken upload must not replace
    # the source of a document that is in use.
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    path = settings.upload_dir / f"{doc_id}{suffix}"
    staged = settings.upload_dir / f".{doc_id}.upload{suffix}"
    staged.write_bytes(data)
    try:
        # Markdown carries its own front matter; whatever the form says wins.
        meta = load_file(staged).meta if suffix == ".md" else None
        if meta:
            _check_lengths(meta)
    except (ValueError, yaml.YAMLError) as e:
        staged.unlink(missing_ok=True)
        raise HTTPException(400, f"the front matter is not valid: {_first_line(e)}") from e
    staged.replace(path)

    doc = existing
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
    if doc is None or doc.status == "deleted":
        raise HTTPException(404, f"no document {doc_id!r}")
    if is_busy(doc):
        raise HTTPException(409, f"{doc_id!r} is being indexed, try again when it is done")
    await tombstone(doc)
    _remove_upload(doc.path)
    await session.commit()
    return Response(status_code=204)


def _check_lengths(meta: DocMeta) -> None:
    """What the columns hold. SQLite would store a longer value; Postgres
    rejects it with a 500."""
    for field in ("title", "number", "issued_by"):
        value = getattr(meta, field)
        limit = Document.__table__.c[field].type.length
        if value and len(value) > limit:
            raise ValueError(f"{field} is longer than {limit} characters")


def _first_line(e: Exception) -> str:
    return str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__


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
