from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlmodel import Session, select

from app.db.models import Document, DocumentChunk


@dataclass(frozen=True)
class VectorSearchMatch:
    chunk_id: int
    document_id: int
    filename: str
    page_number: int | None
    section_title: str | None
    text: str
    distance: float


def search_similar_chunks(
    *,
    session: Session,
    query_embedding: list[float],
    document_ids: list[int] | None = None,
    top_k: int = 5,
) -> list[VectorSearchMatch]:
    embedding_column = cast(Any, DocumentChunk.embedding)
    document_id_column = cast(Any, DocumentChunk.document_id)
    distance = embedding_column.cosine_distance(query_embedding)
    columns: tuple[Any, ...] = (
        cast(Any, DocumentChunk.id),
        document_id_column,
        cast(Any, Document.filename),
        cast(Any, DocumentChunk.page_number),
        cast(Any, DocumentChunk.section_title),
        cast(Any, DocumentChunk.text),
        distance.label("distance"),
    )
    statement = (
        select(*columns)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(embedding_column.is_not(None))
        .order_by(distance)
        .limit(top_k)
    )
    if document_ids:
        statement = statement.where(document_id_column.in_(document_ids))

    rows = session.exec(statement).all()
    return [
        VectorSearchMatch(
            chunk_id=chunk_id,
            document_id=document_id,
            filename=filename,
            page_number=page_number,
            section_title=section_title,
            text=text,
            distance=float(row_distance),
        )
        for chunk_id, document_id, filename, page_number, section_title, text, row_distance in rows
    ]
