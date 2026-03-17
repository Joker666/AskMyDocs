from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from app.ingestion.parser import ParsedDocument, ParsedPage

CHUNK_TARGET_CHARS = 800
CHUNK_MIN_CHARS = 500
CHUNK_OVERLAP_CHARS = 120


@dataclass(frozen=True)
class ChunkPayload:
    document_id: int
    chunk_index: int
    page_number: int | None
    section_title: str | None
    text: str
    token_estimate: int
    metadata_json: dict[str, object]


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return ceil(len(text) / 4)


def chunk_document(*, document_id: int, parsed_document: ParsedDocument) -> list[ChunkPayload]:
    chunks: list[ChunkPayload] = []
    chunk_index = 0

    for page in parsed_document.pages:
        for section_title, text in _iter_page_segments(page):
            for chunk_text in _split_text(text):
                metadata = {
                    "source_filename": parsed_document.filename,
                    "chunk_index": chunk_index,
                    "page_number": page.page_number,
                    "section_title": section_title,
                }
                chunks.append(
                    ChunkPayload(
                        document_id=document_id,
                        chunk_index=chunk_index,
                        page_number=page.page_number,
                        section_title=section_title,
                        text=chunk_text,
                        token_estimate=estimate_tokens(chunk_text),
                        metadata_json=metadata,
                    )
                )
                chunk_index += 1

    return chunks


def _iter_page_segments(page: ParsedPage) -> list[tuple[str | None, str]]:
    segments: list[tuple[str | None, str]] = []
    current_section = page.section_title
    current_parts: list[str] = []

    for block in page.blocks:
        block_text = block.text.strip()
        if not block_text:
            continue

        block_section = block.section_title or current_section or page.section_title
        if current_parts and block_section != current_section:
            segment_text = "\n\n".join(current_parts).strip()
            if segment_text:
                segments.append((current_section, segment_text))
            current_parts = [block_text]
            current_section = block_section
            continue

        current_section = current_section or block_section
        current_parts.append(block_text)

    if current_parts:
        segment_text = "\n\n".join(current_parts).strip()
        if segment_text:
            segments.append((current_section, segment_text))

    return segments


def _split_text(text: str) -> list[str]:
    chunks: list[str] = []
    start = 0
    text_length = len(text)

    while start < text_length:
        max_end = min(text_length, start + CHUNK_TARGET_CHARS)
        end = _find_split_end(text, start, max_end)
        chunk_text = text[start:end].strip()
        if chunk_text:
            chunks.append(chunk_text)

        if end >= text_length:
            break

        next_start = max(start, end - CHUNK_OVERLAP_CHARS)
        while next_start < text_length and text[next_start].isspace():
            next_start += 1
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks


def _find_split_end(text: str, start: int, max_end: int) -> int:
    if max_end >= len(text):
        return len(text)

    min_break = min(len(text), start + CHUNK_MIN_CHARS)
    if min_break >= max_end:
        return max_end

    for separator in ("\n\n", "\n", " "):
        index = text.rfind(separator, min_break, max_end)
        if index != -1:
            return index

    return max_end
