from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

from src.marketing_agents.content_sources import (
    AIWeeklyContentSource,
    ContentSourceConfigurationError,
    JsonWeeklyContentSource,
    WeeklyContentSource,
    configured_content_source_mode,
    configured_weekly_post_count,
    content_source_from_settings,
)
from src.marketing_agents.models import ContentSourceMode, WeeklyContentItem


WEEK_START = date(2026, 10, 5)


def prepared_items(
    mode: ContentSourceMode,
    count: int,
) -> tuple[WeeklyContentItem, ...]:
    return tuple(
        WeeklyContentItem(
            position=position,
            scheduled_date=WEEK_START + timedelta(days=position - 1),
            title=f"Post {position}",
            body=f"Complete body {position}",
            source_mode=mode,
            source_reference=f"{mode.value}:{position}",
        )
        for position in range(1, count + 1)
    )


class ContentSourceSelectionTests(unittest.TestCase):
    def test_json_mode_never_calls_ai_preparer(self) -> None:
        ai_preparer = Mock(return_value=prepared_items(ContentSourceMode.AI, 2))
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "week.json"
            input_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.0",
                        "week_start": WEEK_START.isoformat(),
                        "items": [
                            {
                                "slot": position,
                                "scheduled_date": (
                                    WEEK_START + timedelta(days=position - 1)
                                ).isoformat(),
                                "title": f"Post {position}",
                                "body": f"Authoritative JSON body {position}",
                                "channel": "blog",
                            }
                            for position in range(1, 3)
                        ],
                    }
                ),
                encoding="utf-8",
            )
            source = content_source_from_settings(
                json_source=JsonWeeklyContentSource(input_path),
                ai_source=AIWeeklyContentSource(ai_preparer),
                environ={
                    "CONTENT_SOURCE_MODE": "json",
                    "STORAGE_BACKEND": "database",
                },
            )
            result = source.prepare(WEEK_START, 2)

        self.assertIsInstance(source, WeeklyContentSource)
        self.assertEqual(result.spec.source_mode, ContentSourceMode.JSON)
        self.assertEqual(result.items[0].body, "Authoritative JSON body 1")
        ai_preparer.assert_not_called()

    def test_ai_mode_never_calls_json_preparer(self) -> None:
        ai_preparer = Mock(return_value=prepared_items(ContentSourceMode.AI, 1))
        source = content_source_from_settings(
            json_source=JsonWeeklyContentSource("must-not-be-read.json"),
            ai_source=AIWeeklyContentSource(ai_preparer),
            environ={
                "CONTENT_SOURCE_MODE": "AI",
                "STORAGE_BACKEND": "json",
            },
        )

        result = source.prepare(WEEK_START, 1)

        self.assertEqual(result.spec.source_mode, ContentSourceMode.AI)
        ai_preparer.assert_called_once_with(WEEK_START, 1)

    def test_invalid_mode_fails_fast(self) -> None:
        with self.assertRaisesRegex(
            ContentSourceConfigurationError,
            "either 'json' or 'ai'",
        ):
            configured_content_source_mode({"CONTENT_SOURCE_MODE": "automatic"})

    def test_factory_rejects_miswired_adapters(self) -> None:
        ai_source = AIWeeklyContentSource(Mock())

        with self.assertRaisesRegex(ContentSourceConfigurationError, "json_source"):
            content_source_from_settings(
                json_source=ai_source,
                ai_source=ai_source,
                environ={"CONTENT_SOURCE_MODE": "json"},
            )


class WeeklyPostCountTests(unittest.TestCase):
    def test_defaults_to_seven_and_accepts_configured_count(self) -> None:
        self.assertEqual(configured_weekly_post_count({}), 7)
        self.assertEqual(
            configured_weekly_post_count({"WEEKLY_POST_COUNT": "5"}),
            5,
        )

    def test_rejects_invalid_count(self) -> None:
        for value in ("zero", "0", "8"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(
                    ContentSourceConfigurationError,
                    "between 1 and 7",
                ):
                    configured_weekly_post_count({"WEEKLY_POST_COUNT": value})


class WeeklyContentNormalizationTests(unittest.TestCase):
    def test_adapter_rejects_missing_items(self) -> None:
        source = AIWeeklyContentSource(
            lambda _week_start, _count: prepared_items(ContentSourceMode.JSON, 1)
        )

        with self.assertRaisesRegex(ValueError, "item count"):
            source.prepare(WEEK_START, 2)

    def test_adapter_rejects_items_from_another_mode(self) -> None:
        source = AIWeeklyContentSource(
            lambda _week_start, _count: prepared_items(ContentSourceMode.JSON, 1)
        )

        with self.assertRaisesRegex(ValueError, "match the batch source mode"):
            source.prepare(WEEK_START, 1)

    def test_items_require_complete_title_and_body(self) -> None:
        with self.assertRaisesRegex(ValueError, "title"):
            WeeklyContentItem(
                position=1,
                scheduled_date=WEEK_START,
                title=" ",
                body="Complete body",
                source_mode=ContentSourceMode.JSON,
            )
        with self.assertRaisesRegex(ValueError, "body"):
            WeeklyContentItem(
                position=1,
                scheduled_date=WEEK_START,
                title="Title",
                body=" ",
                source_mode=ContentSourceMode.JSON,
            )


if __name__ == "__main__":
    unittest.main()
