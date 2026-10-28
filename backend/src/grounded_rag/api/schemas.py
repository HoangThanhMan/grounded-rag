"""Request and response bodies of the HTTP API."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    number: str | None
    issued_by: str | None
    effective_date: date | None
    expiry_date: date | None
    filename: str
    status: str
    chunks: int
    error: str | None
    updated_at: datetime
