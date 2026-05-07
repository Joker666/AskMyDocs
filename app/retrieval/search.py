from __future__ import annotations

import logging
from dataclasses import dataclass

from sqlmodel import Session

from app.config import Settings
from app.db.vector_store import search_similar_chunks
from app.ingestion.embedder import embed_texts
from app.observability import preview_text, start_observation
from app.retrieval.exa_search import ExaSearchError, search_exa
from app.retrieval.fusion import FusedResult, reciprocal_rank_fusion

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
    with start_observation(
        settings,
        name="retrieval.search",
        as_type="retriever",
        input={
            "query": preview_text(query),
            "document_ids": document_ids or [],
            "top_k": top_k,
        },
        metadata={"component": "vector_search"},
    ) as span:
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
            logger.info(
                "vector_search_completed",
                extra={"result_count": 0, "reason": "no_embedding"},
            )
            if span is not None:
                span.update(output={"result_count": 0, "reason": "no_embedding"})
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
        if span is not None:
            span.update(
                output={
                    "result_count": len(results),
                    "chunk_ids": [result.chunk_id for result in results],
                }
            )
        return results


def hybrid_search(
    *,
    session: Session,
    settings: Settings,
    query: str,
    document_ids: list[int] | None = None,
    top_k: int = 5,
) -> list[FusedResult]:
    """Run pgvector search and optionally Exa search, fuse results with RRF."""
    with start_observation(
        settings,
        name="retrieval.hybrid_search",
        as_type="retriever",
        input={
            "query": preview_text(query),
            "document_ids": document_ids or [],
            "top_k": top_k,
            "exa_enabled": settings.exa_is_configured,
        },
        metadata={"component": "hybrid_search"},
    ) as span:
        local_results = search_chunks(
            session=session,
            settings=settings,
            query=query,
            document_ids=document_ids,
            top_k=top_k,
        )

        if not settings.exa_is_configured:
            fused = _wrap_local_results(local_results)
            logger.info(
                "hybrid_search_completed",
                extra={
                    "mode": "local_only",
                    "local_count": len(local_results),
                    "exa_count": 0,
                    "fused_count": len(fused),
                },
            )
            if span is not None:
                span.update(
                    output={
                        "mode": "local_only",
                        "local_count": len(local_results),
                        "exa_count": 0,
                        "fused_count": len(fused),
                    }
                )
            return fused

        try:
            exa_results = search_exa(
                settings=settings,
                query=query,
                num_results=settings.exa_num_results,
            )
        except ExaSearchError:
            logger.warning("exa_search_failed_gracefully", extra={"query_length": len(query)})
            fused = _wrap_local_results(local_results)
            if span is not None:
                span.update(
                    output={
                        "mode": "local_only_exa_failed",
                        "local_count": len(local_results),
                        "exa_count": 0,
                        "fused_count": len(fused),
                    }
                )
            return fused

        if not exa_results:
            fused = _wrap_local_results(local_results)
            logger.info(
                "hybrid_search_completed",
                extra={
                    "mode": "local_only_exa_empty",
                    "local_count": len(local_results),
                    "exa_count": 0,
                    "fused_count": len(fused),
                },
            )
            if span is not None:
                span.update(
                    output={
                        "mode": "local_only_exa_empty",
                        "local_count": len(local_results),
                        "exa_count": 0,
                        "fused_count": len(fused),
                    }
                )
            return fused

        fused = reciprocal_rank_fusion(
            local_results=local_results,
            exa_results=exa_results,
            exa_weight=settings.exa_weight,
            top_k=top_k,
        )

        exa_cost_estimate = _estimate_exa_cost(len(exa_results))
        logger.info(
            "hybrid_search_completed",
            extra={
                "mode": "fused",
                "local_count": len(local_results),
                "exa_count": len(exa_results),
                "fused_count": len(fused),
                "exa_weight": settings.exa_weight,
                "exa_cost_estimate_usd": exa_cost_estimate,
            },
        )
        if span is not None:
            span.update(
                output={
                    "mode": "fused",
                    "local_count": len(local_results),
                    "exa_count": len(exa_results),
                    "fused_count": len(fused),
                    "exa_weight": settings.exa_weight,
                    "exa_cost_estimate_usd": exa_cost_estimate,
                },
                metadata={"exa_cost_estimate_usd": exa_cost_estimate},
            )
        return fused


EXA_BASE_SEARCH_COST = 0.007
EXA_PER_CONTENT_COST = 0.001
EXA_EXTRA_RESULT_COST = 0.001
EXA_INCLUDED_RESULTS = 10


def _estimate_exa_cost(num_results: int) -> float:
    """Estimate Exa API cost in USD for a single search call.

    Based on Exa pricing:
    - $0.007 per search (up to 10 results)
    - $0.001 per extra result beyond 10
    - $0.001 per result for text content
    - $0.001 per result for highlights
    """
    base = EXA_BASE_SEARCH_COST
    extra_results = max(0, num_results - EXA_INCLUDED_RESULTS) * EXA_EXTRA_RESULT_COST
    content = num_results * EXA_PER_CONTENT_COST * 2  # text + highlights
    return round(base + extra_results + content, 4)


def _wrap_local_results(results: list[SearchResult]) -> list[FusedResult]:
    """Convert local-only results into FusedResult for a uniform return type."""
    return [
        FusedResult(
            source="local",
            rank=index,
            rrf_score=result.similarity_score,
            chunk_id=result.chunk_id,
            document_id=result.document_id,
            filename=result.filename,
            page_number=result.page_number,
            section_title=result.section_title,
            text=result.text,
            similarity_score=result.similarity_score,
        )
        for index, result in enumerate(results, start=1)
    ]

