from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.content_sources import JsonWeeklyContentSource
from src.marketing_agents.db_models import Base, ContentItemRecord, WeeklyBatchRecord
from src.marketing_agents.weekly_import import (
    JsonWeeklyBatchImporter,
    WeeklyImportConflictError,
)
from src.marketing_agents.weekly_json import JsonWeeklyContentError


WEEK_START = date(2026, 10, 5)


def payload(
    count: int = 2,
    *,
    body_prefix: str = "Complete authoritative body",
) -> dict:
    return {
        "schema_version": "1.0",
        "week_start": WEEK_START.isoformat(),
        "items": [
            {
                "slot": position,
                "scheduled_date": (
                    WEEK_START + timedelta(days=position - 1)
                ).isoformat(),
                "title": f"Blog {position}",
                "body": f"{body_prefix} {position}",
                "channel": "blog",
                "metadata": {
                    "pillar": "AOSP",
                    "tags": ["android", f"slot-{position}"],
                },
                "sources": ["https://source.android.com/docs/core/architecture"],
            }
            for position in range(1, count + 1)
        ],
    }


class JsonWeeklySchemaTests(unittest.TestCase):
    def write_payload(self, value: dict) -> tuple[tempfile.TemporaryDirectory, Path]:
        temp_dir = tempfile.TemporaryDirectory()
        path = Path(temp_dir.name) / "week.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return temp_dir, path

    def test_valid_file_loads_complete_content_and_checksum(self) -> None:
        temp_dir, path = self.write_payload(payload())
        self.addCleanup(temp_dir.cleanup)

        result = JsonWeeklyContentSource(path).prepare(WEEK_START, 2)

        self.assertEqual(result.items[0].body, "Complete authoritative body 1")
        self.assertEqual(result.items[0].scheduled_date, WEEK_START)
        self.assertEqual(result.items[0].metadata["pillar"], "AOSP")
        self.assertEqual(len(result.source_metadata["source_checksum_sha256"]), 64)
        self.assertEqual(result.source_metadata["schema_version"], "1.0")

    def test_duplicate_slots_and_dates_are_rejected(self) -> None:
        for duplicate_field in ("slot", "scheduled_date"):
            value = payload()
            value["items"][1][duplicate_field] = value["items"][0][duplicate_field]
            temp_dir, path = self.write_payload(value)
            self.addCleanup(temp_dir.cleanup)

            with self.subTest(duplicate_field=duplicate_field):
                with self.assertRaisesRegex(
                    JsonWeeklyContentError,
                    f"duplicate {duplicate_field}",
                ):
                    JsonWeeklyContentSource(path).prepare(WEEK_START, 2)

    def test_wrong_schema_week_and_count_are_actionable(self) -> None:
        wrong_week = payload()
        wrong_week["week_start"] = "2026-10-12"
        for item in wrong_week["items"]:
            item["scheduled_date"] = (
                date.fromisoformat(item["scheduled_date"]) + timedelta(days=7)
            ).isoformat()

        cases = [
            ("schema_version", {**payload(), "schema_version": "2.0"}, "schema_version"),
            ("week_start", wrong_week, "expected"),
            ("count", payload(count=1), "expected 2"),
        ]
        for name, value, message in cases:
            temp_dir, path = self.write_payload(value)
            self.addCleanup(temp_dir.cleanup)
            with self.subTest(name=name):
                with self.assertRaisesRegex(JsonWeeklyContentError, message):
                    JsonWeeklyContentSource(path).prepare(WEEK_START, 2)

    def test_missing_body_and_unknown_fields_are_rejected(self) -> None:
        missing_body = payload(count=1)
        missing_body["items"][0].pop("body")
        unknown_field = payload(count=1)
        unknown_field["items"][0]["rewrite_with_ai"] = True

        for name, value in (
            ("missing_body", missing_body),
            ("unknown_field", unknown_field),
        ):
            temp_dir, path = self.write_payload(value)
            self.addCleanup(temp_dir.cleanup)
            with self.subTest(name=name):
                with self.assertRaises(JsonWeeklyContentError):
                    JsonWeeklyContentSource(path).prepare(WEEK_START, 1)


class JsonWeeklyImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.factory()
        self.importer = JsonWeeklyBatchImporter(self.session)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "week.json"

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def prepare(self, value: dict | None = None):
        self.path.write_text(json.dumps(value or payload()), encoding="utf-8")
        return JsonWeeklyContentSource(self.path).prepare(WEEK_START, 2)

    def test_import_creates_pending_batch_and_authoritative_master_content(self) -> None:
        result = self.prepare()

        imported = self.importer.import_batch(result)
        self.session.commit()

        batch = self.session.get(WeeklyBatchRecord, imported.batch_id)
        content = list(
            self.session.scalars(
                select(ContentItemRecord).order_by(ContentItemRecord.batch_position)
            )
        )
        self.assertTrue(imported.created)
        self.assertEqual(batch.status, "pending_approval")
        self.assertEqual(batch.source_mode, "json")
        self.assertEqual(len(content), 2)
        self.assertEqual(content[0].body, "Complete authoritative body 1")
        self.assertEqual(content[0].metadata_json["scheduled_date"], "2026-10-05")
        self.assertEqual(
            content[0].metadata_json["source_checksum_sha256"],
            result.source_metadata["source_checksum_sha256"],
        )

    def test_repeated_identical_import_is_idempotent(self) -> None:
        result = self.prepare()
        first = self.importer.import_batch(result)
        self.session.commit()

        repeated = self.importer.import_batch(result)
        self.session.commit()

        self.assertFalse(repeated.created)
        self.assertEqual(repeated.batch_id, first.batch_id)
        self.assertEqual(repeated.content_item_ids, first.content_item_ids)
        self.assertEqual(
            self.session.scalar(select(func.count(WeeklyBatchRecord.id))),
            1,
        )
        self.assertEqual(
            self.session.scalar(select(func.count(ContentItemRecord.id))),
            2,
        )

    def test_changed_file_is_rejected_without_mutating_existing_batch(self) -> None:
        original = self.prepare()
        imported = self.importer.import_batch(original)
        self.session.commit()

        changed = self.prepare(payload(body_prefix="Changed body"))
        with self.assertRaisesRegex(
            WeeklyImportConflictError,
            "different JSON file",
        ):
            self.importer.import_batch(changed)
        self.session.rollback()

        batch = self.session.get(WeeklyBatchRecord, imported.batch_id)
        first_content = self.session.scalar(
            select(ContentItemRecord).where(ContentItemRecord.batch_position == 1)
        )
        self.assertEqual(batch.status, "pending_approval")
        self.assertEqual(first_content.body, "Complete authoritative body 1")


if __name__ == "__main__":
    unittest.main()
