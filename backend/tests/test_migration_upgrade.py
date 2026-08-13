from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from app.migrations import backup_sqlite_database

ROOT = Path(__file__).resolve().parents[2]


def run_alembic(database_url: str, revision: str) -> None:
    environment = {**os.environ, "SOURCEDGRID_DATABASE_URL": database_url}
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
        cwd=ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def test_upgrade_from_35a_fixture_preserves_research_artifact_and_secret(tmp_path: Path) -> None:
    database = tmp_path / "legacy.db"
    url = f"sqlite:///{database}"
    run_alembic(url, "35a3bdad004e")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO grids VALUES (:id, 'Legacy', 'kept', NULL, :at, :at)"),
            {"id": "grid", "at": "2026-01-01 00:00:00"},
        )
        connection.execute(
            text(
                "INSERT INTO column_definitions VALUES "
                "('column', 'grid', 'repo', 'Repo', 'input', 0, 160, '[]', '{}', NULL, '{}', :at, :at)"
            ),
            {"at": "2026-01-01 00:00:00"},
        )
        connection.execute(
            text("INSERT INTO grid_rows VALUES ('row', 'grid', 0, :at, :at)"),
            {"at": "2026-01-01 00:00:00"},
        )
        connection.execute(
            text(
                "INSERT INTO cells VALUES "
                "('cell', 'row', 'column', 'succeeded', '\"preserved\"', NULL, 'cache', :at, :at)"
            ),
            {"at": "2026-01-01 00:00:00"},
        )
        connection.execute(
            text(
                "INSERT INTO artifacts VALUES "
                "('hash', 'ha/sh/hash', 'application/json', 10, :at)"
            ),
            {"at": "2026-01-01 00:00:00"},
        )
        connection.execute(
            text(
                "INSERT INTO provenance VALUES "
                "('provenance', 'cell', 'input', '[]', 'hash', NULL, NULL, NULL, 0, 0, 0, 0, 0, '{}', :at)"
            ),
            {"at": "2026-01-01 00:00:00"},
        )
        connection.execute(
            text(
                "INSERT INTO encrypted_secrets VALUES "
                "('secret', 'github_token', 'ciphertext', :at, :at)"
            ),
            {"at": "2026-01-01 00:00:00"},
        )
    backup = backup_sqlite_database(database)
    assert backup and backup.exists()
    run_alembic(url, "head")
    with engine.connect() as connection:
        execution = connection.execute(
            text("SELECT status, value FROM cell_executions WHERE cell_id='cell'")
        ).one()
        assert execution.status == "succeeded"
        assert "preserved" in execution.value
        assert connection.execute(text("SELECT COUNT(*) FROM artifacts WHERE hash='hash'")).scalar() == 1
        assert connection.execute(text("SELECT COUNT(*) FROM encrypted_secrets WHERE id='secret'")).scalar() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM provenance WHERE execution_id IS NOT NULL")
        ).scalar() == 1
        provider_columns = {
            row[1] for row in connection.execute(text("PRAGMA table_info(provider_profiles)"))
        }
        assert {"structured_output_mode", "default_temperature"} <= provider_columns
