from __future__ import annotations

import base64
import json
import random
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

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
    version = "4"

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
        token = context.secrets.get("github_token")
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "SourcedGrid/0.1",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if context.prior_etag:
            headers["If-None-Match"] = context.prior_etag
        base = f"https://api.github.com/repos/{owner}/{repo}"
        settings = get_settings()
        async with httpx.AsyncClient(
            headers=headers, timeout=settings.http_timeout_seconds, follow_redirects=False
        ) as client:
            rate_metadata: dict[str, Any] = {}
            repo_data = await self._get(client, base, rate_metadata, etag_key="repository_etag")
            resource = str(context.column.config.get("resource", "snapshot"))
            if resource == "repository":
                payload: Any = repo_data
                urls = [str(repo_data.get("html_url", f"https://github.com/{owner}/{repo}"))]
            else:
                readme, releases, languages, issues, pulls = await self._snapshot_parts(
                    client, base, rate_metadata
                )
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
                    **rate_metadata,
                    "activity_window": "latest 30 issues and latest 30 pull requests by updated_at",
                },
            )

    async def _snapshot_parts(
        self, client: httpx.AsyncClient, base: str, rate_metadata: dict[str, Any]
    ) -> tuple[str, list, dict, list, list]:
        readme_response = await self._safe_get(client, f"{base}/readme")
        if readme_response.status_code == 404:
            readme = ""
        else:
            self._capture_rate(readme_response, rate_metadata, etag_key="readme_etag")
            self._raise(readme_response)
            encoded = readme_response.json().get("content", "")
            readme = base64.b64decode(encoded).decode("utf-8", errors="replace") if encoded else ""
        releases = await self._get_optional(
            client, f"{base}/releases?per_page=10", rate_metadata, []
        )
        languages = await self._get_optional(client, f"{base}/languages", rate_metadata, {})
        issues = await self._get_optional(
            client,
            f"{base}/issues?state=all&sort=updated&per_page=30",
            rate_metadata,
            [],
        )
        pulls = await self._get_optional(
            client,
            f"{base}/pulls?state=all&sort=updated&direction=desc&per_page=30",
            rate_metadata,
            [],
        )
        return readme[:100_000], releases, languages, issues, pulls

    async def _get(
        self,
        client: httpx.AsyncClient,
        url: str,
        rate_metadata: dict[str, Any],
        *,
        etag_key: str | None = None,
    ) -> Any:
        response = await self._safe_get(client, url)
        self._capture_rate(response, rate_metadata, etag_key=etag_key)
        self._raise(response)
        return response.json()

    async def _get_optional(
        self,
        client: httpx.AsyncClient,
        url: str,
        rate_metadata: dict[str, Any],
        default: Any,
    ) -> Any:
        response = await self._safe_get(client, url)
        self._capture_rate(response, rate_metadata)
        if response.status_code == 404:
            unavailable = rate_metadata.setdefault("unavailable_resources", [])
            unavailable.append(str(response.request.url))
            return default
        self._raise(response)
        return response.json()

    @staticmethod
    async def _safe_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
        current = url
        for _ in range(3):
            response = await client.get(current)
            if response.status_code not in {301, 302, 307, 308}:
                return response
            location = response.headers.get("location")
            if not location:
                return response
            redirected = urljoin(str(response.request.url), location)
            parsed = urlparse(redirected)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "api.github.com"
                or parsed.username
                or parsed.password
            ):
                raise PermissionError("GitHub API redirect target is not trusted")
            current = redirected
        raise RuntimeError("GitHub API returned too many redirects")

    @staticmethod
    def _capture_rate(
        response: httpx.Response,
        target: dict[str, Any],
        *,
        etag_key: str | None = None,
    ) -> None:
        target.update(
            rate_limit_remaining=response.headers.get("x-ratelimit-remaining"),
            rate_limit_reset=response.headers.get("x-ratelimit-reset"),
            retry_after=response.headers.get("retry-after"),
        )
        if etag_key:
            target[etag_key] = response.headers.get("etag")

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.status_code == 304:
            raise GitHubNotModified
        if response.status_code == 401:
            raise PermissionError("GitHub token was rejected")
        if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
            reset = response.headers.get("x-ratelimit-reset")
            retry_after = response.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                retry_at = datetime.now(UTC).timestamp() + int(retry_after)
            elif reset and reset.isdigit():
                retry_at = float(reset)
            else:
                retry_at = datetime.now(UTC).timestamp() + 60
            raise GitHubRateLimitError(retry_at + random.uniform(0.5, 3.0))
        if response.status_code == 404:
            raise FileNotFoundError("GitHub repository or resource was not found")
        response.raise_for_status()


class GitHubRateLimitError(RuntimeError):
    def __init__(self, retry_at_epoch: float) -> None:
        super().__init__("GitHub rate limit exhausted; the task will resume after reset")
        self.retry_at = datetime.fromtimestamp(retry_at_epoch, UTC)


class GitHubNotModified(RuntimeError):
    pass


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
