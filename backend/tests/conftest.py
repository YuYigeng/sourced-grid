from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

TEST_DATA = Path(tempfile.mkdtemp(prefix="sourcedgrid-tests-"))
os.environ["SOURCEDGRID_DATA_DIR"] = str(TEST_DATA)
os.environ["SOURCEDGRID_CORS_ORIGINS"] = "http://testserver"


def pytest_sessionstart(session) -> None:
    del session
    from app.migrations import migrate_database

    migrate_database()
