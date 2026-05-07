from __future__ import annotations

from app.retrieval.exa_search import ExaSearchResult
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.search import SearchResult


def _local(chunk_id: int, score: float = 0.9) -> SearchResult:
    return SearchResult(
        chunk_id=chunk_id,
        document_id=1,
        filename="doc.pdf",
        page_number=1,
        section_title="Section",
        text=f"Chunk {chunk_id} text",
        similarity_score=score,
    )


def _exa(url: str, score: float = 0.8) -> ExaSearchResult:
    return ExaSearchResult(
        title=f"Page at {url}",
        url=url,
        text=f"Content from {url}",
        score=score,
        highlights=["highlight"],
        published_date=None,
    )


class TestReciprocalRankFusion:
    def test_local_only(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[_local(1), _local(2)],
            exa_results=[],
        )
        assert len(results) == 2
        assert all(r.source == "local" for r in results)
        assert results[0].rank == 1
        assert results[1].rank == 2
        assert results[0].rrf_score > results[1].rrf_score

    def test_exa_only(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[],
            exa_results=[_exa("https://a.com"), _exa("https://b.com")],
        )
        assert len(results) == 2
        assert all(r.source == "exa" for r in results)
        assert results[0].url == "https://a.com"

    def test_mixed_results_sorted_by_rrf(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[_local(1), _local(2), _local(3)],
            exa_results=[_exa("https://a.com"), _exa("https://b.com")],
            local_weight=1.0,
            exa_weight=1.0,
        )
        assert len(results) == 5
        scores = [r.rrf_score for r in results]
        assert scores == sorted(scores, reverse=True)

    def test_local_weight_bias(self) -> None:
        """With high local weight = 2.0 and exa weight = 0.1, local results dominate."""
        results = reciprocal_rank_fusion(
            local_results=[_local(1)],
            exa_results=[_exa("https://a.com")],
            local_weight=2.0,
            exa_weight=0.1,
        )
        assert results[0].source == "local"
        assert results[0].rrf_score > results[1].rrf_score * 10

    def test_exa_weight_bias(self) -> None:
        """With exa weight = 2.0 and local weight = 0.1, exa results dominate."""
        results = reciprocal_rank_fusion(
            local_results=[_local(1)],
            exa_results=[_exa("https://a.com")],
            local_weight=0.1,
            exa_weight=2.0,
        )
        assert results[0].source == "exa"

    def test_top_k_truncation(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[_local(i) for i in range(10)],
            exa_results=[_exa(f"https://{i}.com") for i in range(10)],
            top_k=3,
        )
        assert len(results) == 3

    def test_empty_inputs(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[],
            exa_results=[],
        )
        assert results == []

    def test_ranks_are_sequential(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[_local(1), _local(2)],
            exa_results=[_exa("https://a.com")],
        )
        ranks = [r.rank for r in results]
        assert ranks == list(range(1, len(results) + 1))

    def test_local_fields_preserved(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[_local(42, score=0.95)],
            exa_results=[],
        )
        r = results[0]
        assert r.chunk_id == 42
        assert r.document_id == 1
        assert r.filename == "doc.pdf"
        assert r.similarity_score == 0.95
        assert r.url is None

    def test_exa_fields_preserved(self) -> None:
        results = reciprocal_rank_fusion(
            local_results=[],
            exa_results=[_exa("https://example.com")],
        )
        r = results[0]
        assert r.url == "https://example.com"
        assert r.title == "Page at https://example.com"
        assert r.highlights == ["highlight"]
        assert r.chunk_id is None
        assert r.document_id is None

    def test_custom_k_constant(self) -> None:
        """Lower k gives more reward to top-ranked results."""
        results_low_k = reciprocal_rank_fusion(
            local_results=[_local(1), _local(2)],
            exa_results=[],
            k=1,
        )
        results_high_k = reciprocal_rank_fusion(
            local_results=[_local(1), _local(2)],
            exa_results=[],
            k=100,
        )
        spread_low = results_low_k[0].rrf_score - results_low_k[1].rrf_score
        spread_high = results_high_k[0].rrf_score - results_high_k[1].rrf_score
        assert spread_low > spread_high
