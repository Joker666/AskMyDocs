from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import psycopg
import pytest
from pydantic import SecretStr
from sqlmodel import Session, delete

from app.config import Settings
from app.db.models import Document, DocumentChunk, IngestionJob
from app.db.session import get_engine
from app.ingestion.embedder import OllamaNativeError, embed_texts
from app.retrieval.search import search_chunks


def make_settings() -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
    )


@pytest.fixture
def retrieval_environment():
    settings = make_settings()

    try:
        with psycopg.connect(settings.migration_database_url):
            pass
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not available for retrieval tests: {exc}")

    engine = get_engine(settings)
    with Session(engine) as session:
        session.exec(delete(IngestionJob))
        session.exec(delete(DocumentChunk))
        session.exec(delete(Document))
        session.commit()

    yield settings, engine

    with Session(engine) as session:
        session.exec(delete(IngestionJob))
        session.exec(delete(DocumentChunk))
        session.exec(delete(Document))
        session.commit()


def _vector(*components: float, dimension: int) -> list[float]:
    vector = [0.0] * dimension
    for index, value in enumerate(components):
        vector[index] = value
    return vector


def _seed_document(
    *,
    session: Session,
    filename: str,
    checksum: str,
    status: str = "ready",
) -> Document:
    now = datetime.now(UTC)
    document = Document(
        filename=filename,
        file_path=f"./data/uploads/{checksum}.pdf",
        checksum=checksum,
        page_count=1,
        status=status,
        created_at=now,
        updated_at=now,
    )
    session.add(document)
    session.commit()
    session.refresh(document)
    return document


def _document_id(document: Document) -> int:
    assert document.id is not None
    return document.id


def test_search_chunks_orders_by_similarity(retrieval_environment, monkeypatch) -> None:
    settings, engine = retrieval_environment

    def fake_embed_texts(texts: list[str], _settings: Settings) -> list[list[float]]:
        assert texts == ["question"]
        return [_vector(1.0, 0.0, dimension=settings.embedding_dimension)]

    monkeypatch.setattr("app.retrieval.search.embed_texts", fake_embed_texts)

    with Session(engine) as session:
        first_document = _seed_document(session=session, filename="alpha.pdf", checksum="alpha")
        second_document = _seed_document(session=session, filename="beta.pdf", checksum="beta")
        first_document_id = _document_id(first_document)
        second_document_id = _document_id(second_document)

        session.add(
            DocumentChunk(
                document_id=first_document_id,
                chunk_index=0,
                page_number=1,
                section_title="Overview",
                text="Exact match chunk",
                token_estimate=4,
                metadata_json={},
                embedding=_vector(1.0, 0.0, dimension=settings.embedding_dimension),
            )
        )
        session.add(
            DocumentChunk(
                document_id=second_document_id,
                chunk_index=0,
                page_number=1,
                section_title="Overview",
                text="Close match chunk",
                token_estimate=4,
                metadata_json={},
                embedding=_vector(0.8, 0.2, dimension=settings.embedding_dimension),
            )
        )
        session.add(
            DocumentChunk(
                document_id=second_document_id,
                chunk_index=1,
                page_number=1,
                section_title="Appendix",
                text="Far match chunk",
                token_estimate=4,
                metadata_json={},
                embedding=_vector(0.0, 1.0, dimension=settings.embedding_dimension),
            )
        )
        session.commit()

        results = search_chunks(session=session, settings=settings, query="question", top_k=3)

    assert [result.text for result in results] == [
        "Exact match chunk",
        "Close match chunk",
        "Far match chunk",
    ]
    assert results[0].similarity_score > results[1].similarity_score > results[2].similarity_score


def test_search_chunks_respects_top_k_and_document_filters(
    retrieval_environment,
    monkeypatch,
) -> None:
    settings, engine = retrieval_environment

    def fake_embed_texts(_texts: list[str], _settings: Settings) -> list[list[float]]:
        return [_vector(1.0, 0.0, dimension=settings.embedding_dimension)]

    monkeypatch.setattr("app.retrieval.search.embed_texts", fake_embed_texts)

    with Session(engine) as session:
        first_document = _seed_document(session=session, filename="keep.pdf", checksum="keep")
        second_document = _seed_document(session=session, filename="drop.pdf", checksum="drop")
        first_document_id = _document_id(first_document)
        second_document_id = _document_id(second_document)

        session.add(
            DocumentChunk(
                document_id=first_document_id,
                chunk_index=0,
                page_number=1,
                section_title=None,
                text="Filtered chunk",
                token_estimate=3,
                metadata_json={},
                embedding=_vector(1.0, 0.0, dimension=settings.embedding_dimension),
            )
        )
        session.add(
            DocumentChunk(
                document_id=second_document_id,
                chunk_index=0,
                page_number=1,
                section_title=None,
                text="Unfiltered chunk",
                token_estimate=3,
                metadata_json={},
                embedding=_vector(0.9, 0.1, dimension=settings.embedding_dimension),
            )
        )
        session.commit()

        filtered = search_chunks(
            session=session,
            settings=settings,
            query="question",
            document_ids=[first_document_id],
            top_k=1,
        )

    assert len(filtered) == 1
    assert filtered[0].text == "Filtered chunk"
    assert filtered[0].document_id == first_document_id


def test_search_chunks_excludes_null_embeddings(retrieval_environment, monkeypatch) -> None:
    settings, engine = retrieval_environment

    def fake_embed_texts(_texts: list[str], _settings: Settings) -> list[list[float]]:
        return [_vector(1.0, 0.0, dimension=settings.embedding_dimension)]

    monkeypatch.setattr("app.retrieval.search.embed_texts", fake_embed_texts)

    with Session(engine) as session:
        document = _seed_document(session=session, filename="sample.pdf", checksum="sample")
        document_id = _document_id(document)
        session.add(
            DocumentChunk(
                document_id=document_id,
                chunk_index=0,
                page_number=1,
                section_title=None,
                text="Embedded chunk",
                token_estimate=3,
                metadata_json={},
                embedding=_vector(1.0, 0.0, dimension=settings.embedding_dimension),
            )
        )
        session.add(
            DocumentChunk(
                document_id=document_id,
                chunk_index=1,
                page_number=1,
                section_title=None,
                text="Missing embedding",
                token_estimate=3,
                metadata_json={},
                embedding=None,
            )
        )
        session.commit()

        results = search_chunks(session=session, settings=settings, query="question", top_k=5)

    assert [result.text for result in results] == ["Embedded chunk"]


@pytest.mark.integration
def test_live_embed_texts_returns_configured_dimension() -> None:
    settings = make_settings()

    try:
        embeddings = embed_texts(["hello from integration test"], settings)
    except OllamaNativeError as exc:
        pytest.skip(f"Ollama not available for integration test: {exc}")

    assert len(embeddings) == 1
    assert len(embeddings[0]) == settings.embedding_dimension
