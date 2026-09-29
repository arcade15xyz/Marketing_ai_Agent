from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.db_models import Base
from src.marketing_agents.models import (
    ContentSourceMode,
    WeeklyBatchSpec,
    WeeklyBatchStatus,
)
from src.marketing_agents.repositories import (
    LifecycleRepository,
    WeeklyBatchRepository,
    WeeklyBatchStateError,
    WeeklyBatchValidationError,
)


class WeeklyBatchSpecTests(unittest.TestCase):
    def test_week_is_monday_through_sunday_and_count_is_configurable(self) -> None:
        spec = WeeklyBatchSpec(
            week_start=date(2026, 10, 5),
            source_mode=ContentSourceMode.JSON,
            expected_item_count=5,
        )

        self.assertEqual(spec.week_end, date(2026, 10, 11))
        self.assertEqual(spec.expected_item_count, 5)

    def test_rejects_non_monday_and_out_of_range_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "Monday"):
            WeeklyBatchSpec(
                week_start=date(2026, 10, 6),
                source_mode=ContentSourceMode.JSON,
            )
        with self.assertRaisesRegex(ValueError, "between 1 and 7"):
            WeeklyBatchSpec(
                week_start=date(2026, 10, 5),
                source_mode=ContentSourceMode.JSON,
                expected_item_count=8,
            )


class WeeklyBatchRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.factory()
        self.batches = WeeklyBatchRepository(self.session)
        self.lifecycle = LifecycleRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def spec(
        self,
        mode: ContentSourceMode = ContentSourceMode.JSON,
        count: int = 2,
    ) -> WeeklyBatchSpec:
        return WeeklyBatchSpec(
            week_start=date(2026, 10, 5),
            source_mode=mode,
            expected_item_count=count,
        )

    def test_creation_is_idempotent_and_preserves_mode_snapshot(self) -> None:
        original = self.batches.create(
            self.spec(),
            configuration={"input": "week.json"},
        )
        repeated = self.batches.create(
            self.spec(ContentSourceMode.AI, count=7),
            configuration={"model": "changed"},
        )

        self.assertEqual(repeated.id, original.id)
        self.assertEqual(repeated.source_mode, "json")
        self.assertEqual(repeated.expected_item_count, 2)
        self.assertEqual(
            repeated.configuration_snapshot,
            {
                "input": "week.json",
                "source_mode": "json",
                "expected_item_count": 2,
            },
        )

    def test_weekly_content_inherits_mode_and_cannot_change_it(self) -> None:
        batch = self.batches.create(self.spec())
        content = self.lifecycle.create_content(
            run_id="weekly-2026-10-05-1",
            channel="master",
            title="One",
            body="Complete blog",
            status="draft",
            weekly_batch_id=batch.id,
            batch_position=1,
        )

        self.assertEqual(content.source_mode, "json")
        with self.assertRaisesRegex(
            WeeklyBatchValidationError,
            "source mode cannot be changed",
        ):
            self.lifecycle.create_content(
                run_id="weekly-2026-10-05-1",
                channel="master",
                title="One",
                body="Complete blog",
                status="draft",
                weekly_batch_id=batch.id,
                source_mode=ContentSourceMode.AI,
                batch_position=1,
            )

    def test_batch_cannot_become_ready_with_missing_positions(self) -> None:
        batch = self.batches.create(self.spec(count=2))
        self.batches.transition(batch.id, WeeklyBatchStatus.VALIDATING)
        self.batches.transition(batch.id, WeeklyBatchStatus.PENDING_APPROVAL)
        self.lifecycle.create_content(
            run_id="weekly-2026-10-05-1",
            channel="master",
            title="One",
            body="First blog",
            status="draft",
            weekly_batch_id=batch.id,
            batch_position=1,
        )

        with self.assertRaisesRegex(
            WeeklyBatchValidationError,
            "every expected master position",
        ):
            self.batches.transition(batch.id, WeeklyBatchStatus.READY)

        self.lifecycle.create_content(
            run_id="weekly-2026-10-05-2",
            channel="master",
            title="Two",
            body="Second blog",
            status="draft",
            weekly_batch_id=batch.id,
            batch_position=2,
        )
        ready = self.batches.transition(batch.id, WeeklyBatchStatus.READY)

        self.assertEqual(ready.status, "ready")
        self.assertIsNotNone(ready.finalized_at)

    def test_invalid_transition_is_rejected(self) -> None:
        batch = self.batches.create(self.spec())

        with self.assertRaisesRegex(WeeklyBatchStateError, "Cannot transition"):
            self.batches.transition(batch.id, WeeklyBatchStatus.COMPLETED)

    def test_exception_state_requires_reason(self) -> None:
        batch = self.batches.create(self.spec())

        with self.assertRaisesRegex(WeeklyBatchValidationError, "reason is required"):
            self.batches.transition(batch.id, WeeklyBatchStatus.INCOMPLETE)

        incomplete = self.batches.transition(
            batch.id,
            WeeklyBatchStatus.INCOMPLETE,
            reason="Only one valid item was supplied.",
        )
        self.assertEqual(incomplete.failure_reason, "Only one valid item was supplied.")

    def test_mode_changes_require_explicit_replacement(self) -> None:
        original = self.batches.create(self.spec())
        replacement = self.batches.replace(
            original.id,
            self.spec(ContentSourceMode.AI, count=5),
            configuration={"model": "claude"},
        )

        self.assertEqual(original.status, "replaced")
        self.assertEqual(replacement.version, 2)
        self.assertEqual(replacement.source_mode, "ai")
        self.assertNotEqual(replacement.id, original.id)
        self.assertEqual(
            self.batches.create(self.spec(ContentSourceMode.JSON)).id,
            replacement.id,
        )


if __name__ == "__main__":
    unittest.main()
