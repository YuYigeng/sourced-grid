from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.orm import Session

from ..models import ColumnDefinition, GridRow
from ..schemas import CellResult
from ..secrets import SecretVault


@dataclass(slots=True)
class ConnectorContext:
    session: Session
    row: GridRow
    column: ColumnDefinition
    row_values: dict[str, Any]
    vault: SecretVault


class Connector(Protocol):
    name: str

    async def execute(self, context: ConnectorContext) -> CellResult: ...

    def fingerprint(self, context: ConnectorContext) -> str: ...


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


class BaseConnector:
    name = "base"

    def fingerprint(self, context: ConnectorContext) -> str:
        return stable_hash(
            {
                "connector": self.name,
                "column": context.column.key,
                "config": context.column.config,
                "prompt": context.column.prompt,
                "inputs": {key: context.row_values.get(key) for key in context.column.depends_on},
            }
        )
