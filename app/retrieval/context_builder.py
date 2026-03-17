from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from sqlmodel import Session, select

from app.db.models import Document, DocumentChunk

DEFAULT_CONTEXT_WINDOW = 1


@dataclass(frozen=True)
class ContextChunkRecord:
    """Normalized chunk payload used while assembling answer context windows."""

    chunk_id: int
    document_id: int
    filename: str
    chunk_index: int
    page_number: int | None
    section_title: str | None
    text: str


def build_chunk_context(
    *,
    session: Session,
    chunk_ids: list[int],
    document_ids: list[int],
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> list[ContextChunkRecord]:
    """Expand selected chunk IDs into a local same-document context window.

    This is the repository's main context-engineering step after semantic search.
    Retrieval first finds the most similar chunks. This function then widens that
    sparse result set into a more readable local passage by including nearby chunks
    from the same document, using chunk_index adjacency rather than another model
    call or another semantic ranking pass.

    The flow is:
    1. Load only the requested chunk IDs, scoped to allowed document IDs.
    2. Preserve the caller's chunk order so the downstream agent sees context in
       the order implied by the search/tool response.
    3. Load candidate chunks for the involved documents.
    4. Expand each selected chunk by +/- context_window chunk indexes.
    5. Deduplicate overlapping windows while preserving stable first-seen order.

    Important constraints:
    - Context expansion never crosses document boundaries.
    - Chunks not returned by the current retrieval step are ignored.
    - The default window is intentionally small for the MVP: one neighboring
      chunk on each side when available.
    """
    if not chunk_ids or not document_ids:
        return []

    selected_rows = _load_context_rows_for_chunk_ids(
        session=session,
        chunk_ids=chunk_ids,
        document_ids=document_ids,
    )
    if not selected_rows:
        return []

    selected_by_id = {row.chunk_id: row for row in selected_rows}
    ordered_selected = [
        selected_by_id[chunk_id]
        for chunk_id in chunk_ids
        if chunk_id in selected_by_id
    ]
    if not ordered_selected:
        return []

    involved_document_ids = list({row.document_id for row in ordered_selected})
    candidate_rows = _load_context_rows_for_documents(
        session=session,
        document_ids=involved_document_ids,
    )
    return expand_context_window(
        selected_chunks=ordered_selected,
        candidate_chunks=candidate_rows,
        context_window=context_window,
    )


def expand_context_window(
    *,
    selected_chunks: list[ContextChunkRecord],
    candidate_chunks: list[ContextChunkRecord],
    context_window: int = DEFAULT_CONTEXT_WINDOW,
) -> list[ContextChunkRecord]:
    """Return a deduplicated +/- N chunk window around each selected chunk.

    This function performs local adjacency expansion only. It does not rerank,
    rescore, summarize, or compress content. The assumption is that the chunk
    next to a relevant hit is often useful supporting context, especially when a
    section or paragraph boundary was split by chunking.

    Ordering behavior matters:
    - candidate_chunks are grouped and sorted by chunk_index per document
    - selected_chunks are processed in the order given by the caller
    - overlapping windows are merged by first appearance

    The result is therefore stable and predictable for prompting:
    the agent gets contiguous local context around each hit without duplicates
    and without mixing chunks from different documents.
    """
    if not selected_chunks or not candidate_chunks:
        return []

    chunks_by_document: dict[int, list[ContextChunkRecord]] = {}
    for chunk in candidate_chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)

    for chunks in chunks_by_document.values():
        chunks.sort(key=lambda chunk: chunk.chunk_index)

    expanded_chunks: list[ContextChunkRecord] = []
    seen_chunk_ids: set[int] = set()

    for selected in selected_chunks:
        document_chunks = chunks_by_document.get(selected.document_id, [])
        lower_bound = selected.chunk_index - max(0, context_window)
        upper_bound = selected.chunk_index + max(0, context_window)
        for chunk in document_chunks:
            if chunk.chunk_index < lower_bound or chunk.chunk_index > upper_bound:
                continue
            if chunk.chunk_id in seen_chunk_ids:
                continue
            expanded_chunks.append(chunk)
            seen_chunk_ids.add(chunk.chunk_id)

    return expanded_chunks


def _load_context_rows_for_chunk_ids(
    *,
    session: Session,
    chunk_ids: list[int],
    document_ids: list[int],
) -> list[ContextChunkRecord]:
    """Load only the chunks explicitly selected by retrieval/tool output.

    This scoped lookup is the guardrail that prevents arbitrary chunk IDs from
    becoming answer context. By joining back to Document and filtering by the
    allowed document_ids, the function ensures later context expansion starts
    from chunks that belong to the current query scope.
    """
    chunk_id_column = cast(Any, DocumentChunk.id)
    document_id_column = cast(Any, DocumentChunk.document_id)
    chunk_index_column = cast(Any, DocumentChunk.chunk_index)
    columns: tuple[Any, ...] = (
        chunk_id_column,
        document_id_column,
        cast(Any, Document.filename),
        chunk_index_column,
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
        ContextChunkRecord(
            chunk_id=chunk_id,
            document_id=document_id,
            filename=filename,
            chunk_index=chunk_index,
            page_number=page_number,
            section_title=section_title,
            text=text,
        )
        for chunk_id, document_id, filename, chunk_index, page_number, section_title, text in rows
        if chunk_id is not None
    ]


def _load_context_rows_for_documents(
    *,
    session: Session,
    document_ids: list[int],
) -> list[ContextChunkRecord]:
    """Load all candidate chunks for the documents involved in this answer.

    The caller uses this broader document-local set to expand around selected
    hits by chunk_index. For the MVP this keeps the implementation simple and
    makes window expansion deterministic, at the cost of loading more rows than
    strictly necessary for large documents.
    """
    document_id_column = cast(Any, DocumentChunk.document_id)
    chunk_index_column = cast(Any, DocumentChunk.chunk_index)
    columns: tuple[Any, ...] = (
        cast(Any, DocumentChunk.id),
        document_id_column,
        cast(Any, Document.filename),
        chunk_index_column,
        cast(Any, DocumentChunk.page_number),
        cast(Any, DocumentChunk.section_title),
        cast(Any, DocumentChunk.text),
    )
    statement = (
        select(*columns)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(document_id_column.in_(document_ids))
        .order_by(document_id_column, chunk_index_column)
    )
    rows = session.exec(statement).all()
    return [
        ContextChunkRecord(
            chunk_id=chunk_id,
            document_id=document_id,
            filename=filename,
            chunk_index=chunk_index,
            page_number=page_number,
            section_title=section_title,
            text=text,
        )
        for chunk_id, document_id, filename, chunk_index, page_number, section_title, text in rows
        if chunk_id is not None
    ]
