from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DATA = Path(tempfile.mkdtemp(prefix="sourcedgrid-tests-"))
os.environ["SOURCEDGRID_DATA_DIR"] = str(TEST_DATA)
os.environ["SOURCEDGRID_CORS_ORIGINS"] = "http://testserver"
