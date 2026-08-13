"""provider pricing

Revision ID: c3d9e6f1a702
Revises: b8f2a7c4d901
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d9e6f1a702"
down_revision: str | None = "b8f2a7c4d901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "provider_profiles",
        sa.Column("input_price_per_million_usd", sa.Float(), nullable=True),
    )
    op.add_column(
        "provider_profiles",
        sa.Column("cached_input_price_per_million_usd", sa.Float(), nullable=True),
    )
    op.add_column(
        "provider_profiles",
        sa.Column("output_price_per_million_usd", sa.Float(), nullable=True),
    )
    op.execute(
        "UPDATE provider_profiles SET input_price_per_million_usd = 0.14, "
        "cached_input_price_per_million_usd = 0.0028, "
        "output_price_per_million_usd = 0.28 WHERE id = 'deepseek'"
    )


def downgrade() -> None:
    raise RuntimeError("This data-preserving migration cannot be downgraded safely")
