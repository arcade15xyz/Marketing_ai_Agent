from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from .models import (
    ContentSourceMode,
    WeeklyBatchResult,
    WeeklyBatchSpec,
    WeeklyContentItem,
)


class JsonWeeklyContentError(ValueError):
    """Raised when a weekly JSON input cannot be read or validated."""


class JsonWeeklyItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slot: int = Field(ge=1, le=7)
    scheduled_date: date
    title: str
    body: str
    channel: str = "blog"
    metadata: dict[str, Any] = Field(default_factory=dict)
    sources: list[str] = Field(default_factory=list)

    @field_validator("title", "body", "channel")
    @classmethod
    def require_non_empty_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("sources")
    @classmethod
    def require_non_empty_sources(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("source entries must not be empty")
        return values


class JsonWeeklyBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    week_start: date
    items: list[JsonWeeklyItem] = Field(min_length=1, max_length=7)

    @model_validator(mode="after")
    def validate_week_and_duplicates(self) -> JsonWeeklyBatch:
        if self.week_start.weekday() != 0:
            raise ValueError("week_start must be a Monday")

        slots = [item.slot for item in self.items]
        if len(slots) != len(set(slots)):
            raise ValueError("items contain duplicate slots")

        scheduled_dates = [item.scheduled_date for item in self.items]
        if len(scheduled_dates) != len(set(scheduled_dates)):
            raise ValueError("items contain duplicate scheduled_date values")

        week_end = self.week_start + timedelta(days=6)
        if any(
            scheduled_date < self.week_start or scheduled_date > week_end
            for scheduled_date in scheduled_dates
        ):
            raise ValueError("every scheduled_date must fall within the declared week")
        return self


def load_weekly_json(
    input_path: Path | str,
    *,
    week_start: date,
    count: int,
) -> WeeklyBatchResult:
    path = Path(input_path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise JsonWeeklyContentError(
            f"Unable to read weekly JSON input {path}: {exc}"
        ) from exc

    try:
        payload = JsonWeeklyBatch.model_validate_json(raw)
    except ValidationError as exc:
        raise JsonWeeklyContentError(
            f"Invalid weekly JSON input {path}: {exc}"
        ) from exc

    if payload.week_start != week_start:
        raise JsonWeeklyContentError(
            f"JSON week_start is {payload.week_start}, expected {week_start}."
        )
    if len(payload.items) != count:
        raise JsonWeeklyContentError(
            f"JSON contains {len(payload.items)} items, expected {count}."
        )

    resolved_path = path.resolve()
    digest = sha256(raw).hexdigest()
    spec = WeeklyBatchSpec(
        week_start=week_start,
        source_mode=ContentSourceMode.JSON,
        expected_item_count=count,
    )
    items = tuple(
        WeeklyContentItem(
            position=item.slot,
            scheduled_date=item.scheduled_date,
            title=item.title,
            body=item.body,
            channel=item.channel,
            source_mode=ContentSourceMode.JSON,
            source_reference=f"{resolved_path}#slot={item.slot}",
            sources=tuple(item.sources),
            metadata=dict(item.metadata),
        )
        for item in payload.items
    )

    try:
        return WeeklyBatchResult(
            spec=spec,
            items=items,
            source_metadata={
                "schema_version": payload.schema_version,
                "source_path": str(resolved_path),
                "source_name": path.name,
                "source_size": len(raw),
                "source_checksum_sha256": digest,
            },
        )
    except ValueError as exc:
        raise JsonWeeklyContentError(
            f"Invalid weekly JSON batch {path}: {exc}"
        ) from exc
