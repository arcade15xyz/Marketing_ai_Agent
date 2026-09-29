"""Add durable weekly content batches.

Revision ID: 0002_weekly_batches
Revises: 0001_initial_persistence
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0002_weekly_batches"
down_revision: str | None = "0001_initial_persistence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_batches",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("week_end", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("expected_item_count", sa.Integer(), nullable=False),
        sa.Column("configuration_snapshot", sa.JSON(), nullable=False),
        sa.Column("failure_reason", sa.Text(), nullable=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "expected_item_count BETWEEN 1 AND 7",
            name="ck_weekly_batch_expected_item_count",
        ),
        sa.UniqueConstraint(
            "week_start",
            "version",
            name="uq_weekly_batch_start_version",
        ),
    )
    op.create_index(
        "ix_weekly_batches_status_start",
        "weekly_batches",
        ["status", "week_start"],
    )

    with op.batch_alter_table("content_items") as batch_op:
        batch_op.add_column(
            sa.Column("weekly_batch_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("source_mode", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("batch_position", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_content_items_weekly_batch_id",
            "weekly_batches",
            ["weekly_batch_id"],
            ["id"],
        )
        batch_op.create_unique_constraint(
            "uq_content_batch_position_channel_version",
            ["weekly_batch_id", "batch_position", "channel", "version"],
        )
        batch_op.create_index(
            "ix_content_items_batch_position",
            ["weekly_batch_id", "batch_position"],
        )


def downgrade() -> None:
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.drop_index("ix_content_items_batch_position")
        batch_op.drop_constraint(
            "uq_content_batch_position_channel_version",
            type_="unique",
        )
        batch_op.drop_constraint(
            "fk_content_items_weekly_batch_id",
            type_="foreignkey",
        )
        batch_op.drop_column("batch_position")
        batch_op.drop_column("source_mode")
        batch_op.drop_column("weekly_batch_id")

    op.drop_index(
        "ix_weekly_batches_status_start",
        table_name="weekly_batches",
    )
    op.drop_table("weekly_batches")
