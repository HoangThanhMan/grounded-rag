from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from grounded_rag.types import Answer

CONFIG_NAME = r"^[A-Za-z0-9_-]+$"   # a file in configs/, never a path


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    config: str = Field(default="full", pattern=CONFIG_NAME)
    as_of: date | None = None       # read the law as of this day; default today


class ChatResponse(Answer):
    pass


class IngestRequest(BaseModel):
    # An unknown field is an error, not ignored: `recreate` used to be one,
    # and a client still sending it must learn it no longer drops the index.
    model_config = ConfigDict(extra="forbid")

    source: str = "data/corpus"     # a directory under settings.data_root
    config: str = Field(default="full", pattern=CONFIG_NAME)


class IngestResponse(BaseModel):
    files: int
    chunks: int
    written: int


class ConfigSummary(BaseModel):
    """One row of GET /configs - which layers of defence a config turns on."""

    name: str
    guard_enabled: bool
    entailment_threshold: float
    corrective_enabled: bool
    min_score: float
    chunker: str
