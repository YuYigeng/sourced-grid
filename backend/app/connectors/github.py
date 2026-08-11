from __future__ import annotations

import base64
import json
import re
import time
from typing import Any

import httpx

from ..config import get_settings
from ..schemas import CellResult
from .base import BaseConnector, ConnectorContext, stable_hash

REPO_PATTERN = re.compile(
    r"^(?:https?://github\.com/)?(?P<owner>[A-Za-z0-9_.-]+)/(?P<repo>[A-Za-z0-9_.-]+?)(?:\.git)?/?$"
)


def parse_repository(value: str) -> tuple[str, str]:
    match = REPO_PATTERN.match(value.strip())
    if not match:
        raise ValueError(f"Not a GitHub repository: {value}")
    return match.group("owner"), match.group("repo")


class GitHubConnector(BaseConnector):
    name = "github"

    async def execute(self, context: ConnectorContext) -> CellResult:
        started = time.perf_counter()
        source_key = str(
            context.column.config.get(
                "source", context.column.depends_on[0] if context.column.depends_on else "repo_url"
            )
        )
        source_value = context.row_values.get(source_key)
        if not isinstance(source_value, str):
            raise TypeError(f"GitHub source column {source_key} is empty")
        owner, repo = parse_repository(source_value)
        token = context.vault.get(context.session, "github_token")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SourcedGrid/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        base = f"https://api.github.com/repos/{owner}/{repo}"
        settings = get_settings()
        async with httpx.AsyncClient(
            headers=headers, timeout=settings.http_timeout_seconds, follow_redirects=False
        ) as client:
            repo_data = await self._get(client, base)
            resource = str(context.column.config.get("resource", "snapshot"))
            if resource == "repository":
                payload: Any = repo_data
                urls = [str(repo_data.get("html_url", f"https://github.com/{owner}/{repo}"))]
            else:
                readme, releases, languages, issues, pulls = await self._snapshot_parts(client, base)
                payload = {
                    "repository": repo_data,
                    "readme": readme,
                    "releases": releases,
                    "languages": languages,
                    "issues": [item for item in issues if "pull_request" not in item],
                    "pulls": pulls,
                }
                urls = [
                    str(repo_data.get("html_url", f"https://github.com/{owner}/{repo}")),
                    f"https://github.com/{owner}/{repo}/releases",
                    f"https://github.com/{owner}/{repo}/issues",
                    f"https://github.com/{owner}/{repo}/pulls",
                ]
            selected = select_path(payload, str(context.column.config.get("select", "")))
            artifact = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
            return CellResult(
                value=selected,
                connector=self.name,
                source_urls=urls,
                artifact_content=artifact,
                artifact_content_type="application/json",
                input_hash=stable_hash(source_value),
                duration_ms=int((time.perf_counter() - started) * 1000),
                metadata={
                    "repository": f"{owner}/{repo}",
                    "rate_limit_remaining": client.headers.get("x-ratelimit-remaining"),
                },
            )

    async def _snapshot_parts(
        self, client: httpx.AsyncClient, base: str
    ) -> tuple[str, list, dict, list, list]:
        readme_response = await client.get(f"{base}/readme")
        if readme_response.status_code == 404:
            readme = ""
        else:
            self._raise(readme_response)
            encoded = readme_response.json().get("content", "")
            readme = base64.b64decode(encoded).decode("utf-8", errors="replace") if encoded else ""
        releases = await self._get(client, f"{base}/releases?per_page=10")
        languages = await self._get(client, f"{base}/languages")
        issues = await self._get(client, f"{base}/issues?state=all&sort=updated&per_page=30")
        pulls = await self._get(client, f"{base}/pulls?state=all&sort=updated&direction=desc&per_page=30")
        return readme[:100_000], releases, languages, issues, pulls

    async def _get(self, client: httpx.AsyncClient, url: str) -> Any:
        response = await client.get(url)
        self._raise(response)
        return response.json()

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise PermissionError("GitHub token was rejected")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            raise RuntimeError("GitHub rate limit exhausted; add a token or retry after reset")
        if response.status_code == 404:
            raise FileNotFoundError("GitHub repository or resource was not found")
        response.raise_for_status()


def select_path(value: Any, path: str) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            current = current[int(part)]
        else:
            return None
    return current
