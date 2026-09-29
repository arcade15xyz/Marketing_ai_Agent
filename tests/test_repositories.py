from __future__ import annotations

import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.db_models import (
    Base,
    ContentItemRecord,
    PublishJobRecord,
    SystemEventRecord,
)
from src.marketing_agents.repositories import (
    LifecycleRepository,
    TopicRepository,
    TopicStateError,
)


class RepositoryTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.session_factory()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def add_topic(self, name: str, pillar: str = "Architecture", priority: int = 0):
        return TopicRepository(self.session).add(
            pillar=pillar,
            name=name,
            angle="An angle",
            format="deep dive",
            sources=["https://source.android.com/docs/core/architecture"],
            priority=priority,
        )


class TopicRepositoryTests(RepositoryTestCase):
    def test_reservation_prefers_priority_and_avoids_last_pillar(self) -> None:
        self.add_topic("High same pillar", pillar="Architecture", priority=100)
        expected = self.add_topic("Lower other pillar", pillar="Security", priority=10)

        reserved = TopicRepository(self.session).reserve_next(
            run_id="run-1", last_pillar="Architecture"
        )

        self.assertEqual(reserved.id, expected.id)
        self.assertEqual(reserved.status, "reserved")

    def test_reservation_is_idempotent_for_same_run(self) -> None:
        self.add_topic("First")
        self.add_topic("Second")
        repository = TopicRepository(self.session)

        first = repository.reserve_next(run_id="run-1")
        repeated = repository.reserve_next(run_id="run-1")

        self.assertEqual(first.id, repeated.id)

    def test_separate_runs_do_not_reserve_same_topic(self) -> None:
        self.add_topic("First", priority=20)
        self.add_topic("Second", priority=10)
        repository = TopicRepository(self.session)

        first = repository.reserve_next(run_id="run-1")
        second = repository.reserve_next(run_id="run-2")

        self.assertNotEqual(first.id, second.id)

    def test_exhaustion_creates_visible_system_event(self) -> None:
        reserved = self.add_topic("Only topic")
        reserved.status = "used"
        self.session.flush()

        result = TopicRepository(self.session).reserve_next(run_id="run-2")
        event_count = self.session.scalar(
            select(func.count(SystemEventRecord.id)).where(
                SystemEventRecord.event_type == "TOPIC_BACKLOG_EXHAUSTED"
            )
        )

        self.assertIsNone(result)
        self.assertEqual(event_count, 1)

    def test_only_reserving_run_can_mark_topic_used(self) -> None:
        topic = self.add_topic("Reserved topic")
        repository = TopicRepository(self.session)
        repository.reserve_next(run_id="run-1")

        with self.assertRaises(TopicStateError):
            repository.mark_used(topic_id=topic.id, run_id="run-2")

        used = repository.mark_used(topic_id=topic.id, run_id="run-1")
        self.assertEqual(used.status, "used")
        self.assertIsNotNone(used.used_at)

    def test_release_makes_topic_eligible_and_records_failure(self) -> None:
        topic = self.add_topic("Retry topic")
        repository = TopicRepository(self.session)
        repository.reserve_next(run_id="run-1")

        released = repository.release(topic_id=topic.id, run_id="run-1")

        self.assertEqual(released.status, "unused")
        self.assertEqual(released.failure_count, 1)
        self.assertEqual(repository.stats()["failed"], 1)


class LifecycleRepositoryTests(RepositoryTestCase):
    def test_content_and_publish_job_are_idempotent(self) -> None:
        lifecycle = LifecycleRepository(self.session)
        content = lifecycle.create_content(
            run_id="run-1",
            channel="linkedin",
            title="Title",
            body="Body",
            status="queued_for_approval",
        )
        repeated_content = lifecycle.create_content(
            run_id="run-1",
            channel="linkedin",
            title="Changed title",
            body="Changed body",
            status="queued_for_approval",
        )
        first_job = lifecycle.ensure_publish_job(
            content_item_id=content.id,
            channel="linkedin",
            idempotency_key="run-1:linkedin:v1",
        )
        repeated_job = lifecycle.ensure_publish_job(
            content_item_id=content.id,
            channel="linkedin",
            idempotency_key="run-1:linkedin:v1",
        )

        self.assertEqual(content.id, repeated_content.id)
        self.assertEqual(first_job.id, repeated_job.id)
        self.assertEqual(
            self.session.scalar(select(func.count(ContentItemRecord.id))), 1
        )
        self.assertEqual(
            self.session.scalar(select(func.count(PublishJobRecord.id))), 1
        )


if __name__ == "__main__":
    unittest.main()
