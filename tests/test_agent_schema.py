from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.agent.models import AnswerResult, Citation


def test_answer_result_accepts_valid_citation() -> None:
    result = AnswerResult(
        answer="The title appears in the first page.",
        citations=[
            Citation(
                document_id=1,
                chunk_id=2,
                filename="paper.pdf",
                page_number=1,
                section_title="Overview",
                quote="The title is shown here.",
            )
        ],
        confidence=0.75,
    )

    assert result.citations[0].chunk_id == 2
    assert result.confidence == 0.75


def test_answer_result_rejects_confidence_out_of_bounds() -> None:
    with pytest.raises(ValidationError):
        AnswerResult(answer="x", citations=[], confidence=1.5)


def test_citation_requires_non_empty_quote() -> None:
    with pytest.raises(ValidationError):
        Citation(
            document_id=1,
            chunk_id=2,
            filename="paper.pdf",
            page_number=1,
            section_title=None,
            quote="",
        )
