from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, cast

from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from sqlmodel import Session, desc, select

from app.agent.models import AnswerResult
from app.config import Settings
from app.db.models import Document, DocumentChunk
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
        logger.info("agent_tool_called name=list_documents")
        statement = select(Document).order_by(desc(Document.created_at), desc(Document.id))
        documents = ctx.deps.session.exec(statement).all()
        return [
            ListedDocument(
                id=document.id,
                filename=document.filename,
                status=document.status,
                page_count=document.page_count,
            )
            for document in documents
            if document.id is not None
        ]

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
        if not scoped_document_ids:
            ctx.deps.search_results_by_id = {}
            ctx.deps.fetched_chunks_by_id = {}
            return []

        effective_top_k = max(1, min(top_k, 20))
        logger.info(
            "agent_tool_called name=search_chunks documents=%s top_k=%s",
            len(scoped_document_ids),
            effective_top_k,
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
        return [
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

    @agent.tool
    def fetch_chunk_context(
        ctx: RunContext[QueryAgentDeps],
        chunk_ids: list[int],
    ) -> list[ChunkContextResult]:
        logger.info("agent_tool_called name=fetch_chunk_context requested=%s", len(chunk_ids))
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

        records = _load_chunk_context(
            session=ctx.deps.session,
            chunk_ids=allowed_chunk_ids,
            document_ids=ctx.deps.document_ids,
        )
        records_by_id = {record.chunk_id: record for record in records}
        ordered_records = [
            records_by_id[chunk_id]
            for chunk_id in allowed_chunk_ids
            if chunk_id in records_by_id
        ]
        ctx.deps.fetched_chunks_by_id = {
            record.chunk_id: record for record in ordered_records
        }
        return ordered_records

    @agent.tool
    def get_document_metadata(
        ctx: RunContext[QueryAgentDeps],
        document_id: int,
    ) -> DocumentMetadataResult:
        logger.info("agent_tool_called name=get_document_metadata document_id=%s", document_id)
        document = ctx.deps.session.get(Document, document_id)
        if document is None or document.id is None:
            raise ValueError("Document not found.")

        chunk_count = len(
            ctx.deps.session.exec(
                select(DocumentChunk).where(DocumentChunk.document_id == document_id)
            ).all()
        )
        return DocumentMetadataResult(
            document_id=document.id,
            filename=document.filename,
            page_count=document.page_count,
            status=document.status,
            chunk_count=chunk_count,
        )


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


def _load_chunk_context(
    *,
    session: Session,
    chunk_ids: list[int],
    document_ids: list[int],
) -> list[ChunkContextResult]:
    chunk_id_column = cast(Any, DocumentChunk.id)
    document_id_column = cast(Any, DocumentChunk.document_id)
    columns: tuple[Any, ...] = (
        chunk_id_column,
        document_id_column,
        cast(Any, Document.filename),
        cast(Any, DocumentChunk.page_number),
        cast(Any, DocumentChunk.section_title),
        cast(Any, DocumentChunk.text),
    )
    statement = (
        select(*columns)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(chunk_id_column.in_(chunk_ids))
        .where(document_id_column.in_(document_ids))
    )
    rows = session.exec(statement).all()
    return [
        ChunkContextResult(
            chunk_id=chunk_id,
            document_id=document_id,
            filename=filename,
            page_number=page_number,
            section_title=section_title,
            text=text,
        )
        for chunk_id, document_id, filename, page_number, section_title, text in rows
        if chunk_id is not None
    ]
