from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import time
from urllib.parse import urlparse

import httpx

from ..config import get_settings
from ..schemas import CellResult
from .base import BaseConnector, ConnectorContext, stable_hash
from .github import select_path


async def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute HTTP(S) URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed")
    records = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM
    )
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if not address.is_global:
            raise ValueError("Local, private, loopback, and link-local destinations are blocked")


class SafeHttpConnector(BaseConnector):
    name = "http"

    async def execute(self, context: ConnectorContext) -> CellResult:
        started = time.perf_counter()
        source_key = str(
            context.column.config.get(
                "source", context.column.depends_on[0] if context.column.depends_on else "url"
            )
        )
        url = context.row_values.get(source_key)
        if not isinstance(url, str):
            raise TypeError(f"HTTP source column {source_key} is empty")
        await validate_public_url(url)
        settings = get_settings()
        async with httpx.AsyncClient(timeout=settings.http_timeout_seconds, follow_redirects=False) as client:
            response = await client.get(url, headers={"User-Agent": "SourcedGrid/0.1"})
            response.raise_for_status()
            if int(response.headers.get("content-length", 0)) > settings.max_http_bytes:
                raise ValueError("HTTP response exceeds the configured size limit")
            payload = response.content[: settings.max_http_bytes + 1]
            if len(payload) > settings.max_http_bytes:
                raise ValueError("HTTP response exceeds the configured size limit")
            content_type = response.headers.get("content-type", "application/octet-stream").split(";")[0]
            if content_type == "application/json":
                parsed = response.json()
                value = select_path(parsed, str(context.column.config.get("select", "")))
                artifact_content: str | bytes = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
            elif content_type.startswith("text/"):
                value = response.text
                artifact_content = response.text
            else:
                value = {"content_type": content_type, "byte_size": len(payload)}
                artifact_content = payload
            return CellResult(
                value=value,
                connector=self.name,
                source_urls=[url],
                artifact_content=artifact_content,
                artifact_content_type=content_type,
                input_hash=stable_hash(url),
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
