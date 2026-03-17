from __future__ import annotations

import logging
from dataclasses import dataclass, field

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from sqlmodel import Session, desc, select

from app.agent.models import AnswerResult
from app.config import Settings
from app.db.models import Document, DocumentChunk
from app.observability import get_langfuse_client
from app.retrieval.context_builder import build_chunk_context
from app.retrieval.search import SearchResult
from app.retrieval.search import search_chunks as run_search_chunks

logger = logging.getLogger(__name__)


@dataclass
class QueryAgentDeps:
    session: Session
    settings: Settings
    document_ids: list[int]
    top_k: int
    search_results_by_id: dict[int, SearchResult] = field(default_factory=dict)
    fetched_chunks_by_id: dict[int, ChunkContextResult] = field(default_factory=dict)


class ListedDocument(BaseModel):
    id: int
    filename: str
    status: str
    page_count: int | None


class SearchChunkResult(BaseModel):
    chunk_id: int
    document_id: int
    filename: str
    page_number: int | None
    section_title: str | None
    text_excerpt: str
    similarity_score: float


class ChunkContextResult(BaseModel):
    chunk_id: int
    document_id: int
    filename: str
    page_number: int | None
    section_title: str | None
    text: str


class DocumentMetadataResult(BaseModel):
    document_id: int
    filename: str
    page_count: int | None
    status: str
    chunk_count: int


def register_query_tools(agent: Agent[QueryAgentDeps, AnswerResult]) -> None:
    @agent.tool
    def list_documents(ctx: RunContext[QueryAgentDeps]) -> list[ListedDocument]:
        logger.info("agent_tool_called", extra={"tool_name": "list_documents"})
        statement = select(Document).order_by(desc(Document.created_at), desc(Document.id))
        documents = ctx.deps.session.exec(statement).all()
        result = [
            ListedDocument(
                id=document.id,
                filename=document.filename,
                status=document.status,
                page_count=document.page_count,
            )
            for document in documents
            if document.id is not None
        ]
        client = get_langfuse_client(ctx.deps.settings)
        if client is not None:
            client.update_current_span(
                input={"tool_name": "list_documents"},
                output={
                    "document_count": len(result),
                    "document_ids": [document.id for document in result],
                },
            )
        return result

    @agent.tool
    def search_chunks(
        ctx: RunContext[QueryAgentDeps],
        query: str,
        document_ids: list[int] | None = None,
        top_k: int = 5,
    ) -> list[SearchChunkResult]:
        scoped_document_ids = _resolve_scoped_document_ids(
            requested_document_ids=document_ids,
            allowed_document_ids=ctx.deps.document_ids,
        )
        client = get_langfuse_client(ctx.deps.settings)
        if client is not None:
            client.update_current_span(
                input={
                    "document_ids": scoped_document_ids,
                    "top_k": max(1, min(top_k, 20)),
                    "query_length": len(query),
                }
            )
        if not scoped_document_ids:
            ctx.deps.search_results_by_id = {}
            ctx.deps.fetched_chunks_by_id = {}
            if client is not None:
                client.update_current_span(output={"result_count": 0})
            return []

        effective_top_k = max(1, min(top_k, 20))
        logger.info(
            "agent_tool_called",
            extra={
                "tool_name": "search_chunks",
                "document_count": len(scoped_document_ids),
                "top_k": effective_top_k,
                "query_length": len(query),
            },
        )
        results = run_search_chunks(
            session=ctx.deps.session,
            settings=ctx.deps.settings,
            query=query,
            document_ids=scoped_document_ids,
            top_k=effective_top_k,
        )
        ctx.deps.search_results_by_id = {result.chunk_id: result for result in results}
        ctx.deps.fetched_chunks_by_id = {}
        output = [
            SearchChunkResult(
                chunk_id=result.chunk_id,
                document_id=result.document_id,
                filename=result.filename,
                page_number=result.page_number,
                section_title=result.section_title,
                text_excerpt=result.text,
                similarity_score=result.similarity_score,
            )
            for result in results
        ]
        if client is not None:
            client.update_current_span(
                output={
                    "result_count": len(output),
                    "chunk_ids": [result.chunk_id for result in output],
                }
            )
        return output

    @agent.tool
    def fetch_chunk_context(
        ctx: RunContext[QueryAgentDeps],
        chunk_ids: list[int],
    ) -> list[ChunkContextResult]:
        client = get_langfuse_client(ctx.deps.settings)
        logger.info(
            "agent_tool_called",
            extra={"tool_name": "fetch_chunk_context", "requested_chunk_count": len(chunk_ids)},
        )
        if client is not None:
            client.update_current_span(input={"requested_chunk_ids": chunk_ids})
        allowed_chunk_ids = [
            chunk_id
            for chunk_id in chunk_ids
            if chunk_id in ctx.deps.search_results_by_id
        ]
        if not allowed_chunk_ids and ctx.deps.search_results_by_id:
            allowed_chunk_ids = list(ctx.deps.search_results_by_id)[: ctx.deps.top_k]
        if not allowed_chunk_ids:
            ctx.deps.fetched_chunks_by_id = {}
            return []

        records = load_chunk_context(
            session=ctx.deps.session,
            chunk_ids=allowed_chunk_ids,
            document_ids=ctx.deps.document_ids,
        )
        ctx.deps.fetched_chunks_by_id = {
            record.chunk_id: record for record in records
        }
        if client is not None:
            client.update_current_span(
                output={
                    "chunk_count": len(records),
                    "chunk_ids": [record.chunk_id for record in records],
                }
            )
        return records

    @agent.tool
    def get_document_metadata(
        ctx: RunContext[QueryAgentDeps],
        document_id: int,
    ) -> DocumentMetadataResult:
        client = get_langfuse_client(ctx.deps.settings)
        logger.info(
            "agent_tool_called",
            extra={"tool_name": "get_document_metadata", "document_id": document_id},
        )
        if client is not None:
            client.update_current_span(input={"document_id": document_id})
        document = ctx.deps.session.get(Document, document_id)
        if document is None or document.id is None:
            raise ValueError("Document not found.")

        chunk_count = len(
            ctx.deps.session.exec(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            ).all()
        )
        result = DocumentMetadataResult(
            document_id=document.id,
            filename=document.filename,
            page_count=document.page_count,
            status=document.status,
            chunk_count=chunk_count,
        )
        if client is not None:
            client.update_current_span(
                output={
                    "document_id": result.document_id,
                    "status": result.status,
                    "chunk_count": result.chunk_count,
                }
            )
        return result


def _resolve_scoped_document_ids(
    *,
    requested_document_ids: list[int] | None,
    allowed_document_ids: list[int],
) -> list[int]:
    allowed_set = set(allowed_document_ids)
    if not requested_document_ids:
        return allowed_document_ids
    return [
        document_id
        for document_id in dict.fromkeys(requested_document_ids)
        if document_id in allowed_set
    ]


def load_chunk_context(
    *,
    session: Session,
    chunk_ids: list[int],
    document_ids: list[int],
) -> list[ChunkContextResult]:
    rows = build_chunk_context(
        session=session,
        chunk_ids=chunk_ids,
        document_ids=document_ids,
    )
    return [
        ChunkContextResult(
            chunk_id=row.chunk_id,
            document_id=row.document_id,
            filename=row.filename,
            page_number=row.page_number,
            section_title=row.section_title,
            text=row.text,
        )
        for row in rows
    ]
