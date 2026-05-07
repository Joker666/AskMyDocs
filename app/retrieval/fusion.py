from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.retrieval.exa_search import ExaSearchResult

if TYPE_CHECKING:
    from app.retrieval.search import SearchResult

logger = logging.getLogger(__name__)

DEFAULT_RRF_K = 60


@dataclass(frozen=True)
class FusedResult:
    """A single result from fusing multiple retrieval sources via RRF."""

    source: str
    rank: int
    rrf_score: float
    # Local fields (populated when source="local")
    chunk_id: int | None = None
    document_id: int | None = None
    filename: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    text: str = ""
    similarity_score: float = 0.0
    # Exa fields (populated when source="exa")
    url: str | None = None
    title: str | None = None
    highlights: list[str] = field(default_factory=list)
    published_date: str | None = None


def reciprocal_rank_fusion(
    *,
    local_results: list[SearchResult],
    exa_results: list[ExaSearchResult],
    k: int = DEFAULT_RRF_K,
    local_weight: float = 1.0,
    exa_weight: float = 0.5,
    top_k: int | None = None,
) -> list[FusedResult]:
    """Merge local pgvector and Exa results using weighted Reciprocal Rank Fusion.

    RRF score for a document d across sources S:
        score(d) = Σ  weight_s / (k + rank_s(d))
                   s∈S

    Each result is identified by a unique key:
    - Local results: keyed by chunk_id
    - Exa results: keyed by URL

    The k constant (default 60) controls how much weight higher-ranked results
    get relative to lower-ranked ones. Higher k → more uniform scores.
    """
    scores: dict[str, float] = {}
    result_map: dict[str, FusedResult] = {}

    for rank_index, result in enumerate(local_results):
        key = f"local:{result.chunk_id}"
        rrf_contribution = local_weight / (k + rank_index + 1)
        scores[key] = scores.get(key, 0.0) + rrf_contribution
        if key not in result_map:
            result_map[key] = FusedResult(
                source="local",
                rank=0,
                rrf_score=0.0,
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                filename=result.filename,
                page_number=result.page_number,
                section_title=result.section_title,
                text=result.text,
                similarity_score=result.similarity_score,
            )

    for rank_index, result in enumerate(exa_results):
        key = f"exa:{result.url}"
        rrf_contribution = exa_weight / (k + rank_index + 1)
        scores[key] = scores.get(key, 0.0) + rrf_contribution
        if key not in result_map:
            result_map[key] = FusedResult(
                source="exa",
                rank=0,
                rrf_score=0.0,
                url=result.url,
                title=result.title,
                text=result.text,
                highlights=result.highlights,
                published_date=result.published_date,
            )

    sorted_keys = sorted(scores, key=lambda key: scores[key], reverse=True)
    if top_k is not None:
        sorted_keys = sorted_keys[:top_k]

    fused: list[FusedResult] = []
    for rank_index, key in enumerate(sorted_keys, start=1):
        base = result_map[key]
        fused.append(
            FusedResult(
                source=base.source,
                rank=rank_index,
                rrf_score=scores[key],
                chunk_id=base.chunk_id,
                document_id=base.document_id,
                filename=base.filename,
                page_number=base.page_number,
                section_title=base.section_title,
                text=base.text,
                similarity_score=base.similarity_score,
                url=base.url,
                title=base.title,
                highlights=base.highlights,
                published_date=base.published_date,
            )
        )

    logger.info(
        "rrf_fusion_completed",
        extra={
            "local_count": len(local_results),
            "exa_count": len(exa_results),
            "fused_count": len(fused),
            "local_weight": local_weight,
            "exa_weight": exa_weight,
        },
    )
    return fused
