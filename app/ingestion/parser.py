from __future__ import annotations

from pathlib import Path

from docling.datamodel.base_models import ConversionStatus
from docling.document_converter import DocumentConverter
from docling_core.types.doc.document import SectionHeaderItem, TextItem
from pydantic import BaseModel, Field

from app.runtime import safe_error_detail


class ParsedBlock(BaseModel):
    text: str
    section_title: str | None = None


class ParsedPage(BaseModel):
    page_number: int
    section_title: str | None = None
    blocks: list[ParsedBlock] = Field(default_factory=list)


class ParsedDocument(BaseModel):
    document_id: int
    filename: str
    page_count: int
    pages: list[ParsedPage] = Field(default_factory=list)


class DocumentParseError(Exception):
    """Raised when a document cannot be parsed into the internal representation."""
def parse_document(*, document_id: int, filename: str, source_path: str | Path) -> ParsedDocument:
    path = Path(source_path)
    if not path.exists():
        raise DocumentParseError("Document source file is missing.")

    try:
        result = DocumentConverter().convert(path, raises_on_error=True)
    except Exception as exc:  # pragma: no cover - exercised via integration and monkeypatch paths
        raise DocumentParseError(
            safe_error_detail(exc, fallback="Docling parsing failed.")
        ) from exc

    if result.status != ConversionStatus.SUCCESS:
        message = "Docling parsing failed."
        if result.errors:
            message = safe_error_detail(
                result.errors[0].error_message,
                fallback="Docling parsing failed.",
            )
        raise DocumentParseError(message)

    parsed = _normalize_docling_document(
        document_id=document_id,
        filename=filename,
        page_count=max(len(result.document.pages), len(result.pages)),
        document=result.document,
    )

    if parsed.page_count == 0:
        raise DocumentParseError("Parsed document has no pages.")

    return parsed


def _normalize_docling_document(
    *,
    document_id: int,
    filename: str,
    page_count: int,
    document,
) -> ParsedDocument:
    pages_by_number = {
        page_number: ParsedPage(page_number=page_number)
        for page_number in range(1, page_count + 1)
    }
    current_section_title: str | None = None

    for item, _ in document.iterate_items(with_groups=False):
        if not isinstance(item, TextItem):
            continue

        text = item.text.strip()
        if not text:
            continue

        page_number = item.prov[0].page_no if item.prov else 1
        page = pages_by_number.setdefault(page_number, ParsedPage(page_number=page_number))

        if isinstance(item, SectionHeaderItem):
            current_section_title = text

        block_section_title = current_section_title
        if page.section_title is None and block_section_title is not None:
            page.section_title = block_section_title

        page.blocks.append(ParsedBlock(text=text, section_title=block_section_title))

    return ParsedDocument(
        document_id=document_id,
        filename=filename,
        page_count=page_count,
        pages=[pages_by_number[page_number] for page_number in sorted(pages_by_number)],
    )
