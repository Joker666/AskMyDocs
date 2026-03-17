from __future__ import annotations

from app.ingestion.chunker import chunk_document, estimate_tokens
from app.ingestion.parser import ParsedBlock, ParsedDocument, ParsedPage


def build_parsed_document() -> ParsedDocument:
    page_one_text = " ".join(f"intro-{idx:03d}" for idx in range(120))
    page_two_text = " ".join(f"methods-{idx:03d}" for idx in range(120))
    return ParsedDocument(
        document_id=1,
        filename="sample.pdf",
        page_count=2,
        pages=[
            ParsedPage(
                page_number=1,
                section_title="Introduction",
                blocks=[ParsedBlock(text=page_one_text, section_title="Introduction")],
            ),
            ParsedPage(
                page_number=2,
                section_title="Methods",
                blocks=[ParsedBlock(text=page_two_text, section_title="Methods")],
            ),
        ],
    )


def test_estimate_tokens_is_deterministic() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_chunker_keeps_page_boundaries_and_indexes() -> None:
    parsed_document = build_parsed_document()

    chunks = chunk_document(document_id=1, parsed_document=parsed_document)

    assert chunks
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert {chunk.page_number for chunk in chunks} == {1, 2}
    assert all(chunk.metadata_json["page_number"] == chunk.page_number for chunk in chunks)


def test_chunker_preserves_section_titles_and_overlap() -> None:
    parsed_document = ParsedDocument(
        document_id=1,
        filename="sample.pdf",
        page_count=1,
        pages=[
            ParsedPage(
                page_number=1,
                section_title="Methods",
                blocks=[
                    ParsedBlock(
                        text=" ".join(f"token-{idx:03d}" for idx in range(220)),
                        section_title="Methods",
                    )
                ],
            )
        ],
    )

    chunks = chunk_document(document_id=1, parsed_document=parsed_document)

    assert len(chunks) >= 2
    assert all(chunk.section_title == "Methods" for chunk in chunks)
    assert chunks[0].text[-80:] in chunks[1].text
