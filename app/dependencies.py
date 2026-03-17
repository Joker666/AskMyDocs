from __future__ import annotations

from collections.abc import Generator

from sqlmodel import Session

from app.config import Settings, get_settings
from app.db.session import get_engine


def get_app_settings() -> Settings:
    return get_settings()


def get_db_session(settings: Settings | None = None) -> Generator[Session]:
    resolved_settings = settings or get_settings()
    engine = get_engine(resolved_settings)
    with Session(engine) as session:
        yield session
