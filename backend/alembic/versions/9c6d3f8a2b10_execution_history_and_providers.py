"""immutable execution history and trusted providers

Revision ID: 9c6d3f8a2b10
Revises: 35a3bdad004e
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "9c6d3f8a2b10"
down_revision: str | None = "35a3bdad004e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("grids", sa.Column("schema_version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("grids", sa.Column("canvas_layout", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("runs", sa.Column("reserved_usd", sa.Float(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("force_refresh", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("runs", sa.Column("schema_snapshot", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("runs", sa.Column("skipped_tasks", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("runs", sa.Column("cancelled_tasks", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("run_tasks", sa.Column("execution_id", sa.String(36), nullable=True))
    op.add_column("run_tasks", sa.Column("reserved_usd", sa.Float(), nullable=False, server_default="0"))

    op.create_table(
        "cell_executions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cell_id", sa.String(36), nullable=True),
        sa.Column("row_position", sa.Integer(), nullable=False),
        sa.Column("column_key", sa.String(100), nullable=False),
        sa.Column("column_label", sa.String(180), nullable=False),
        sa.Column("run_id", sa.String(36), nullable=True),
        sa.Column("run_task_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("error_code", sa.String(120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("cache_key", sa.String(64), nullable=True),
        sa.Column("source_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cache_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reused_from_execution_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["cell_id"], ["cells.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_task_id"], ["run_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reused_from_execution_id"], ["cell_executions.id"]),
        sa.UniqueConstraint("run_task_id"),
    )
    op.create_index("ix_cell_executions_cell_id", "cell_executions", ["cell_id"])
    op.create_index("ix_cell_executions_run_id", "cell_executions", ["run_id"])
    op.create_index("ix_cell_executions_status", "cell_executions", ["status"])
    op.create_index("idx_executions_cell_created", "cell_executions", ["cell_id", "created_at"])
    op.create_index("idx_executions_cache", "cell_executions", ["cache_key", "cache_expires_at"])

    connection = op.get_bind()
    cells = connection.execute(
        sa.text(
            "SELECT cells.id, cells.status, cells.value, cells.error, cells.cache_key, "
            "cells.created_at, cells.updated_at, grid_rows.position AS row_position, "
            "column_definitions.key AS column_key, column_definitions.label AS column_label "
            "FROM cells JOIN grid_rows ON grid_rows.id=cells.row_id "
            "JOIN column_definitions ON column_definitions.id=cells.column_id"
        )
    ).mappings()
    latest: dict[str, str] = {}
    for cell in cells:
        execution_id = str(uuid.uuid4())
        latest[cell["id"]] = execution_id
        connection.execute(
            sa.text(
                "INSERT INTO cell_executions "
                "(id, cell_id, row_position, column_key, column_label, status, value, "
                "error_code, error_message, cache_key, "
                "source_fetched_at, created_at, completed_at) "
                "VALUES (:id, :cell_id, :row_position, :column_key, :column_label, :status, "
                ":value, :error_code, :error_message, :cache_key, "
                ":source_fetched_at, :created_at, :completed_at)"
            ),
            {
                "id": execution_id,
                "cell_id": cell["id"],
                "row_position": cell["row_position"],
                "column_key": cell["column_key"],
                "column_label": cell["column_label"],
                "status": cell["status"],
                "value": cell["value"],
                "error_code": "legacy_error" if cell["error"] else None,
                "error_message": cell["error"],
                "cache_key": cell["cache_key"],
                "source_fetched_at": cell["updated_at"],
                "created_at": cell["created_at"],
                "completed_at": cell["updated_at"],
            },
        )

    op.add_column("provenance", sa.Column("execution_id", sa.String(36), nullable=True))
    for cell_id, execution_id in latest.items():
        connection.execute(
            sa.text("UPDATE provenance SET execution_id=:execution_id WHERE cell_id=:cell_id"),
            {"execution_id": execution_id, "cell_id": cell_id},
        )
    with op.batch_alter_table(
        "provenance",
        naming_convention={
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        },
    ) as batch:
        batch.drop_constraint("uq_provenance_cell_id", type_="unique")
        batch.drop_constraint("fk_provenance_cell_id_cells", type_="foreignkey")
        batch.alter_column("cell_id", nullable=True)
        batch.alter_column("execution_id", nullable=False)
        batch.create_foreign_key(
            "fk_provenance_execution", "cell_executions", ["execution_id"], ["id"], ondelete="CASCADE"
        )
        batch.create_unique_constraint("uq_provenance_execution", ["execution_id"])

    op.add_column("cells", sa.Column("latest_execution_id", sa.String(36), nullable=True))
    for cell_id, execution_id in latest.items():
        connection.execute(
            sa.text("UPDATE cells SET latest_execution_id=:execution_id WHERE id=:cell_id"),
            {"execution_id": execution_id, "cell_id": cell_id},
        )
    with op.batch_alter_table("cells") as batch:
        batch.create_foreign_key(
            "fk_cells_latest_execution", "cell_executions", ["latest_execution_id"], ["id"]
        )
    op.create_index("ix_cells_latest_execution_id", "cells", ["latest_execution_id"])

    with op.batch_alter_table("run_tasks") as batch:
        batch.create_foreign_key("fk_run_tasks_execution", "cell_executions", ["execution_id"], ["id"])

    op.create_table(
        "execution_dependencies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("upstream_execution_id", sa.String(36), nullable=False),
        sa.Column("column_key", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(["execution_id"], ["cell_executions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["upstream_execution_id"], ["cell_executions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("execution_id", "upstream_execution_id", name="uq_execution_dependency"),
    )
    op.create_index("ix_execution_dependencies_execution_id", "execution_dependencies", ["execution_id"])
    op.create_index(
        "ix_execution_dependencies_upstream_execution_id", "execution_dependencies", ["upstream_execution_id"]
    )

    op.create_table(
        "provider_profiles",
        sa.Column("id", sa.String(120), primary_key=True),
        sa.Column("provider_type", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(180), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("default_model", sa.String(180), nullable=False),
        sa.Column("credential_mode", sa.String(30), nullable=False),
        sa.Column("secret_name", sa.String(120), nullable=True),
        sa.Column("trusted", sa.Boolean(), nullable=False),
        sa.Column("builtin", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["runs.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])


def downgrade() -> None:
    raise RuntimeError("This data-preserving migration cannot be downgraded safely")
