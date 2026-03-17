from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    filename: str
    page_count: int | None
    status: str
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(BaseModel):
    document: DocumentSummary


class DocumentListResponse(BaseModel):
    documents: list[DocumentSummary]


class IngestionStatusResponse(BaseModel):
    job_id: int
    document_id: int
    status: str
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    chunk_count: int


class DocumentDetailResponse(BaseModel):
    id: int
    filename: str
    file_path: str
    checksum: str
    page_count: int | None
    status: str
    chunk_count: int
    created_at: datetime
    updated_at: datetime
    latest_ingestion: IngestionStatusResponse | None


class QueryRequest(BaseModel):
    question: str
    document_ids: list[int] | None = None
    top_k: int = Field(default=5, ge=1, le=20)
