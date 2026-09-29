from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

from .models import (
    ContentSourceMode,
    WeeklyBatchResult,
    WeeklyBatchSpec,
    WeeklyContentItem,
)
from .weekly_json import load_weekly_json


class ContentSourceConfigurationError(RuntimeError):
    """Raised when weekly content-source settings are invalid."""


@runtime_checkable
class WeeklyContentSource(Protocol):
    mode: ContentSourceMode

    def prepare(self, week_start: date, count: int) -> WeeklyBatchResult:
        """Prepare and normalize a complete weekly content batch."""


WeeklyItemsPreparer = Callable[
    [date, int],
    Iterable[WeeklyContentItem],
]


class _WeeklyContentSourceAdapter:
    mode: ContentSourceMode

    def __init__(self, prepare_items: WeeklyItemsPreparer) -> None:
        self._prepare_items = prepare_items

    def prepare(self, week_start: date, count: int) -> WeeklyBatchResult:
        spec = WeeklyBatchSpec(
            week_start=week_start,
            source_mode=self.mode,
            expected_item_count=count,
        )
        items = tuple(self._prepare_items(week_start, count))
        return WeeklyBatchResult(spec=spec, items=items)


class JsonWeeklyContentSource:
    """Load complete, authoritative weekly items from a versioned JSON file."""

    mode = ContentSourceMode.JSON

    def __init__(self, input_path: Path | str) -> None:
        self.input_path = Path(input_path)

    def prepare(self, week_start: date, count: int) -> WeeklyBatchResult:
        return load_weekly_json(self.input_path, week_start=week_start, count=count)


class AIWeeklyContentSource(_WeeklyContentSourceAdapter):
    """Normalize items produced by the configured AI weekly generator."""

    mode = ContentSourceMode.AI


def configured_content_source_mode(
    environ: Mapping[str, str] | None = None,
) -> ContentSourceMode:
    values = os.environ if environ is None else environ
    configured = values.get("CONTENT_SOURCE_MODE", ContentSourceMode.JSON.value)
    try:
        return ContentSourceMode(configured.strip().lower())
    except ValueError as exc:
        raise ContentSourceConfigurationError(
            "CONTENT_SOURCE_MODE must be either 'json' or 'ai'."
        ) from exc


def configured_weekly_post_count(
    environ: Mapping[str, str] | None = None,
) -> int:
    values = os.environ if environ is None else environ
    raw_count = values.get("WEEKLY_POST_COUNT", "7")
    try:
        count = int(raw_count)
    except ValueError as exc:
        raise ContentSourceConfigurationError(
            "WEEKLY_POST_COUNT must be an integer between 1 and 7."
        ) from exc
    if not 1 <= count <= 7:
        raise ContentSourceConfigurationError(
            "WEEKLY_POST_COUNT must be an integer between 1 and 7."
        )
    return count


def content_source_from_settings(
    *,
    json_source: WeeklyContentSource,
    ai_source: WeeklyContentSource,
    environ: Mapping[str, str] | None = None,
) -> WeeklyContentSource:
    if json_source.mode is not ContentSourceMode.JSON:
        raise ContentSourceConfigurationError(
            "json_source must declare ContentSourceMode.JSON."
        )
    if ai_source.mode is not ContentSourceMode.AI:
        raise ContentSourceConfigurationError(
            "ai_source must declare ContentSourceMode.AI."
        )

    mode = configured_content_source_mode(environ)
    if mode is ContentSourceMode.JSON:
        return json_source
    return ai_source
