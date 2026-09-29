from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any


class ContentSourceMode(StrEnum):
    JSON = "json"
    AI = "ai"


class WeeklyBatchStatus(StrEnum):
    DRAFT = "draft"
    VALIDATING = "validating"
    PENDING_APPROVAL = "pending_approval"
    READY = "ready"
    PUBLISHING = "publishing"
    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    REPLACED = "replaced"


@dataclass(frozen=True)
class WeeklyBatchSpec:
    week_start: date
    source_mode: ContentSourceMode
    expected_item_count: int = 7

    def __post_init__(self) -> None:
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday.")
        if not 1 <= self.expected_item_count <= 7:
            raise ValueError("expected_item_count must be between 1 and 7.")

    @property
    def week_end(self) -> date:
        return self.week_start + timedelta(days=6)


@dataclass(frozen=True)
class WeeklyContentItem:
    position: int
    title: str
    body: str
    source_mode: ContentSourceMode
    scheduled_date: date
    channel: str = "blog"
    source_reference: str = ""
    sources: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.position < 1:
            raise ValueError("Weekly content position must be positive.")
        if not self.title.strip():
            raise ValueError("Weekly content title must not be empty.")
        if not self.body.strip():
            raise ValueError("Weekly content body must not be empty.")
        if not isinstance(self.source_mode, ContentSourceMode):
            raise ValueError("Weekly content source_mode must be json or ai.")
        if not self.channel.strip():
            raise ValueError("Weekly content channel must not be empty.")


@dataclass(frozen=True)
class WeeklyBatchResult:
    spec: WeeklyBatchSpec
    items: tuple[WeeklyContentItem, ...]
    source_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if len(self.items) != self.spec.expected_item_count:
            raise ValueError(
                "Weekly batch result item count does not match expected_item_count."
            )

        positions = {item.position for item in self.items}
        expected_positions = set(range(1, self.spec.expected_item_count + 1))
        if positions != expected_positions:
            raise ValueError(
                "Weekly batch result positions must be unique and contiguous."
            )


        scheduled_dates = {item.scheduled_date for item in self.items}
        if len(scheduled_dates) != len(self.items):
            raise ValueError("Weekly batch result scheduled dates must be unique.")
        if any(
            scheduled_date < self.spec.week_start
            or scheduled_date > self.spec.week_end
            for scheduled_date in scheduled_dates
        ):
            raise ValueError(
                "Weekly batch result scheduled dates must fall within the week."
            )
        if any(item.source_mode is not self.spec.source_mode for item in self.items):
            raise ValueError(
                "Every weekly content item must match the batch source mode."
            )


@dataclass(frozen=True)
class Topic:
    pillar: str
    topic: str
    angle: str
    format: str
    sources: list[str]


@dataclass(frozen=True)
class ResearchPacket:
    run_date: str
    candidates: list[Topic]


@dataclass(frozen=True)
class StrategyBrief:
    run_date: str
    topic: Topic
    target_reader: str
    call_to_action: str


@dataclass(frozen=True)
class Draft:
    title: str
    body: str
    sources: list[str]


@dataclass(frozen=True)
class ReviewResult:
    status: str
    notes: list[str]
    required_sources: list[str]


@dataclass(frozen=True)
class PlatformDraft:
    platform: str
    title: str
    body: str
    status: str
    notes: list[str]


@dataclass(frozen=True)
class RepurposedPackage:
    drafts: list[PlatformDraft]


@dataclass(frozen=True)
class AnalyticsReport:
    week_start: str
    week_end: str
    summary: list[str]
    recommendations: list[str]
    rows: list[JsonObject]


@dataclass(frozen=True)
class PipelinePaths:
    root: Path
    output_dir: Path
    research: Path
    strategy: Path
    draft: Path
    review: Path
    blog: Path
    linkedin: Path
    reddit: Path
    approval: Path
    package: Path


JsonObject = dict[str, Any]

