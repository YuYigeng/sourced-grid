from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlparse

import httpcore
import httpx

from ..config import get_settings
from ..schemas import CellResult
from .base import BaseConnector, ConnectorContext, stable_hash
from .github import select_path


async def resolve_public_url(url: str) -> tuple[str, tuple[str, ...]]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only absolute HTTP(S) URLs are supported")
    if parsed.username or parsed.password:
        raise ValueError("URLs containing credentials are not allowed")
    default_port = 443 if parsed.scheme == "https" else 80
    records = await asyncio.to_thread(
        socket.getaddrinfo, parsed.hostname, parsed.port or default_port, type=socket.SOCK_STREAM
    )
    return parsed.hostname, public_ip_addresses(records)


def public_ip_addresses(records: list[tuple]) -> tuple[str, ...]:
    addresses: list[str] = []
    for record in records:
        address = ipaddress.ip_address(record[4][0])
        if not address.is_global:
            raise ValueError("Local, private, loopback, and link-local destinations are blocked")
        addresses.append(str(address))
    return tuple(dict.fromkeys(addresses))


async def validate_public_url(url: str) -> None:
    await resolve_public_url(url)


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    """Resolve once, then connect only to the validated address set."""

    def __init__(self, host: str, addresses: tuple[str, ...]) -> None:
        self.host = host
        self.addresses = addresses
        self.backend = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        if host != self.host:
            raise httpcore.ConnectError("Unvalidated destination")
        last_error: Exception | None = None
        for address in self.addresses:
            try:
                return await self.backend.connect_tcp(
                    address, port, timeout, local_address, socket_options
                )
            except Exception as exc:  # noqa: BLE001 - try every validated address
                last_error = exc
        if last_error:
            raise last_error
        raise httpcore.ConnectError("No validated destination")

    async def connect_unix_socket(self, path: str, timeout=None, socket_options=None):
        raise httpcore.ConnectError("Unix sockets are not allowed")

    async def sleep(self, seconds: float) -> None:
        await self.backend.sleep(seconds)


async def pinned_transport(url: str) -> httpx.AsyncHTTPTransport:
    host, addresses = await resolve_public_url(url)
    transport = httpx.AsyncHTTPTransport(trust_env=False)
    transport._pool = httpcore.AsyncConnectionPool(
        ssl_context=ssl.create_default_context(),
        network_backend=PinnedNetworkBackend(host, addresses),
        max_connections=10,
        max_keepalive_connections=5,
    )
    return transport


class SafeHttpConnector(BaseConnector):
    name = "http"
    version = "2"

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
        transport = await pinned_transport(url)
        settings = get_settings()
        async with httpx.AsyncClient(
            timeout=settings.http_timeout_seconds,
            follow_redirects=False,
            transport=transport,
            trust_env=False,
        ) as client:
            async with client.stream("GET", url, headers={"User-Agent": "SourcedGrid/0.1"}) as response:
                response.raise_for_status()
                if int(response.headers.get("content-length", 0)) > settings.max_http_bytes:
                    raise ValueError("HTTP response exceeds the configured size limit")
                chunks: list[bytes] = []
                size = 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > settings.max_http_bytes:
                        raise ValueError("HTTP response exceeds the configured size limit")
                    chunks.append(chunk)
                payload = b"".join(chunks)
            content_type = response.headers.get("content-type", "application/octet-stream").split(";")[0]
            if content_type == "application/json":
                parsed = json.loads(payload)
                value = select_path(parsed, str(context.column.config.get("select", "")))
                artifact_content: str | bytes = json.dumps(parsed, ensure_ascii=False, sort_keys=True)
            elif content_type.startswith("text/"):
                charset = response.encoding or "utf-8"
                value = payload.decode(charset, errors="replace")
                artifact_content = value
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
