from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import psycopg

from app.config import Settings, get_settings


@dataclass(frozen=True)
class Migration:
    name: str
    path: Path


def list_migrations(migrations_dir: Path) -> list[Migration]:
    return [
        Migration(name=path.name, path=path)
        for path in sorted(migrations_dir.glob("*.sql"))
        if path.is_file()
    ]


def ensure_migration_table(connection: psycopg.Connection) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )


def applied_migrations(connection: psycopg.Connection) -> set[str]:
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM schema_migrations")
        return {row[0] for row in cursor.fetchall()}


def apply_migration(connection: psycopg.Connection, migration: Migration) -> None:
    migration_sql = migration.path.read_text(encoding="utf-8")
    with connection.cursor() as cursor:
        cursor.execute(cast(Any, migration_sql))
        cursor.execute(
            "INSERT INTO schema_migrations (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
            (migration.name,),
        )


def run_migrations(settings: Settings) -> None:
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    migrations = list_migrations(migrations_dir)

    if not migrations:
        raise RuntimeError(f"No migration files found in {migrations_dir}")

    with psycopg.connect(settings.migration_database_url) as connection:
        ensure_migration_table(connection)
        applied = applied_migrations(connection)

        for migration in migrations:
            if migration.name in applied:
                continue
            apply_migration(connection, migration)

        connection.commit()


def main() -> None:
    run_migrations(get_settings())


if __name__ == "__main__":
    main()
