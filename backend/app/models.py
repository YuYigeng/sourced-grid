from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Grid(Base, TimestampMixin):
    __tablename__ = "grids"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    template_slug: Mapped[str | None] = mapped_column(String(120), nullable=True)
    schema_version: Mapped[int] = mapped_column(Integer, default=1)
    canvas_layout: Mapped[dict] = mapped_column(JSON, default=dict)
    columns: Mapped[list[ColumnDefinition]] = relationship(
        back_populates="grid", cascade="all, delete-orphan", order_by="ColumnDefinition.position"
    )
    rows: Mapped[list[GridRow]] = relationship(
        back_populates="grid", cascade="all, delete-orphan", order_by="GridRow.position"
    )


class ColumnDefinition(Base, TimestampMixin):
    __tablename__ = "column_definitions"
    __table_args__ = (UniqueConstraint("grid_id", "key", name="uq_columns_grid_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    grid_id: Mapped[str] = mapped_column(ForeignKey("grids.id", ondelete="CASCADE"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(180))
    kind: Mapped[str] = mapped_column(String(30))
    position: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer, default=160)
    depends_on: Mapped[list[str]] = mapped_column(JSON, default=list)
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_schema: Mapped[dict] = mapped_column(JSON, default=dict)
    grid: Mapped[Grid] = relationship(back_populates="columns")
    cells: Mapped[list[Cell]] = relationship(back_populates="column", cascade="all, delete-orphan")


class GridRow(Base, TimestampMixin):
    __tablename__ = "grid_rows"
    __table_args__ = (UniqueConstraint("grid_id", "position", name="uq_rows_grid_position"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    grid_id: Mapped[str] = mapped_column(ForeignKey("grids.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    grid: Mapped[Grid] = relationship(back_populates="rows")
    cells: Mapped[list[Cell]] = relationship(back_populates="row", cascade="all, delete-orphan")


class Cell(Base, TimestampMixin):
    __tablename__ = "cells"
    __table_args__ = (UniqueConstraint("row_id", "column_id", name="uq_cells_row_column"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    row_id: Mapped[str] = mapped_column(ForeignKey("grid_rows.id", ondelete="CASCADE"), index=True)
    column_id: Mapped[str] = mapped_column(
        ForeignKey("column_definitions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="empty", index=True)
    value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    latest_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("cell_executions.id", use_alter=True), nullable=True, index=True
    )
    row: Mapped[GridRow] = relationship(back_populates="cells")
    column: Mapped[ColumnDefinition] = relationship(back_populates="cells")
    executions: Mapped[list[CellExecution]] = relationship(
        back_populates="cell", foreign_keys="CellExecution.cell_id", passive_deletes=True
    )
    latest_execution: Mapped[CellExecution | None] = relationship(
        foreign_keys=[latest_execution_id], post_update=True
    )


class Run(Base, TimestampMixin):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    grid_id: Mapped[str] = mapped_column(ForeignKey("grids.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    budget_usd: Mapped[float] = mapped_column(Float, default=2.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    force_refresh: Mapped[bool] = mapped_column(Boolean, default=False)
    schema_snapshot: Mapped[dict] = mapped_column(JSON, default=dict)
    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    skipped_tasks: Mapped[int] = mapped_column(Integer, default=0)
    cancelled_tasks: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tasks: Mapped[list[RunTask]] = relationship(back_populates="run", cascade="all, delete-orphan")
    events: Mapped[list[RunEvent]] = relationship(back_populates="run", cascade="all, delete-orphan")


class RunTask(Base, TimestampMixin):
    __tablename__ = "run_tasks"
    __table_args__ = (
        UniqueConstraint("run_id", "row_id", "column_id", name="uq_tasks_run_row_column"),
        Index("idx_tasks_claim", "status", "available_at", "lease_expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    row_id: Mapped[str] = mapped_column(ForeignKey("grid_rows.id", ondelete="CASCADE"), index=True)
    column_id: Mapped[str] = mapped_column(
        ForeignKey("column_definitions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    execution_id: Mapped[str | None] = mapped_column(ForeignKey("cell_executions.id"), nullable=True)
    reserved_usd: Mapped[float] = mapped_column(Float, default=0.0)
    run: Mapped[Run] = relationship(back_populates="tasks")
    execution: Mapped[CellExecution | None] = relationship(foreign_keys=[execution_id])


class CellExecution(Base):
    __tablename__ = "cell_executions"
    __table_args__ = (
        Index("idx_executions_cell_created", "cell_id", "created_at"),
        Index("idx_executions_cache", "cache_key", "cache_expires_at"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cell_id: Mapped[str | None] = mapped_column(
        ForeignKey("cells.id", ondelete="SET NULL"), nullable=True, index=True
    )
    row_position: Mapped[int] = mapped_column(Integer)
    column_key: Mapped[str] = mapped_column(String(100))
    column_label: Mapped[str] = mapped_column(String(180))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    run_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("run_tasks.id", ondelete="SET NULL"), unique=True
    )
    status: Mapped[str] = mapped_column(String(30), index=True)
    value: Mapped[object | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(120), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cache_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cache_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reused_from_execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("cell_executions.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cell: Mapped[Cell | None] = relationship(back_populates="executions", foreign_keys=[cell_id])
    provenance: Mapped[Provenance | None] = relationship(
        back_populates="execution", cascade="all, delete-orphan", uselist=False
    )


class ExecutionDependency(Base):
    __tablename__ = "execution_dependencies"
    __table_args__ = (
        UniqueConstraint("execution_id", "upstream_execution_id", name="uq_execution_dependency"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("cell_executions.id", ondelete="CASCADE"), index=True
    )
    upstream_execution_id: Mapped[str] = mapped_column(
        ForeignKey("cell_executions.id", ondelete="RESTRICT"), index=True
    )
    column_key: Mapped[str] = mapped_column(String(100))


class Provenance(Base):
    __tablename__ = "provenance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    execution_id: Mapped[str] = mapped_column(
        ForeignKey("cell_executions.id", ondelete="CASCADE"), unique=True
    )
    legacy_cell_id: Mapped[str | None] = mapped_column("cell_id", String(36), nullable=True)
    connector: Mapped[str] = mapped_column(String(80))
    source_urls: Mapped[list[str]] = mapped_column(JSON, default=list)
    artifact_hash: Mapped[str | None] = mapped_column(ForeignKey("artifacts.hash"), nullable=True)
    input_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(180), nullable=True)
    prompt: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    cache_hit: Mapped[bool] = mapped_column(Boolean, default=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    execution: Mapped[CellExecution] = relationship(back_populates="provenance")


class ProviderProfile(Base, TimestampMixin):
    __tablename__ = "provider_profiles"
    id: Mapped[str] = mapped_column(String(120), primary_key=True)
    provider_type: Mapped[str] = mapped_column(String(40))
    display_name: Mapped[str] = mapped_column(String(180))
    base_url: Mapped[str] = mapped_column(Text)
    default_model: Mapped[str] = mapped_column(String(180))
    credential_mode: Mapped[str] = mapped_column(String(30), default="required")
    secret_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    trusted: Mapped[bool] = mapped_column(Boolean, default=False)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    run: Mapped[Run] = relationship(back_populates="events")


class Artifact(Base):
    __tablename__ = "artifacts"
    hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    path: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str] = mapped_column(String(180))
    byte_size: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Template(Base, TimestampMixin):
    __tablename__ = "templates"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(180))
    version: Mapped[str] = mapped_column(String(40))
    document_yaml: Mapped[str] = mapped_column(Text)


class EncryptedSecret(Base, TimestampMixin):
    __tablename__ = "encrypted_secrets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    ciphertext: Mapped[str] = mapped_column(Text)
