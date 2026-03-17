from __future__ import annotations

from app.retrieval.context_builder import ContextChunkRecord, expand_context_window


def _chunk(
    *,
    chunk_id: int,
    document_id: int,
    chunk_index: int,
    text: str,
) -> ContextChunkRecord:
    return ContextChunkRecord(
        chunk_id=chunk_id,
        document_id=document_id,
        filename=f"doc-{document_id}.pdf",
        chunk_index=chunk_index,
        page_number=1,
        section_title=None,
        text=text,
    )


def test_expand_context_window_includes_adjacent_chunks_for_selected_hit() -> None:
    selected = [_chunk(chunk_id=2, document_id=1, chunk_index=1, text="middle")]
    candidates = [
        _chunk(chunk_id=1, document_id=1, chunk_index=0, text="before"),
        _chunk(chunk_id=2, document_id=1, chunk_index=1, text="middle"),
        _chunk(chunk_id=3, document_id=1, chunk_index=2, text="after"),
        _chunk(chunk_id=4, document_id=1, chunk_index=3, text="too-far"),
    ]

    expanded = expand_context_window(
        selected_chunks=selected,
        candidate_chunks=candidates,
        context_window=1,
    )

    assert [chunk.chunk_id for chunk in expanded] == [1, 2, 3]


def test_expand_context_window_deduplicates_overlapping_windows() -> None:
    selected = [
        _chunk(chunk_id=2, document_id=1, chunk_index=1, text="middle-a"),
        _chunk(chunk_id=3, document_id=1, chunk_index=2, text="middle-b"),
    ]
    candidates = [
        _chunk(chunk_id=1, document_id=1, chunk_index=0, text="before"),
        _chunk(chunk_id=2, document_id=1, chunk_index=1, text="middle-a"),
        _chunk(chunk_id=3, document_id=1, chunk_index=2, text="middle-b"),
        _chunk(chunk_id=4, document_id=1, chunk_index=3, text="after"),
    ]

    expanded = expand_context_window(
        selected_chunks=selected,
        candidate_chunks=candidates,
        context_window=1,
    )

    assert [chunk.chunk_id for chunk in expanded] == [1, 2, 3, 4]


def test_expand_context_window_does_not_cross_documents() -> None:
    selected = [_chunk(chunk_id=2, document_id=1, chunk_index=1, text="middle")]
    candidates = [
        _chunk(chunk_id=1, document_id=1, chunk_index=0, text="before"),
        _chunk(chunk_id=2, document_id=1, chunk_index=1, text="middle"),
        _chunk(chunk_id=3, document_id=2, chunk_index=2, text="other-doc"),
    ]

    expanded = expand_context_window(
        selected_chunks=selected,
        candidate_chunks=candidates,
        context_window=1,
    )

    assert [chunk.chunk_id for chunk in expanded] == [1, 2]
