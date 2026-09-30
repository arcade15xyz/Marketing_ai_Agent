from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.ai_weekly import (
    AIWeeklyBatchConflictError,
    AIWeeklyBatchIncompleteError,
    AIWeeklyBatchService,
)
from src.marketing_agents.db_models import (
    AgentRunRecord,
    ApprovalRecord,
    Base,
    ContentItemRecord,
    SystemEventRecord,
    TopicRecord,
    WeeklyBatchRecord,
)
from src.marketing_agents.llm import FakeLLMProvider, LLMProviderError
from src.marketing_agents.models import ContentSourceMode, WeeklyBatchSpec
from src.marketing_agents.repositories import TopicRepository, WeeklyBatchRepository


WEEK_START = date(2026, 10, 5)
APPROVED_SOURCE = "https://source.android.com/docs/core/architecture"


class InspectingFakeProvider(FakeLLMProvider):
    def __init__(self, responses, factory) -> None:
        super().__init__(responses)
        self.factory = factory
        self.reserved_counts: list[int] = []

    async def generate(self, **kwargs):
        with self.factory() as session:
            self.reserved_counts.append(
                session.scalar(
                    select(func.count(TopicRecord.id)).where(
                        TopicRecord.status == "reserved"
                    )
                )
                or 0
            )
        return await super().generate(**kwargs)


class AIWeeklyBatchServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def seed_topics(self, count: int) -> None:
        pillars = ["Architecture deep dives", "Security", "Build system"]
        with self.factory() as session:
            repository = TopicRepository(session)
            for position in range(1, count + 1):
                repository.add(
                    pillar=pillars[(position - 1) % len(pillars)],
                    name=f"AI weekly topic {position}",
                    angle=f"Grounded angle {position}",
                    format="deep dive",
                    sources=[APPROVED_SOURCE],
                    priority=100 - position,
                )
            session.commit()

    async def test_generates_complete_batch_after_reserving_every_topic(self) -> None:
        self.seed_topics(2)
        provider = InspectingFakeProvider(
            [
                {"title": "Generated one", "body": "# One\n\nComplete content."},
                {"title": "Generated two", "body": "# Two\n\nComplete content."},
            ],
            self.factory,
        )
        service = AIWeeklyBatchService(self.factory, provider)

        prepared = await service.prepare(WEEK_START, 2)

        self.assertTrue(prepared.created)
        self.assertEqual(provider.reserved_counts, [2, 2])
        self.assertEqual(len(provider.requests), 2)
        self.assertEqual(prepared.result.items[0].body, "# One\n\nComplete content.")
        self.assertEqual(
            provider.requests[0].prompt_version,
            "weekly_ai_writer:v1",
        )
        with self.factory() as session:
            batch = session.get(WeeklyBatchRecord, prepared.batch_id)
            topics = list(session.scalars(select(TopicRecord)))
            content = list(
                session.scalars(
                    select(ContentItemRecord).order_by(
                        ContentItemRecord.batch_position
                    )
                )
            )
            runs = list(session.scalars(select(AgentRunRecord)))
            approvals = list(session.scalars(select(ApprovalRecord)))

        self.assertEqual(batch.status, "pending_approval")
        self.assertEqual(batch.configuration_snapshot["models"], ["fake"])
        self.assertTrue(all(topic.status == "used" for topic in topics))
        self.assertEqual(len(content), 8)
        self.assertTrue(all(item.source_mode == "ai" for item in content))
        self.assertEqual(
            {item.channel for item in content},
            {"master", "blog", "linkedin", "reddit"},
        )
        masters = [item for item in content if item.channel == "master"]
        self.assertEqual(
            [item.metadata_json["scheduled_date"] for item in masters],
            ["2026-10-05", "2026-10-06"],
        )
        self.assertTrue(all(item.parent_content_id is None for item in masters))
        self.assertEqual([run.status for run in runs], ["completed", "completed"])
        self.assertEqual(len(approvals), 6)
        self.assertTrue(all(approval.status == "pending" for approval in approvals))
        approval_content_ids = {approval.content_item_id for approval in approvals}
        self.assertFalse(
            any(
                item.channel == "reddit" and item.id in approval_content_ids
                for item in content
            )
        )

    async def test_provider_failure_releases_all_topics_and_fails_batch(self) -> None:
        self.seed_topics(2)
        provider = FakeLLMProvider(
            [{"title": "Generated one", "body": "Complete content."}]
        )
        service = AIWeeklyBatchService(self.factory, provider)

        with self.assertRaisesRegex(LLMProviderError, "no queued responses"):
            await service.prepare(WEEK_START, 2)

        with self.factory() as session:
            batch = session.scalar(select(WeeklyBatchRecord))
            topics = list(session.scalars(select(TopicRecord)))
            run_statuses = list(
                session.scalars(
                    select(AgentRunRecord.status).order_by(AgentRunRecord.created_at)
                )
            )
            content_count = session.scalar(select(func.count(ContentItemRecord.id)))

        self.assertEqual(batch.status, "failed")
        self.assertTrue(all(topic.status == "unused" for topic in topics))
        self.assertTrue(all(topic.failure_count == 1 for topic in topics))
        self.assertEqual(run_statuses, ["completed", "failed"])
        self.assertEqual(content_count, 0)

    async def test_backlog_exhaustion_releases_reservations_and_marks_incomplete(
        self,
    ) -> None:
        self.seed_topics(1)
        provider = FakeLLMProvider([])
        service = AIWeeklyBatchService(self.factory, provider)

        with self.assertRaisesRegex(
            AIWeeklyBatchIncompleteError,
            "enough unique topics",
        ):
            await service.prepare(WEEK_START, 2)

        with self.factory() as session:
            batch = session.scalar(select(WeeklyBatchRecord))
            topic = session.scalar(select(TopicRecord))
            event_types = set(session.scalars(select(SystemEventRecord.event_type)))

        self.assertEqual(batch.status, "incomplete")
        self.assertEqual(topic.status, "unused")
        self.assertEqual(topic.failure_count, 1)
        self.assertEqual(len(provider.requests), 0)
        self.assertIn("TOPIC_BACKLOG_EXHAUSTED", event_types)
        self.assertIn("WEEKLY_BATCH_INCOMPLETE", event_types)

    async def test_rerun_restores_persisted_batch_without_new_llm_calls(self) -> None:
        self.seed_topics(1)
        provider = FakeLLMProvider(
            [{"title": "Generated once", "body": "Complete content."}]
        )
        service = AIWeeklyBatchService(self.factory, provider)

        first = await service.prepare(WEEK_START, 1)
        repeated = await service.prepare(WEEK_START, 1)

        self.assertEqual(repeated.batch_id, first.batch_id)
        self.assertEqual(repeated.content_item_ids, first.content_item_ids)
        self.assertFalse(repeated.created)
        self.assertTrue(repeated.result.source_metadata["restored"])
        self.assertEqual(len(provider.requests), 1)


    async def test_does_not_overwrite_existing_json_batch(self) -> None:
        with self.factory() as session:
            WeeklyBatchRepository(session).create(
                WeeklyBatchSpec(
                    week_start=WEEK_START,
                    source_mode=ContentSourceMode.JSON,
                    expected_item_count=1,
                )
            )
            session.commit()
        provider = FakeLLMProvider([])
        service = AIWeeklyBatchService(self.factory, provider)

        with self.assertRaisesRegex(
            AIWeeklyBatchConflictError,
            "different source mode",
        ):
            await service.prepare(WEEK_START, 1)

        self.assertEqual(len(provider.requests), 0)
if __name__ == "__main__":
    unittest.main()
