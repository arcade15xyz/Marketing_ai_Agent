"""Create the durable marketing content lifecycle.

Revision ID: 0001_initial_persistence
Revises: None
Create Date: 2026-09-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0001_initial_persistence"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp_columns() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    op.create_table(
        "topics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("pillar", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=500), nullable=False, unique=True),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reserved_by_run_id", sa.String(length=36)),
        sa.Column("reserved_at", sa.DateTime(timezone=True)),
        sa.Column("used_at", sa.DateTime(timezone=True)),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        *timestamp_columns(),
    )
    op.create_index("ix_topics_status_priority", "topics", ["status", "priority"])

    op.create_table(
        "content_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.String(length=36), sa.ForeignKey("topics.id")),
        sa.Column(
            "parent_content_id",
            sa.String(length=36),
            sa.ForeignKey("content_items.id"),
        ),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint(
            "run_id", "channel", "version", name="uq_content_run_channel_version"
        ),
    )
    op.create_index("ix_content_items_run_id", "content_items", ["run_id"])
    op.create_index(
        "ix_content_items_status_channel", "content_items", ["status", "channel"]
    )

    op.create_table(
        "research_sources",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("topic_id", sa.String(length=36), sa.ForeignKey("topics.id")),
        sa.Column(
            "content_item_id", sa.String(length=36), sa.ForeignKey("content_items.id")
        ),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True)),
        sa.Column("claims_supported", sa.JSON(), nullable=False),
        sa.Column("validation_state", sa.String(length=32), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("topic_id", "url", name="uq_research_source_topic_url"),
    )
    op.create_index("ix_research_sources_topic_id", "research_sources", ["topic_id"])
    op.create_index(
        "ix_research_sources_content_item_id", "research_sources", ["content_item_id"]
    )

    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "content_item_id",
            sa.String(length=36),
            sa.ForeignKey("content_items.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reviewer_notes", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        *timestamp_columns(),
        sa.UniqueConstraint("content_item_id", name="uq_approval_content_item"),
    )
    op.create_index("ix_approvals_status", "approvals", ["status"])

    op.create_table(
        "publish_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "content_item_id",
            sa.String(length=36),
            sa.ForeignKey("content_items.id"),
            nullable=False,
        ),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("external_post_id", sa.String(length=255), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=False),
        *timestamp_columns(),
        sa.UniqueConstraint("idempotency_key", name="uq_publish_job_idempotency_key"),
    )
    op.create_index(
        "ix_publish_jobs_status_scheduled", "publish_jobs", ["status", "scheduled_at"]
    )

    op.create_table(
        "publish_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "publish_job_id",
            sa.String(length=36),
            sa.ForeignKey("publish_jobs.id"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("external_post_id", sa.String(length=255), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("response_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_publish_events_publish_job_id", "publish_events", ["publish_job_id"]
    )

    op.create_table(
        "metrics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "content_item_id", sa.String(length=36), sa.ForeignKey("content_items.id")
        ),
        sa.Column("observation_date", sa.Date(), nullable=False),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "observation_date",
            "channel",
            "content_item_id",
            name="uq_metric_observation",
        ),
    )
    op.create_index("ix_metrics_content_item_id", "metrics", ["content_item_id"])

    op.create_table(
        "agent_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("agent", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("outputs", sa.JSON(), nullable=False),
        sa.Column("model_name", sa.String(length=120), nullable=False),
        sa.Column("latency_ms", sa.Integer()),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("cost_usd", sa.Numeric(precision=12, scale=6)),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_agent_runs_run_date", "agent_runs", ["run_date"])
    op.create_index(
        "ix_agent_runs_status_created", "agent_runs", ["status", "created_at"]
    )

    op.create_table(
        "system_events",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_system_events_type_created", "system_events", ["event_type", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("system_events")
    op.drop_table("agent_runs")
    op.drop_table("metrics")
    op.drop_table("publish_events")
    op.drop_table("publish_jobs")
    op.drop_table("approvals")
    op.drop_table("research_sources")
    op.drop_table("content_items")
    op.drop_table("topics")
