from __future__ import annotations

import argparse
import shutil
from collections.abc import Sequence
from pathlib import Path

import psycopg

from app.config import get_settings


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Reset local AskMyDocs data.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the destructive database reset.",
    )
    parser.add_argument(
        "--delete-artifacts",
        action="store_true",
        help="Also remove files under UPLOAD_DIR and PARSED_DIR.",
    )
    return parser.parse_args(argv)


def _remove_directory_contents(path: Path) -> int:
    if not path.exists():
        return 0

    removed = 0
    for child in path.iterdir():
        if child.name == ".gitkeep":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
        removed += 1
    return removed


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.yes:
        print("Refusing to reset without --yes.")
        return 2

    settings = get_settings()

    with psycopg.connect(settings.migration_database_url) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                TRUNCATE TABLE
                    ingestion_jobs,
                    document_chunks,
                    documents
                RESTART IDENTITY CASCADE
                """
            )
        connection.commit()

    print("Reset database tables: documents, document_chunks, ingestion_jobs.")

    if args.delete_artifacts:
        uploads_removed = _remove_directory_contents(Path(settings.upload_dir))
        parsed_removed = _remove_directory_contents(Path(settings.parsed_dir))
        print(
            "Removed local artifacts: "
            f"uploads={uploads_removed} parsed={parsed_removed}."
        )
    else:
        print("Kept local upload and parsed artifacts.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
