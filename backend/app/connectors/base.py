from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from ..schemas import CellResult


@dataclass(frozen=True, slots=True)
class ColumnSnapshot:
    key: str
    kind: str
    depends_on: tuple[str, ...]
    config: dict[str, Any]
    prompt: str | None
    output_schema: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ProviderSnapshot:
    id: str
    provider_type: str
    base_url: str
    default_model: str
    credential_mode: str


@dataclass(slots=True)
class ConnectorContext:
    row_id: str
    column: ColumnSnapshot
    row_values: dict[str, Any]
    upstream_execution_hashes: dict[str, str]
    secrets: dict[str, str]
    provider: ProviderSnapshot | None = None
    prior_execution_id: str | None = None
    prior_etag: str | None = None


class Connector(Protocol):
    name: str

    async def execute(self, context: ConnectorContext) -> CellResult: ...

    def fingerprint(self, context: ConnectorContext) -> str: ...


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


class BaseConnector:
    name = "base"
    version = "1"

    def fingerprint(self, context: ConnectorContext) -> str:
        return stable_hash(
            {
                "connector": self.name,
                "connector_version": self.version,
                "column": context.column.key,
                "config": context.column.config,
                "prompt": context.column.prompt,
                "output_schema": context.column.output_schema,
                "upstream_executions": context.upstream_execution_hashes,
                "inputs": {key: context.row_values.get(key) for key in context.column.depends_on},
            }
        )
