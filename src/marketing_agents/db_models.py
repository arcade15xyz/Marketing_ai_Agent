from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TopicRecord(TimestampMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (Index("ix_topics_status_priority", "status", "priority"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    pillar: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(500), unique=True, nullable=False)
    angle: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(120), nullable=False)
    source: Mapped[str] = mapped_column(String(120), default="manual", nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="unused", nullable=False)
    reserved_by_run_id: Mapped[str | None] = mapped_column(String(36))
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class WeeklyBatchRecord(TimestampMixin, Base):
    __tablename__ = "weekly_batches"
    __table_args__ = (
        UniqueConstraint("week_start", "version", name="uq_weekly_batch_start_version"),
        CheckConstraint(
            "expected_item_count BETWEEN 1 AND 7",
            name="ck_weekly_batch_expected_item_count",
        ),
        Index("ix_weekly_batches_status_start", "status", "week_start"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    week_start: Mapped[date] = mapped_column(Date, nullable=False)
    week_end: Mapped[date] = mapped_column(Date, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft", nullable=False)
    expected_item_count: Mapped[int] = mapped_column(Integer, nullable=False)
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    failure_reason: Mapped[str] = mapped_column(Text, default="", nullable=False)
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContentItemRecord(TimestampMixin, Base):
    __tablename__ = "content_items"
    __table_args__ = (
        UniqueConstraint("run_id", "channel", "version", name="uq_content_run_channel_version"),
        UniqueConstraint(
            "weekly_batch_id",
            "batch_position",
            "channel",
            "version",
            name="uq_content_batch_position_channel_version",
        ),
        Index("ix_content_items_status_channel", "status", "channel"),
        Index("ix_content_items_batch_position", "weekly_batch_id", "batch_position"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"))
    weekly_batch_id: Mapped[str | None] = mapped_column(ForeignKey("weekly_batches.id"))
    source_mode: Mapped[str | None] = mapped_column(String(16))
    batch_position: Mapped[int | None] = mapped_column(Integer)
    parent_content_id: Mapped[str | None] = mapped_column(ForeignKey("content_items.id"))
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)


class ResearchSourceRecord(TimestampMixin, Base):
    __tablename__ = "research_sources"
    __table_args__ = (
        UniqueConstraint("topic_id", "url", name="uq_research_source_topic_url"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    topic_id: Mapped[str | None] = mapped_column(ForeignKey("topics.id"), index=True)
    content_item_id: Mapped[str | None] = mapped_column(ForeignKey("content_items.id"), index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    claims_supported: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    validation_state: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)


class ApprovalRecord(TimestampMixin, Base):
    __tablename__ = "approvals"
    __table_args__ = (
        UniqueConstraint("content_item_id", name="uq_approval_content_item"),
        Index("ix_approvals_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    reviewer_notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PublishJobRecord(TimestampMixin, Base):
    __tablename__ = "publish_jobs"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_publish_job_idempotency_key"),
        Index("ix_publish_jobs_status_scheduled", "status", "scheduled_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_item_id: Mapped[str] = mapped_column(ForeignKey("content_items.id"), nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(Text, default="", nullable=False)


class PublishEventRecord(Base):
    __tablename__ = "publish_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    publish_job_id: Mapped[str] = mapped_column(ForeignKey("publish_jobs.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    external_post_id: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    response_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MetricRecord(Base):
    __tablename__ = "metrics"
    __table_args__ = (
        UniqueConstraint(
            "observation_date", "channel", "content_item_id", name="uq_metric_observation"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    content_item_id: Mapped[str | None] = mapped_column(ForeignKey("content_items.id"), index=True)
    observation_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AgentRunRecord(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (Index("ix_agent_runs_status_created", "status", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    agent: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    outputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SystemEventRecord(Base):
    __tablename__ = "system_events"
    __table_args__ = (Index("ix_system_events_type_created", "event_type", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
