from __future__ import annotations

import math
import re
import time
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

from ..schemas import CellResult
from .base import BaseConnector, ConnectorContext, stable_hash
from .github import parse_repository, select_path


class TransformConnector(BaseConnector):
    name = "transform"
    version = "2"

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
            timestamps = [
                item.get("updated_at")
                for item in [*issues, *pulls]
                if isinstance(item, dict) and item.get("updated_at")
            ]
            value = {
                "recent_issues_sample": len(issues),
                "recent_pull_requests_sample": len(pulls),
                "window_start": min(timestamps) if timestamps else None,
                "window_end": max(timestamps) if timestamps else None,
                "sampling": "latest 30 items per resource; not a complete activity count",
            }
        elif operation == "health_score":
            score, components = health_score_detail(source or {})
            value = {"score": score, "algorithm_version": "health-v1", "components": components}
        elif operation == "html_to_text":
            parser = MainTextParser()
            parser.feed(str(source or ""))
            value = {
                "title": parser.title.strip() or None,
                "text": "\n".join(line for line in parser.lines if line)[:100_000],
                "updated_at": parser.updated_at,
            }
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


def health_score_detail(snapshot: dict[str, Any]) -> tuple[int, dict[str, int]]:
    repo = snapshot.get("repository", {})
    releases = snapshot.get("releases", [])
    pulls = snapshot.get("pulls", [])
    components = {"baseline": 35, "recency": 0, "release": 0, "pull_requests": 0, "license": 0, "active": 0}
    pushed_at = repo.get("pushed_at")
    if pushed_at:
        try:
            pushed = datetime.fromisoformat(str(pushed_at))
            days = max(0, (datetime.now(UTC) - pushed).days)
            components["recency"] = max(0, 25 - min(25, math.floor(days / 14)))
        except ValueError:
            pass
    if releases:
        components["release"] = 15
    if pulls:
        components["pull_requests"] = min(15, len(pulls))
    if repo.get("license"):
        components["license"] = 5
    if not repo.get("archived"):
        components["active"] = 5
    return max(0, min(100, sum(components.values()))), components


def health_score(snapshot: dict[str, Any]) -> int:
    return health_score_detail(snapshot)[0]


class MainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self.title = ""
        self.updated_at: str | None = None
        self._hidden = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag in {"script", "style", "svg", "noscript"}:
            self._hidden += 1
        self._in_title = tag == "title"
        if tag == "meta":
            key = attributes.get("property") or attributes.get("name")
            if key in {"article:modified_time", "last-modified", "dateModified"}:
                self.updated_at = attributes.get("content")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "svg", "noscript"} and self._hidden:
            self._hidden -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._hidden:
            return
        normalized = " ".join(data.split())
        if not normalized:
            return
        if self._in_title:
            self.title += normalized
        self.lines.append(normalized)
