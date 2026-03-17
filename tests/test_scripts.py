from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent


def load_script_module(name: str, relative_path: str) -> ModuleType:
    path = ROOT / relative_path
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ingest_sample_returns_error_when_pdf_is_missing(tmp_path) -> None:
    module = load_script_module("ingest_sample_missing", "scripts/ingest_sample.py")

    exit_code = module.main([str(tmp_path / "missing.pdf")])

    assert exit_code == 1


def test_ingest_sample_optionally_runs_query(tmp_path, monkeypatch) -> None:
    module = load_script_module("ingest_sample_success", "scripts/ingest_sample.py")
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.calls: list[tuple[str, str, object]] = []
            self.detail_calls = 0

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, path: str, files=None, json=None):
            self.calls.append(("POST", path, json if json is not None else files))
            if path == "/documents/upload":
                return FakeResponse({"document": {"id": 7}})
            if path == "/documents/7/ingest":
                return FakeResponse({"job_id": 3, "status": "pending"})
            if path == "/query":
                return FakeResponse({"answer": "ok", "citations": [], "confidence": 0.0})
            raise AssertionError(f"Unexpected POST path: {path}")

        def get(self, path: str):
            self.calls.append(("GET", path, None))
            assert path == "/documents/7"
            self.detail_calls += 1
            return FakeResponse(
                {
                    "id": 7,
                    "latest_ingestion": {"status": "completed"},
                }
            )

    fake_client = FakeClient()
    monkeypatch.setattr(module.httpx, "Client", lambda *args, **kwargs: fake_client)

    exit_code = module.main([str(pdf_path), "--question", "What happened?"])

    assert exit_code == 0
    assert [call[:2] for call in fake_client.calls] == [
        ("POST", "/documents/upload"),
        ("POST", "/documents/7/ingest"),
        ("GET", "/documents/7"),
        ("POST", "/query"),
    ]


def test_reset_db_requires_yes_flag() -> None:
    module = load_script_module("reset_db_requires_yes", "scripts/reset_db.py")

    exit_code = module.main([])

    assert exit_code == 2


def test_reset_db_deletes_artifacts_when_requested(tmp_path, monkeypatch) -> None:
    module = load_script_module("reset_db_delete_artifacts", "scripts/reset_db.py")
    upload_dir = tmp_path / "uploads"
    parsed_dir = tmp_path / "parsed"
    upload_dir.mkdir()
    parsed_dir.mkdir()
    (upload_dir / "one.pdf").write_text("x", encoding="utf-8")
    (parsed_dir / "one.json").write_text("x", encoding="utf-8")
    (upload_dir / ".gitkeep").write_text("", encoding="utf-8")

    class FakeCursor:
        def __init__(self):
            self.statements: list[str] = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def execute(self, statement: str) -> None:
            self.statements.append(statement)

    class FakeConnection:
        def __init__(self):
            self.cursor_instance = FakeCursor()
            self.committed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def cursor(self) -> FakeCursor:
            return self.cursor_instance

        def commit(self) -> None:
            self.committed = True

    fake_connection = FakeConnection()
    monkeypatch.setattr(
        module,
        "get_settings",
        lambda: SimpleNamespace(
            migration_database_url="postgresql://example",
            upload_dir=str(upload_dir),
            parsed_dir=str(parsed_dir),
        ),
    )
    monkeypatch.setattr(module.psycopg, "connect", lambda _url: fake_connection)

    exit_code = module.main(["--yes", "--delete-artifacts"])

    assert exit_code == 0
    assert fake_connection.committed is True
    assert len(fake_connection.cursor_instance.statements) == 1
    assert list(upload_dir.iterdir()) == [upload_dir / ".gitkeep"]
    assert list(parsed_dir.iterdir()) == []
