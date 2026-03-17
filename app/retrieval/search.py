from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session

from app.config import Settings
from app.db.vector_store import search_similar_chunks
from app.ingestion.embedder import embed_texts

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SearchResult:
    chunk_id: int
    document_id: int
    filename: str
    page_number: int | None
    section_title: str | None
    text: str
    similarity_score: float


def search_chunks(
    *,
    session: Session,
    settings: Settings,
    query: str,
    document_ids: list[int] | None = None,
    top_k: int = 5,
) -> list[SearchResult]:
    logger.info(
        "vector_search_started",
        extra={
            "document_count": len(document_ids) if document_ids is not None else "all",
            "top_k": top_k,
            "query_length": len(query),
        },
    )
    query_embedding = embed_texts([query], settings)
    if len(query_embedding) != 1:
        logger.info("vector_search_completed", extra={"result_count": 0, "reason": "no_embedding"})
        return []

    matches = search_similar_chunks(
        session=session,
        query_embedding=query_embedding[0],
        document_ids=document_ids,
        top_k=top_k,
    )
    results = [
        SearchResult(
            chunk_id=match.chunk_id,
            document_id=match.document_id,
            filename=match.filename,
            page_number=match.page_number,
            section_title=match.section_title,
            text=match.text,
            similarity_score=1.0 - match.distance,
        )
        for match in matches
    ]
    logger.info("vector_search_completed", extra={"result_count": len(results)})
    return results
