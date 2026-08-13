from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ProvenanceOut(BaseModel):
    id: str
    connector: str
    source_urls: list[str]
    artifact_hash: str | None
    input_hash: str | None
    model: str | None
    prompt: str | None
    input_tokens: int
    output_tokens: int
    cost_usd: float
    duration_ms: int
    cache_hit: bool
    created_at: datetime
    metadata: dict[str, Any]


class CellOut(BaseModel):
    id: str
    column_id: str
    status: str
    value: Any = None
    error: str | None = None
    provenance: ProvenanceOut | None = None


class ColumnOut(BaseModel):
    id: str
    key: str
    label: str
    kind: str
    width: int
    position: int
    depends_on: list[str]
    config: dict[str, Any]
    prompt: str | None
    output_schema: dict[str, Any]


class RowOut(BaseModel):
    id: str
    position: int
    cells: list[CellOut]


class GridOut(BaseModel):
    id: str
    name: str
    description: str
    columns: list[ColumnOut]
    rows: list[RowOut]


class BulkImportRows(BaseModel):
    rows: list[dict[str, Any]] = Field(min_length=1, max_length=1000)
    duplicate_strategy: Literal["skip", "replace", "allow"] = "skip"


class GridCreate(BaseModel):
    name: str = Field(min_length=1, max_length=180)
    description: str = Field(default="", max_length=2000)


class GridPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=2000)


class ColumnIn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str = Field(min_length=1, max_length=180)
    kind: Literal["input", "github", "http", "transform", "llm"]
    width: int = Field(default=160, ge=80, le=800)
    depends_on: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    output_schema: dict[str, Any] = Field(default_factory=dict)


class ColumnPatch(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=180)
    width: int | None = Field(default=None, ge=80, le=800)
    depends_on: list[str] | None = None
    config: dict[str, Any] | None = None
    prompt: str | None = None
    output_schema: dict[str, Any] | None = None


class ImportRows(BaseModel):
    values: list[str] = Field(min_length=1, max_length=1000)


class RowCreate(BaseModel):
    value: str = Field(min_length=1, max_length=20_000)


class InputCellPatch(BaseModel):
    value: str = Field(min_length=1, max_length=20_000)


class RunCreate(BaseModel):
    budget_usd: float = Field(default=2.0, ge=0, le=1000)
    force_refresh: bool = False


class RunOut(BaseModel):
    id: str
    status: str
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    spent_usd: float
    budget_usd: float


class ProviderCredentialIn(BaseModel):
    value: str = Field(min_length=1, max_length=20_000)


class ProviderCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,119}$")
    display_name: str = Field(min_length=1, max_length=180)
    base_url: str = Field(min_length=1, max_length=2000)
    default_model: str = Field(min_length=1, max_length=180)
    credential_mode: Literal["required", "none"] = "required"
    trusted: Literal[True]


class ProviderPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=180)
    base_url: str | None = Field(default=None, min_length=1, max_length=2000)
    default_model: str | None = Field(default=None, min_length=1, max_length=180)
    credential_mode: Literal["required", "none"] | None = None
    trusted: Literal[True] | None = None


class SchemaDraft(BaseModel):
    schema_version: int = Field(ge=1)
    columns: list[ColumnIn] = Field(min_length=1)
    canvas_layout: dict[str, Any] = Field(default_factory=dict)


class SecretIn(BaseModel):
    value: str = Field(min_length=1, max_length=20_000)


class SecretOut(BaseModel):
    name: str
    configured: bool
    updated_at: datetime | None = None


class TemplateImport(BaseModel):
    document: str = Field(min_length=1, max_length=500_000)


class TemplateColumn(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    kind: Literal["input", "github", "http", "transform", "llm"]
    width: int = Field(default=160, ge=80, le=800)
    depends_on: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    prompt: str | None = None
    output_schema: dict[str, Any] = Field(default_factory=dict)


class TemplateMetadata(BaseModel):
    slug: str
    name: str
    version: str = "0.1.0"
    description: str = ""


class ResearchTemplate(BaseModel):
    apiVersion: Literal["sourcedgrid/v1alpha1"]
    kind: Literal["ResearchTemplate"]
    metadata: TemplateMetadata
    defaults: dict[str, Any] = Field(default_factory=dict)
    columns: list[TemplateColumn] = Field(min_length=1)


class CellResult(BaseModel):
    value: Any
    connector: str
    source_urls: list[str] = Field(default_factory=list)
    artifact_content: str | bytes | None = None
    artifact_content_type: str = "application/json"
    input_hash: str | None = None
    model: str | None = None
    prompt: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    cache_hit: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
