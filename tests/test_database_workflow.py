from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.database_pipeline import DatabasePipelineState
from src.marketing_agents.db_models import (
    AgentRunRecord,
    ApprovalRecord,
    Base,
    ContentItemRecord,
    PublishJobRecord,
    TopicRecord,
)
from src.marketing_agents.linkedin_client import LinkedInPublishResult
from src.marketing_agents.manager import ManagerAgent
from src.marketing_agents.publisher import Publisher
from src.marketing_agents.repositories import LifecycleRepository, TopicRepository


class DatabaseWorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def tearDown(self) -> None:
        self.engine.dispose()

    def seed_topic(self) -> None:
        with self.factory() as session:
            TopicRepository(session).add(
                pillar="Architecture deep dives",
                name="Database-backed topic",
                angle="Treat boundaries as architecture.",
                format="deep dive",
                sources=["https://source.android.com/docs/core/architecture"],
            )
            session.commit()

    def test_daily_run_persists_content_and_preserves_approval_on_rerun(self) -> None:
        self.seed_topic()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            output_dir = root / "outputs"
            data_dir.mkdir()
            (data_dir / "approved_sources.json").write_text(
                json.dumps(
                    {
                        "technical_authorities": ["source.android.com"],
                        "community_public_sources": [],
                    }
                ),
                encoding="utf-8",
            )
            manager = ManagerAgent(DatabasePipelineState(self.factory))
            with (
                patch("src.marketing_agents.manager.OUTPUT_DIR", output_dir),
                patch("src.marketing_agents.agents.DATA_DIR", data_dir),
            ):
                manager.run("2026-09-30")
                with self.factory() as session:
                    LifecycleRepository(session).decide_approval(
                        run_id="daily-2026-09-30",
                        channel="linkedin",
                        decision="approved",
                    )
                    session.commit()
                manager.run("2026-09-30")

        with self.factory() as session:
            topic = session.scalar(select(TopicRecord))
            linkedin_approval = LifecycleRepository(session).approval_for_run(
                run_id="daily-2026-09-30", channel="linkedin"
            )
            self.assertEqual(topic.status, "used")
            self.assertEqual(linkedin_approval.status, "approved")
            self.assertEqual(session.scalar(select(func.count(ContentItemRecord.id))), 4)
            self.assertEqual(session.scalar(select(func.count(ApprovalRecord.id))), 3)
            self.assertEqual(
                session.scalar(
                    select(func.count(AgentRunRecord.id)).where(
                        AgentRunRecord.status == "completed"
                    )
                ),
                2,
            )

    def test_failed_daily_run_releases_reserved_topic(self) -> None:
        self.seed_topic()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            data_dir.mkdir()
            (data_dir / "approved_sources.json").write_text(
                json.dumps(
                    {
                        "technical_authorities": ["source.android.com"],
                        "community_public_sources": [],
                    }
                ),
                encoding="utf-8",
            )
            manager = ManagerAgent(DatabasePipelineState(self.factory))
            manager.writer_agent.run = Mock(side_effect=RuntimeError("generation failed"))
            with (
                patch("src.marketing_agents.manager.OUTPUT_DIR", root / "outputs"),
                patch("src.marketing_agents.agents.DATA_DIR", data_dir),
            ):
                with self.assertRaisesRegex(RuntimeError, "generation failed"):
                    manager.run("2026-10-01")

        with self.factory() as session:
            topic = session.scalar(select(TopicRecord))
            run = session.scalar(select(AgentRunRecord))
            self.assertEqual(topic.status, "unused")
            self.assertEqual(topic.failure_count, 1)
            self.assertEqual(run.status, "failed")

    def test_database_publisher_is_idempotent(self) -> None:
        with self.factory() as session:
            lifecycle = LifecycleRepository(session)
            content = lifecycle.create_content(
                run_id="daily-2026-09-30",
                channel="linkedin",
                title="Title",
                body="Database draft",
                status="queued_for_approval",
            )
            lifecycle.ensure_approval(
                content_item_id=content.id,
                status="approved",
            )
            session.commit()

        success = LinkedInPublishResult(
            ok=True,
            status_code=201,
            post_urn="urn:li:share:123",
            response_body="{}",
            error="",
        )
        with (
            patch.dict(
                os.environ,
                {"STORAGE_BACKEND": "database", "PUBLISHING_KILL_SWITCH": "false"},
                clear=True,
            ),
            patch("src.marketing_agents.publisher.configured_session_factory", return_value=self.factory),
            patch("src.marketing_agents.publisher.LinkedInClient") as client,
        ):
            client.return_value.create_text_share.return_value = success
            published = Publisher().publish("2026-09-30", "linkedin", execute=True)
            repeated = Publisher().publish("2026-09-30", "linkedin", execute=True)

        self.assertIn("Published to LinkedIn", published)
        self.assertIn("already published", repeated)
        client.return_value.create_text_share.assert_called_once_with("Database draft")
        with self.factory() as session:
            job = session.scalar(select(PublishJobRecord))
            self.assertEqual(job.status, "published")
            self.assertEqual(job.attempts, 1)


if __name__ == "__main__":
    unittest.main()
