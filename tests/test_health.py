from __future__ import annotations

from typing import Any, cast

from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import Settings
from app.dependencies import get_app_settings
from app.main import app


def make_settings() -> Settings:
    settings_cls = cast(Any, Settings)
    return settings_cls(
        POSTGRES_HOST="localhost",
        POSTGRES_DB="askmydocs",
        POSTGRES_USER="postgres",
        POSTGRES_PASSWORD=SecretStr("postgres"),
    )


def test_health_success(monkeypatch) -> None:
    def fake_db_check(_settings) -> None:
        return None

    def fake_ollama_native_check(_settings) -> None:
        return None

    monkeypatch.setattr("app.api.routes_health.check_database_connection", fake_db_check)
    monkeypatch.setattr("app.api.routes_health.check_ollama_native", fake_ollama_native_check)
    app.dependency_overrides[get_app_settings] = make_settings

    client = TestClient(app)
    try:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "checks": {
                "app": {"status": "ok", "detail": None},
                "db": {"status": "ok", "detail": None},
                "anthropic_compat": {"status": "not_checked", "detail": None},
                "ollama_native": {"status": "ok", "detail": None},
            },
        }
    finally:
        app.dependency_overrides.clear()


def test_health_db_failure(monkeypatch) -> None:
    def fake_db_check(_settings) -> None:
        raise RuntimeError("database unavailable")

    def fake_ollama_native_check(_settings) -> None:
        return None

    monkeypatch.setattr("app.api.routes_health.check_database_connection", fake_db_check)
    monkeypatch.setattr("app.api.routes_health.check_ollama_native", fake_ollama_native_check)
    app.dependency_overrides[get_app_settings] = make_settings

    client = TestClient(app)
    try:
        response = client.get("/health")

        assert response.status_code == 503
        assert response.json() == {
            "status": "degraded",
            "checks": {
                "app": {"status": "ok", "detail": None},
                "db": {"status": "error", "detail": "database unavailable"},
                "anthropic_compat": {"status": "not_checked", "detail": None},
                "ollama_native": {"status": "ok", "detail": None},
            },
        }
    finally:
        app.dependency_overrides.clear()


def test_health_ollama_native_failure(monkeypatch) -> None:
    def fake_db_check(_settings) -> None:
        return None

    def fake_ollama_native_check(_settings) -> None:
        raise RuntimeError("embedding model missing")

    monkeypatch.setattr("app.api.routes_health.check_database_connection", fake_db_check)
    monkeypatch.setattr("app.api.routes_health.check_ollama_native", fake_ollama_native_check)
    app.dependency_overrides[get_app_settings] = make_settings

    client = TestClient(app)
    try:
        response = client.get("/health")

        assert response.status_code == 503
        assert response.json() == {
            "status": "degraded",
            "checks": {
                "app": {"status": "ok", "detail": None},
                "db": {"status": "ok", "detail": None},
                "anthropic_compat": {"status": "not_checked", "detail": None},
                "ollama_native": {"status": "error", "detail": "embedding model missing"},
            },
        }
    finally:
        app.dependency_overrides.clear()
