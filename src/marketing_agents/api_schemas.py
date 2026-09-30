from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class OrmSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class HealthResponse(BaseModel):
    status: str
    storage_backend: str
    database_configured: bool
    content_source_mode: str
    publishing_kill_switch: bool


class TopicCreate(BaseModel):
    pillar: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=500)
    angle: str = Field(min_length=1)
    format: str = Field(min_length=1, max_length=120)
    sources: list[str] = Field(default_factory=list)
    source: str = Field(default="manual", min_length=1, max_length=120)
    priority: int = 0


class TopicRead(OrmSchema):
    id: str
    pillar: str
    name: str
    angle: str
    format: str
    source: str
    priority: int
    status: str
    failure_count: int
    created_at: datetime
    updated_at: datetime


class WeeklyBatchRead(OrmSchema):
    id: str
    week_start: date
    week_end: date
    version: int
    source_mode: str
    status: str
    expected_item_count: int
    configuration_snapshot: dict[str, Any]
    failure_reason: str
    finalized_at: datetime | None
    created_at: datetime
    updated_at: datetime

class WeeklyApprovalSummaryRead(BaseModel):
    batch_id: str
    batch_status: str
    required_count: int
    approved_count: int
    pending_count: int
    needs_changes_count: int
    rejected_count: int
    missing_count: int
    ready: bool


class ContentItemRead(OrmSchema):
    id: str
    run_id: str
    topic_id: str | None
    weekly_batch_id: str | None
    source_mode: str | None
    batch_position: int | None
    parent_content_id: str | None
    channel: str
    title: str
    body: str
    version: int
    status: str
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


ApprovalDecisionValue = Literal["approved", "rejected", "needs_changes"]


class ApprovalDecision(BaseModel):
    decision: ApprovalDecisionValue
    note: str = ""


class ApprovalRead(BaseModel):
    id: str
    content_item_id: str
    channel: str
    title: str
    status: str
    reviewer_notes: str
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PublishRequest(BaseModel):
    execute: bool = False


class PublishResponse(BaseModel):
    content_item_id: str
    publish_job_id: str
    channel: str
    status: Literal["dry_run", "published"]
    message: str
    external_post_id: str = ""


class MetricCreate(BaseModel):
    observation_date: date
    channel: str = Field(min_length=1, max_length=40)
    values: dict[str, Any]
    content_item_id: str | None = None
    note: str = ""


class MetricRead(OrmSchema):
    id: str
    content_item_id: str | None
    observation_date: date
    channel: str
    values: dict[str, Any]
    note: str
    recorded_at: datetime


class AgentRunRead(OrmSchema):
    id: str
    run_date: date
    agent: str
    status: str
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    model_name: str
    latency_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: Decimal | None
    error: str
    created_at: datetime
    completed_at: datetime | None


class AnalyticsSummary(BaseModel):
    topics: dict[str, int]
    content: dict[str, int]
    approvals: dict[str, int]
    publish_jobs: dict[str, int]
    metrics_count: int
