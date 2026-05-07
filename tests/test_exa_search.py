from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.retrieval.exa_search import (
    ExaSearchError,
    ExaSearchResult,
    check_exa,
    search_exa,
)


def _make_settings(**overrides: Any) -> MagicMock:
    """Build a minimal mock Settings with Exa fields."""
    from unittest.mock import PropertyMock

    defaults: dict[str, Any] = {
        "exa_enabled": True,
        "exa_search_type": "auto",
        "exa_num_results": 5,
        "exa_weight": 0.5,
    }
    defaults.update(overrides)

    settings = MagicMock()
    for key, value in defaults.items():
        setattr(settings, key, value)

    # exa_api_key needs .get_secret_value()
    if "exa_api_key" not in overrides:
        settings.exa_api_key.get_secret_value.return_value = "test-key"
    else:
        api_key = overrides["exa_api_key"]
        if api_key is None:
            settings.exa_api_key = None
        else:
            settings.exa_api_key.get_secret_value.return_value = api_key

    # exa_is_configured property
    type(settings).exa_is_configured = PropertyMock(
        return_value=defaults.get("exa_enabled", True) and settings.exa_api_key is not None
    )

    return settings


def _make_exa_result(**overrides: Any) -> MagicMock:
    """Build a mock Exa search result object."""
    defaults = {
        "title": "Test Result",
        "url": "https://example.com/test",
        "text": "This is the full text of the test result.",
        "highlights": ["relevant highlight"],
        "score": 0.95,
        "published_date": "2025-01-15T00:00:00.000Z",
    }
    defaults.update(overrides)
    result = MagicMock()
    for key, value in defaults.items():
        setattr(result, key, value)
    return result


class TestSearchExa:
    @patch("app.retrieval.exa_search._build_client")
    def test_returns_structured_results(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client

        mock_response = MagicMock()
        mock_response.results = [
            _make_exa_result(title="First", url="https://a.com", score=0.9),
            _make_exa_result(title="Second", url="https://b.com", score=0.8),
        ]
        mock_client.search.return_value = mock_response

        settings = _make_settings()
        results = search_exa(settings=settings, query="test query")

        assert len(results) == 2
        assert isinstance(results[0], ExaSearchResult)
        assert results[0].title == "First"
        assert results[0].url == "https://a.com"
        assert results[0].score == 0.9
        assert results[1].title == "Second"

    @patch("app.retrieval.exa_search._build_client")
    def test_uses_settings_defaults(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        mock_client.search.return_value = MagicMock(results=[])

        settings = _make_settings(exa_num_results=3, exa_search_type="neural")
        search_exa(settings=settings, query="test")

        mock_client.search.assert_called_once_with(
            query="test",
            type="neural",
            num_results=3,
            text=True,
            highlights=True,
        )

    @patch("app.retrieval.exa_search._build_client")
    def test_num_results_override(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        mock_client.search.return_value = MagicMock(results=[])

        settings = _make_settings(exa_num_results=5)
        search_exa(settings=settings, query="test", num_results=10)

        mock_client.search.assert_called_once_with(
            query="test",
            type="auto",
            num_results=10,
            text=True,
            highlights=True,
        )

    @patch("app.retrieval.exa_search._build_client")
    def test_handles_missing_optional_fields(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client

        result = _make_exa_result(
            title=None,
            text=None,
            highlights=None,
            score=None,
            published_date=None,
        )
        mock_client.search.return_value = MagicMock(results=[result])

        settings = _make_settings()
        results = search_exa(settings=settings, query="test")

        assert len(results) == 1
        assert results[0].title == ""
        assert results[0].text == ""
        assert results[0].highlights == []
        assert results[0].score == 0.0
        assert results[0].published_date is None

    @patch("app.retrieval.exa_search._build_client")
    def test_empty_results(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        mock_client.search.return_value = MagicMock(results=[])

        settings = _make_settings()
        results = search_exa(settings=settings, query="nothing relevant")

        assert results == []

    @patch("app.retrieval.exa_search._build_client")
    def test_wraps_api_errors(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        mock_client.search.side_effect = RuntimeError("API timeout")

        settings = _make_settings()
        with pytest.raises(ExaSearchError):
            search_exa(settings=settings, query="fail")

    def test_raises_when_no_api_key(self) -> None:
        settings = _make_settings(exa_api_key=None)
        with pytest.raises(ExaSearchError, match="not configured"):
            search_exa(settings=settings, query="test")


class TestCheckExa:
    @patch("app.retrieval.exa_search._build_client")
    def test_health_check_passes(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        mock_client.search.return_value = MagicMock(results=[])

        settings = _make_settings()
        check_exa(settings)

        mock_client.search.assert_called_once_with(
            query="ping", num_results=1, type="neural"
        )

    def test_health_check_fails_when_not_configured(self) -> None:
        settings = _make_settings()
        type(settings).exa_is_configured = property(lambda _: False)

        with pytest.raises(ExaSearchError, match="not configured"):
            check_exa(settings)

    @patch("app.retrieval.exa_search._build_client")
    def test_health_check_wraps_errors(self, mock_build: MagicMock) -> None:
        mock_client = MagicMock()
        mock_build.return_value = mock_client
        mock_client.search.side_effect = ConnectionError("unreachable")

        settings = _make_settings()
        with pytest.raises(ExaSearchError):
            check_exa(settings)
