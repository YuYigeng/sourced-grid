from __future__ import annotations

import math
import re
import time
from datetime import UTC, datetime
from typing import Any

from ..schemas import CellResult
from .base import BaseConnector, ConnectorContext, stable_hash
from .github import parse_repository, select_path


class TransformConnector(BaseConnector):
    name = "transform"

    async def execute(self, context: ConnectorContext) -> CellResult:
        started = time.perf_counter()
        operation = str(context.column.config.get("operation", "select"))
        source_key = str(
            context.column.config.get(
                "source", context.column.depends_on[0] if context.column.depends_on else ""
            )
        )
        source = context.row_values.get(source_key)
        if operation == "canonical_repository":
            owner, repo = parse_repository(str(source))
            value: Any = f"{owner}/{repo}"
        elif operation == "select":
            value = select_path(source, str(context.column.config.get("path", "")))
        elif operation == "primary_language":
            languages = select_path(source, "languages") or {}
            value = max(languages, key=languages.get) if languages else None
        elif operation == "latest_release":
            releases = select_path(source, "releases") or []
            value = releases[0].get("published_at") if releases else None
        elif operation == "activity_summary":
            issues = select_path(source, "issues") or []
            pulls = select_path(source, "pulls") or []
            value = {"recent_issues": len(issues), "recent_pull_requests": len(pulls)}
        elif operation == "health_score":
            value = health_score(source or {})
        elif operation == "regex":
            pattern = str(context.column.config.get("pattern", ""))
            match = re.search(pattern, str(source))
            value = match.group(int(context.column.config.get("group", 0))) if match else None
        else:
            raise ValueError(f"Unknown transform operation: {operation}")
        return CellResult(
            value=value,
            connector=self.name,
            input_hash=stable_hash({"operation": operation, "source": source}),
            duration_ms=int((time.perf_counter() - started) * 1000),
        )


def health_score(snapshot: dict[str, Any]) -> int:
    repo = snapshot.get("repository", {})
    releases = snapshot.get("releases", [])
    pulls = snapshot.get("pulls", [])
    score = 35
    pushed_at = repo.get("pushed_at")
    if pushed_at:
        try:
            pushed = datetime.fromisoformat(str(pushed_at))
            days = max(0, (datetime.now(UTC) - pushed).days)
            score += max(0, 25 - min(25, math.floor(days / 14)))
        except ValueError:
            pass
    if releases:
        score += 15
    if pulls:
        score += min(15, len(pulls))
    if repo.get("license"):
        score += 5
    if not repo.get("archived"):
        score += 5
    return max(0, min(100, score))
