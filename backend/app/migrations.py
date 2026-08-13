from __future__ import annotations

import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

from .config import get_settings


def migrate_database() -> Path | None:
    settings = get_settings()
    repository_root = Path(__file__).resolve().parents[2]
    config = Config(str(repository_root / "alembic.ini"))
    config.set_main_option("script_location", str(repository_root / "backend" / "alembic"))
    config.set_main_option("prepend_sys_path", str(repository_root / "backend"))
    head = ScriptDirectory.from_config(config).get_current_head()
    current = current_revision(settings.database_path)
    if current == head:
        return None
    backup = backup_sqlite_database(settings.database_path)
    try:
        command.upgrade(config, "head")
    except Exception as exc:
        restore = f"cp '{backup}' '{settings.database_path}'" if backup else "restore the database backup"
        raise RuntimeError(f"Database migration failed. Stop services and run: {restore}") from exc
    return backup


def current_revision(database_path: Path) -> str | None:
    if not database_path.exists() or database_path.stat().st_size == 0:
        return None
    try:
        with sqlite3.connect(database_path) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
        return str(row[0]) if row else None
    except sqlite3.Error:
        return None


def backup_sqlite_database(database_path: Path) -> Path | None:
    if not database_path.exists() or database_path.stat().st_size == 0:
        return None
    backup_dir = database_path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    destination = backup_dir / f"{database_path.stem}-{stamp}.db"
    try:
        source = sqlite3.connect(database_path)
        target = sqlite3.connect(destination)
        with target:
            source.backup(target)
        source.close()
        target.close()
    except sqlite3.Error:
        destination.unlink(missing_ok=True)
        shutil.copy2(database_path, destination)
    return destination
