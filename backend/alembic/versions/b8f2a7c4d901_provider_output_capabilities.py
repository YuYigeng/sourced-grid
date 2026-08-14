"""provider output capabilities

Revision ID: b8f2a7c4d901
Revises: 9c6d3f8a2b10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8f2a7c4d901"
down_revision: str | None = "9c6d3f8a2b10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_profiles",
        sa.Column(
            "structured_output_mode",
            sa.String(30),
            nullable=False,
            server_default="json_schema",
        ),
    )
    op.add_column(
        "provider_profiles",
        sa.Column("default_temperature", sa.Float(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE provider_profiles SET structured_output_mode = 'prompt_only' "
        "WHERE id = 'anthropic'"
    )


def downgrade() -> None:
    raise RuntimeError("This data-preserving migration cannot be downgraded safely")
