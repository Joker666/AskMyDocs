from __future__ import annotations

from sqlmodel import create_engine

from app.config import Settings

_cached_engine = None
_cached_engine_url: str | None = None


def get_engine(settings: Settings):
    global _cached_engine, _cached_engine_url

    if _cached_engine is None or _cached_engine_url != settings.database_url:
        _cached_engine = create_engine(
            settings.database_url,
            pool_pre_ping=True,
        )
        _cached_engine_url = settings.database_url

    return _cached_engine


def check_database_connection(settings: Settings) -> None:
    engine = get_engine(settings)
    with engine.connect() as connection:
        connection.exec_driver_sql("SELECT 1")
