from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.api_service import ApiConflictError
from src.marketing_agents.db_models import (
    Base,
    PublishEventRecord,
    PublishJobRecord,
    WeeklyBatchRecord,
)
from src.marketing_agents.linkedin_client import LinkedInPublishResult
from src.marketing_agents.repositories import LifecycleRepository, TopicRepository
from src.marketing_agents.scheduling import (
    DuePublishService,
    WeeklyPreparationError,
    WeeklyPreparationService,
)


WEEK_START = date(2026, 10, 5)


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def weekly_json(self, root: Path, count: int = 2) -> Path:
        path = root / "week.json"
        path.write_text(
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
                            "body": f"Complete body {position}",
                            "channel": "blog",
                        }
                        for position in range(1, count + 1)
                    ],
                }
            ),
            encoding="utf-8",
        )
        return path

    async def test_json_prepare_dry_run_does_not_mutate_or_call_ai(self) -> None:
        provider_factory = Mock(side_effect=AssertionError("AI must not be called"))
        service = WeeklyPreparationService(
            self.factory,
            provider_factory=provider_factory,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = self.weekly_json(Path(temp_dir))
            outcome = await service.prepare(
                WEEK_START,
                input_path=input_path,
                dry_run=True,
                environ={"CONTENT_SOURCE_MODE": "json", "WEEKLY_POST_COUNT": "2"},
            )

        self.assertTrue(outcome.dry_run)
        self.assertEqual(outcome.item_count, 2)
        provider_factory.assert_not_called()
        with self.factory() as session:
            self.assertEqual(
                session.scalar(select(func.count(WeeklyBatchRecord.id))),
                0,
            )

    async def test_json_prepare_imports_once_and_is_idempotent(self) -> None:
        service = WeeklyPreparationService(self.factory)
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = self.weekly_json(Path(temp_dir))
            first = await service.prepare(
                WEEK_START,
                input_path=input_path,
                environ={"CONTENT_SOURCE_MODE": "json", "WEEKLY_POST_COUNT": "2"},
            )
            repeated = await service.prepare(
                WEEK_START,
                input_path=input_path,
                environ={"CONTENT_SOURCE_MODE": "json", "WEEKLY_POST_COUNT": "2"},
            )

        self.assertTrue(first.created)
        self.assertFalse(repeated.created)
        self.assertEqual(first.batch_id, repeated.batch_id)
        self.assertEqual(first.content_item_ids, repeated.content_item_ids)

    async def test_ai_dry_run_checks_capacity_without_calling_provider(self) -> None:
        with self.factory() as session:
            for index in range(2):
                TopicRepository(session).add(
                    pillar="Architecture",
                    name=f"Topic {index}",
                    angle="Explain the boundary.",
                    format="deep dive",
                )
            session.commit()

        provider_factory = Mock(side_effect=AssertionError("No token spend in dry-run"))
        outcome = await WeeklyPreparationService(
            self.factory,
            provider_factory=provider_factory,
        ).prepare(
            WEEK_START,
            dry_run=True,
            environ={"CONTENT_SOURCE_MODE": "ai", "WEEKLY_POST_COUNT": "2"},
        )

        self.assertEqual(outcome.source_mode, "ai")
        self.assertEqual(outcome.item_count, 2)
        provider_factory.assert_not_called()
        with self.factory() as session:
            self.assertEqual(
                session.scalar(select(func.count(WeeklyBatchRecord.id))),
                0,
            )

    async def test_ai_dry_run_fails_when_backlog_is_too_small(self) -> None:
        with self.factory() as session:
            TopicRepository(session).add(
                pillar="Architecture",
                name="Only topic",
                angle="Explain the boundary.",
                format="deep dive",
            )
            session.commit()

        with self.assertRaisesRegex(WeeklyPreparationError, "only 1"):
            await WeeklyPreparationService(self.factory).prepare(
                WEEK_START,
                dry_run=True,
                environ={"CONTENT_SOURCE_MODE": "ai", "WEEKLY_POST_COUNT": "2"},
            )

    def add_job(
        self,
        *,
        run_id: str,
        scheduled_at: datetime,
        approval: str = "approved",
        job_status: str = "ready",
        attempts: int = 0,
    ) -> str:
        with self.factory() as session:
            lifecycle = LifecycleRepository(session)
            content = lifecycle.create_content(
                run_id=run_id,
                channel="linkedin",
                title=run_id,
                body=f"Body for {run_id}",
                status="queued_for_approval",
            )
            lifecycle.ensure_approval(
                content_item_id=content.id,
                status=approval,
            )
            job = lifecycle.ensure_publish_job(
                content_item_id=content.id,
                channel="linkedin",
                idempotency_key=f"scheduled:{content.id}",
                status=job_status,
            )
            job.scheduled_at = scheduled_at
            job.attempts = attempts
            session.commit()
            return job.id

    def test_publish_due_filters_time_approval_state_and_retry_limit(self) -> None:
        now = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
        due_id = self.add_job(
            run_id="due-approved",
            scheduled_at=now - timedelta(minutes=1),
        )
        self.add_job(
            run_id="future",
            scheduled_at=now + timedelta(minutes=1),
        )
        self.add_job(
            run_id="not-approved",
            scheduled_at=now - timedelta(minutes=1),
            approval="pending",
        )
        self.add_job(
            run_id="not-ready",
            scheduled_at=now - timedelta(minutes=1),
            job_status="pending",
        )
        self.add_job(
            run_id="attempts-exhausted",
            scheduled_at=now - timedelta(minutes=1),
            job_status="failed",
            attempts=3,
        )
        client = Mock()

        outcome = DuePublishService(
            self.factory,
            client_factory=lambda: client,
        ).publish_due(now=now)

        self.assertEqual(outcome.due_count, 1)
        self.assertEqual(outcome.dry_run_count, 1)
        client.create_text_share.assert_not_called()
        with self.factory() as session:
            events = list(session.scalars(select(PublishEventRecord)))
            jobs = list(session.scalars(select(PublishJobRecord)))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].publish_job_id, due_id)
        self.assertEqual(len(jobs), 5)

    def test_publish_due_executes_one_due_job_and_reuses_job_record(self) -> None:
        now = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
        job_id = self.add_job(
            run_id="due-execute",
            scheduled_at=now - timedelta(minutes=1),
            job_status="failed",
            attempts=1,
        )
        client = Mock()
        client.create_text_share.return_value = LinkedInPublishResult(
            ok=True,
            status_code=201,
            post_urn="urn:li:share:scheduled",
            response_body="{}",
            error="",
        )

        outcome = DuePublishService(
            self.factory,
            client_factory=lambda: client,
        ).publish_due(
            now=now,
            execute=True,
            environ={"PUBLISHING_KILL_SWITCH": "false"},
        )

        self.assertEqual(outcome.published_count, 1)
        client.create_text_share.assert_called_once()
        with self.factory() as session:
            job = session.get(PublishJobRecord, job_id)
            job_count = session.scalar(select(func.count(PublishJobRecord.id)))
        self.assertEqual(job.status, "published")
        self.assertEqual(job.attempts, 2)
        self.assertEqual(job_count, 1)

    def test_publish_due_kill_switch_blocks_before_external_call(self) -> None:
        now = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)
        self.add_job(
            run_id="kill-switch",
            scheduled_at=now - timedelta(minutes=1),
        )
        client = Mock()

        with self.assertRaisesRegex(ApiConflictError, "KILL_SWITCH"):
            DuePublishService(
                self.factory,
                client_factory=lambda: client,
            ).publish_due(
                now=now,
                execute=True,
                environ={"PUBLISHING_KILL_SWITCH": "true"},
            )

        client.create_text_share.assert_not_called()


if __name__ == "__main__":
    unittest.main()
