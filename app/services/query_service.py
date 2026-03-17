from __future__ import annotations

import logging
from typing import Any, cast

from pydantic_ai import AgentRunError, ModelAPIError, ModelHTTPError, UnexpectedModelBehavior
from pydantic_ai.models import Model
from sqlmodel import Session, select

from app.agent.agent import build_query_agent
from app.agent.models import AnswerResult
from app.agent.tools import QueryAgentDeps
from app.config import Settings
from app.db.models import Document
from app.db.schemas import QueryRequest, QueryResponse
from app.retrieval.search import search_chunks

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


def _short_error(message: str) -> str:
    return message.strip().splitlines()[0][:200]


def query_documents(
    *,
    session: Session,
    settings: Settings,
    request: QueryRequest,
    model_override: Model | None = None,
) -> QueryResponse:
    document_ids = _resolve_queryable_document_ids(
        session=session,
        requested_document_ids=request.document_ids,
    )
    logger.info(
        "query_started documents=%s top_k=%s question_length=%s",
        len(document_ids),
        request.top_k,
        len(request.question),
    )

    retrieval_results = search_chunks(
        session=session,
        settings=settings,
        query=request.question,
        document_ids=document_ids,
        top_k=request.top_k,
    )
    if not retrieval_results:
        logger.info("query_completed documents=%s result=no_hits", len(document_ids))
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
        "query_completed documents=%s citations=%s confidence=%s",
        len(document_ids),
        len(answer.citations),
        answer.confidence,
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
    except (ModelHTTPError, ModelAPIError, UnexpectedModelBehavior, AgentRunError) as exc:
        raise QueryAgentError(
            _short_error(str(exc) or "Query agent failed to produce a valid grounded answer.")
        ) from exc
    except Exception as exc:
        raise QueryAgentError(_short_error(str(exc) or "Query agent request failed.")) from exc

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
