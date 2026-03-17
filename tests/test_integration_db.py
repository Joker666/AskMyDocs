from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import psycopg
import pytest
from pydantic import SecretStr

from app.config import Settings


def make_settings() -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
    )


@pytest.mark.integration
def test_bootstrap_migration_applies_required_tables() -> None:
    settings = make_settings()
    try:
        with psycopg.connect(settings.migration_database_url) as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                assert cursor.fetchone() == ("vector",)

                cursor.execute("SELECT to_regclass('public.documents')")
                assert cursor.fetchone() == ("documents",)

                cursor.execute("SELECT to_regclass('public.document_chunks')")
                assert cursor.fetchone() == ("document_chunks",)

                cursor.execute("SELECT to_regclass('public.ingestion_jobs')")
                assert cursor.fetchone() == ("ingestion_jobs",)
    except psycopg.OperationalError as exc:
        pytest.skip(f"Postgres not available for integration test: {exc}")


def test_bootstrap_migration_file_exists() -> None:
    migration_path = Path("migrations/001_bootstrap.sql")

    assert migration_path.exists()
