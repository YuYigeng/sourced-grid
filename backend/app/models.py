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
    row: Mapped[GridRow] = relationship(back_populates="cells")
    column: Mapped[ColumnDefinition] = relationship(back_populates="cells")
    provenance: Mapped[Provenance | None] = relationship(
        back_populates="cell", cascade="all, delete-orphan", uselist=False
    )


class Run(Base, TimestampMixin):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    grid_id: Mapped[str] = mapped_column(ForeignKey("grids.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(40), default="queued", index=True)
    budget_usd: Mapped[float] = mapped_column(Float, default=2.0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tasks: Mapped[int] = mapped_column(Integer, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tasks: Mapped[list[RunTask]] = relationship(back_populates="run", cascade="all, delete-orphan")


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
    run: Mapped[Run] = relationship(back_populates="tasks")


class Provenance(Base):
    __tablename__ = "provenance"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cell_id: Mapped[str] = mapped_column(ForeignKey("cells.id", ondelete="CASCADE"), unique=True)
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
    cell: Mapped[Cell] = relationship(back_populates="provenance")


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
