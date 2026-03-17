from __future__ import annotations

from typing import Any, cast

from pydantic import SecretStr

from app.config import Settings
from app.db.session import get_engine


def make_settings() -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
    )


def test_get_engine_is_lazy_and_uses_settings_url() -> None:
    settings = make_settings()

    engine = get_engine(settings)

    assert engine.url.render_as_string(hide_password=False) == settings.database_url
