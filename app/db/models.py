from __future__ import annotations

from datetime import datetime
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Column, DateTime, ForeignKey, String, Text, func
from sqlmodel import Field, SQLModel

from app.config import DEFAULT_EMBEDDING_DIMENSION


class Document(SQLModel, table=True):
    __tablename__: ClassVar[str] = "documents"

    id: int | None = Field(default=None, primary_key=True)
    filename: str = Field(sa_column=Column(Text, nullable=False))
    file_path: str = Field(sa_column=Column(Text, nullable=False))
    checksum: str = Field(sa_column=Column(String, nullable=False, unique=True))
    page_count: int | None = Field(default=None)
    status: str = Field(sa_column=Column(String, nullable=False))
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        ),
    )


class DocumentChunk(SQLModel, table=True):
    __tablename__: ClassVar[str] = "document_chunks"

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(
        sa_column=Column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    )
    chunk_index: int = Field(nullable=False)
    page_number: int | None = Field(default=None)
    section_title: str | None = Field(default=None, sa_column=Column(Text))
    text: str = Field(sa_column=Column(Text, nullable=False))
    token_estimate: int = Field(default=0, nullable=False)
    metadata_json: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    embedding: list[float] | None = Field(
        default=None,
        sa_column=Column(Vector(DEFAULT_EMBEDDING_DIMENSION)),
    )
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )


class IngestionJob(SQLModel, table=True):
    __tablename__: ClassVar[str] = "ingestion_jobs"

    id: int | None = Field(default=None, primary_key=True)
    document_id: int = Field(
        sa_column=Column(ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    )
    status: str = Field(sa_column=Column(String, nullable=False))
    error_message: str | None = Field(default=None, sa_column=Column(Text))
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now(), nullable=False),
    )
