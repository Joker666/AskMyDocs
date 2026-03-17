from __future__ import annotations

import logging
from typing import Any, cast

from pydantic_ai import AgentRunError, ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from app.agent.agent import build_query_agent
from app.agent.models import AnswerResult
from app.agent.tools import QueryAgentDeps
from app.config import Settings
from app.db.models import Document
from app.db.schemas import QueryRequest, QueryResponse
from app.ingestion.embedder import OllamaNativeError
from app.retrieval.search import search_chunks
from app.runtime import safe_error_detail

logger = logging.getLogger(__name__)

NO_QUERYABLE_DOCUMENTS_MESSAGE = "No ready documents are available for querying."
NO_RELEVANT_CHUNKS_ANSWER = "I couldn't find relevant information in the indexed documents."


class QueryServiceError(Exception):
    """Base exception for query service failures."""


class QueryDocumentNotFoundError(QueryServiceError):
    """Raised when a requested document does not exist."""


class QueryDocumentConflictError(QueryServiceError):
    """Raised when a requested document cannot be queried."""


class QueryAgentError(QueryServiceError):
    """Raised when the query agent cannot return a valid response."""


class QueryDependencyError(QueryServiceError):
    """Raised when a live dependency fails during querying."""


def query_documents(
    *,
    session: Session,
    settings: Settings,
    request: QueryRequest,
    model_override: Model | None = None,
) -> QueryResponse:
    try:
        document_ids = _resolve_queryable_document_ids(
            session=session,
            requested_document_ids=request.document_ids,
        )
    except SQLAlchemyError as exc:
        detail = safe_error_detail(exc, fallback="Query document lookup failed.")
        logger.warning("query_failed", extra={"stage": "document_lookup", "detail": detail})
        raise QueryDependencyError(detail) from exc
    logger.info(
        "query_started",
        extra={
            "document_count": len(document_ids),
            "top_k": request.top_k,
            "question_length": len(request.question),
        },
    )

    try:
        retrieval_results = search_chunks(
            session=session,
            settings=settings,
            query=request.question,
            document_ids=document_ids,
            top_k=request.top_k,
        )
    except (OllamaNativeError, SQLAlchemyError) as exc:
        detail = safe_error_detail(exc, fallback="Query retrieval failed.")
        logger.warning(
            "query_failed",
            extra={"stage": "retrieval", "detail": detail, "document_count": len(document_ids)},
        )
        raise QueryDependencyError(detail) from exc
    if not retrieval_results:
        logger.info(
            "query_completed",
            extra={"document_count": len(document_ids), "result": "no_hits"},
        )
        return QueryResponse(
            answer=NO_RELEVANT_CHUNKS_ANSWER,
            citations=[],
            confidence=0.0,
        )

    answer = run_query_agent(
        session=session,
        settings=settings,
        question=request.question,
        document_ids=document_ids,
        top_k=request.top_k,
        model_override=model_override,
    )
    logger.info(
        "query_completed",
        extra={
            "document_count": len(document_ids),
            "citation_count": len(answer.citations),
            "confidence": answer.confidence,
        },
    )
    return QueryResponse(
        answer=answer.answer,
        citations=answer.citations,
        confidence=answer.confidence,
    )


def run_query_agent(
    *,
    session: Session,
    settings: Settings,
    question: str,
    document_ids: list[int],
    top_k: int,
    model_override: Model | None = None,
) -> AnswerResult:
    agent = build_query_agent(settings, model=model_override)
    deps = QueryAgentDeps(
        session=session,
        settings=settings,
        document_ids=document_ids,
        top_k=top_k,
    )
    try:
        result = agent.run_sync(question, deps=deps)
    except (OllamaNativeError, SQLAlchemyError) as exc:
        detail = safe_error_detail(exc, fallback="Query agent dependencies failed.")
        logger.warning("query_failed", extra={"stage": "agent_dependencies", "detail": detail})
        raise QueryDependencyError(detail) from exc
    except (ModelHTTPError, ModelAPIError, UnexpectedModelBehavior, AgentRunError) as exc:
        detail = safe_error_detail(
            exc,
            fallback="Query agent failed to produce a valid grounded answer.",
        )
        logger.warning("query_failed", extra={"stage": "agent", "detail": detail})
        raise QueryAgentError(
            detail
        ) from exc
    except Exception as exc:
        detail = safe_error_detail(exc, fallback="Query agent request failed.")
        logger.warning("query_failed", extra={"stage": "agent", "detail": detail})
        raise QueryAgentError(detail) from exc

    output = result.output
    if not isinstance(output, AnswerResult):
        raise QueryAgentError("Query agent returned an unexpected output shape.")
    return output


def _resolve_queryable_document_ids(
    *,
    session: Session,
    requested_document_ids: list[int] | None,
) -> list[int]:
    if requested_document_ids:
        deduped_document_ids = list(dict.fromkeys(requested_document_ids))
        document_id_column = cast(Any, Document.id)
        documents = session.exec(
            select(Document).where(document_id_column.in_(deduped_document_ids))
        ).all()
        documents_by_id = {
            document.id: document for document in documents if document.id is not None
        }
        missing_document_ids = [
            document_id
            for document_id in deduped_document_ids
            if document_id not in documents_by_id
        ]
        if missing_document_ids:
            raise QueryDocumentNotFoundError("Requested document was not found.")

        unready_documents = [
            document
            for document_id in deduped_document_ids
            if (document := documents_by_id[document_id]).status != "ready"
        ]
        if unready_documents:
            raise QueryDocumentConflictError("Requested document is not ready for querying.")

        return deduped_document_ids

    ready_documents = session.exec(select(Document).where(Document.status == "ready")).all()
    ready_document_ids = [
        document.id for document in ready_documents if document.id is not None
    ]
    if not ready_document_ids:
        raise QueryDocumentConflictError(NO_QUERYABLE_DOCUMENTS_MESSAGE)

    return ready_document_ids
