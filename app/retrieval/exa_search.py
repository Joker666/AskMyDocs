from __future__ import annotations

import logging
from dataclasses import dataclass

from exa_py import Exa

from app.config import Settings
from app.observability import preview_text, start_observation
from app.runtime import safe_error_detail

logger = logging.getLogger(__name__)

EXA_TIMEOUT_SECONDS = 10
EXA_HEALTH_TIMEOUT_SECONDS = 5


class ExaSearchError(Exception):
    """Raised when Exa API operations fail."""


@dataclass(frozen=True)
class ExaSearchResult:
    title: str
    url: str
    text: str
    score: float
    highlights: list[str]
    published_date: str | None


def _build_client(settings: Settings) -> Exa:
    if settings.exa_api_key is None:
        raise ExaSearchError("Exa API key is not configured.")
    return Exa(api_key=settings.exa_api_key.get_secret_value())


def search_exa(
    *,
    settings: Settings,
    query: str,
    num_results: int | None = None,
) -> list[ExaSearchResult]:
    """Run a search against the Exa API and return structured results."""
    effective_num_results = num_results or settings.exa_num_results

    with start_observation(
        settings,
        name="exa.search",
        as_type="retriever",
        input={
            "query": preview_text(query),
            "num_results": effective_num_results,
            "search_type": settings.exa_search_type,
        },
        metadata={"component": "exa_search"},
    ) as span:
        logger.info(
            "exa_search_started",
            extra={
                "query_length": len(query),
                "num_results": effective_num_results,
                "search_type": settings.exa_search_type,
            },
        )

        try:
            client = _build_client(settings)
            response = client.search(
                query=query,
                type=settings.exa_search_type,
                num_results=effective_num_results,
                text=True,
                highlights=True,
            )
        except ExaSearchError:
            raise
        except Exception as exc:
            detail = safe_error_detail(exc, fallback="Exa API search failed.")
            raise ExaSearchError(detail) from exc

        results: list[ExaSearchResult] = []
        for result in response.results:
            text = getattr(result, "text", None) or ""
            highlights_list: list[str] = []
            raw_highlights = getattr(result, "highlights", None)
            if isinstance(raw_highlights, list):
                highlights_list = [str(h) for h in raw_highlights if h]
            score = getattr(result, "score", None)

            results.append(
                ExaSearchResult(
                    title=result.title or "",
                    url=result.url,
                    text=text,
                    score=float(score) if score is not None else 0.0,
                    highlights=highlights_list,
                    published_date=result.published_date,
                )
            )

        logger.info("exa_search_completed", extra={"result_count": len(results)})
        if span is not None:
            span.update(
                output={
                    "result_count": len(results),
                    "urls": [r.url for r in results[:5]],
                }
            )
        return results


def check_exa(settings: Settings) -> None:
    """Verify Exa API connectivity by making a minimal search request."""
    if not settings.exa_is_configured:
        raise ExaSearchError("Exa is not configured (disabled or missing API key).")

    try:
        client = _build_client(settings)
        client.search(query="ping", num_results=1, type="neural")
    except ExaSearchError:
        raise
    except Exception as exc:
        raise ExaSearchError(
            safe_error_detail(exc, fallback="Exa API connectivity check failed.")
        ) from exc
