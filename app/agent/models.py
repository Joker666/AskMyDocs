from __future__ import annotations

from pydantic import BaseModel, Field


class Citation(BaseModel):
    document_id: int
    chunk_id: int
    filename: str
    page_number: int | None
    section_title: str | None
    quote: str = Field(min_length=1)


class AnswerResult(BaseModel):
    answer: str = Field(min_length=1)
    citations: list[Citation]
    confidence: float = Field(ge=0.0, le=1.0)
