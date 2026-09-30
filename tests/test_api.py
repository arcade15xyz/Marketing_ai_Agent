from __future__ import annotations

import os
import unittest
from datetime import date
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.marketing_agents.api import create_app
from src.marketing_agents.db_models import (
    Base,
    ContentItemRecord,
    PublishEventRecord,
    PublishJobRecord,
)
from src.marketing_agents.linkedin_client import LinkedInPublishResult
from src.marketing_agents.models import ContentSourceMode, WeeklyBatchSpec
from src.marketing_agents.repositories import (
    LifecycleRepository,
    WeeklyBatchRepository,
)


class FastApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.linkedin = Mock()
        self.app = create_app(
            session_factory=self.factory,
            linkedin_client_factory=lambda: self.linkedin,
        )
        self.client = TestClient(self.app)

    def tearDown(self) -> None:
        self.client.close()
        self.engine.dispose()

    def create_linkedin_content(self) -> str:
        with self.factory() as session:
            content = LifecycleRepository(session).create_content(
                run_id="weekly-2026-10-05-1",
                channel="linkedin",
                title="AOSP boundary",
                body="A durable LinkedIn draft.",
                status="queued_for_approval",
            )
            session.commit()
            return content.id

    def test_health_does_not_require_a_database_connection(self) -> None:
        with patch.dict(
            os.environ,
            {
                "STORAGE_BACKEND": "database",
                "DATABASE_URL": "postgresql://user:pass@localhost/db",
                "CONTENT_SOURCE_MODE": "ai",
                "PUBLISHING_KILL_SWITCH": "true",
            },
            clear=True,
        ):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "storage_backend": "database",
                "database_configured": True,
                "content_source_mode": "ai",
                "publishing_kill_switch": True,
            },
        )

    def test_topics_can_be_created_listed_and_filtered(self) -> None:
        payload = {
            "pillar": "Architecture",
            "name": "System and vendor boundaries",
            "angle": "Explain stable interfaces.",
            "format": "deep dive",
            "sources": ["https://source.android.com/docs/core/architecture"],
            "priority": 10,
        }

        created = self.client.post("/topics", json=payload)
        listed = self.client.get("/topics", params={"status": "unused"})

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.json()["name"], payload["name"])
        self.assertEqual(len(listed.json()), 1)
        self.assertEqual(listed.json()[0]["priority"], 10)

    def test_batches_and_content_are_browsable(self) -> None:
        with self.factory() as session:
            batch = WeeklyBatchRepository(session).create(
                WeeklyBatchSpec(
                    week_start=date(2026, 10, 5),
                    source_mode=ContentSourceMode.JSON,
                    expected_item_count=1,
                )
            )
            content = LifecycleRepository(session).create_content(
                run_id="weekly-2026-10-05-1",
                weekly_batch_id=batch.id,
                batch_position=1,
                channel="master",
                title="AOSP architecture",
                body="Long-form content",
                status="queued_for_approval",
            )
            session.commit()
            batch_id = batch.id
            content_id = content.id

        batch_response = self.client.get(f"/batches/{batch_id}")
        content_response = self.client.get(f"/batches/{batch_id}/content")
        approval_response = self.client.post(
            f"/content/{content_id}/approval",
            json={"decision": "needs_changes", "note": "Add a source."},
        )

        self.assertEqual(batch_response.status_code, 200)
        self.assertEqual(content_response.status_code, 200)
        self.assertEqual(content_response.json()[0]["id"], content_id)
        self.assertEqual(approval_response.status_code, 200)
        self.assertEqual(approval_response.json()["status"], "needs_changes")
        self.assertEqual(approval_response.json()["reviewer_notes"], "Add a source.")

    def test_batch_becomes_ready_only_after_every_required_approval(self) -> None:
        with self.factory() as session:
            batches = WeeklyBatchRepository(session)
            lifecycle = LifecycleRepository(session)
            batch = batches.create(
                WeeklyBatchSpec(
                    week_start=date(2026, 10, 12),
                    source_mode=ContentSourceMode.JSON,
                    expected_item_count=2,
                )
            )
            content_ids = []
            for position in (1, 2):
                content = lifecycle.create_content(
                    run_id=f"weekly-2026-10-12-{position}",
                    weekly_batch_id=batch.id,
                    batch_position=position,
                    channel="master",
                    title=f"Draft {position}",
                    body="Complete draft",
                    status="queued_for_approval",
                )
                content_ids.append(content.id)
            batches.transition(batch.id, "validating")
            batches.transition(batch.id, "pending_approval")
            session.commit()
            batch_id = batch.id

        synced = self.client.post(f"/batches/{batch_id}/approvals/sync")
        first = self.client.post(
            f"/content/{content_ids[0]}/approval",
            json={"decision": "approved"},
        )
        pending = self.client.get(f"/batches/{batch_id}/approval-status")
        second = self.client.post(
            f"/content/{content_ids[1]}/approval",
            json={"decision": "approved"},
        )
        ready = self.client.get(f"/batches/{batch_id}/approval-status")

        self.assertEqual(synced.status_code, 200)
        self.assertEqual(synced.json()["pending_count"], 2)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(pending.json()["batch_status"], "pending_approval")
        self.assertEqual(pending.json()["approved_count"], 1)
        self.assertEqual(second.status_code, 200)
        self.assertTrue(ready.json()["ready"])
        self.assertEqual(ready.json()["batch_status"], "ready")

    def test_publish_is_dry_run_by_default_and_execute_is_guarded(self) -> None:
        content_id = self.create_linkedin_content()
        approved = self.client.post(
            f"/content/{content_id}/approval",
            json={"decision": "approved"},
        )
        self.assertEqual(approved.status_code, 200)

        dry_run = self.client.post(
            f"/content/{content_id}/publish",
            json={},
        )
        self.assertEqual(dry_run.status_code, 200)
        self.assertEqual(dry_run.json()["status"], "dry_run")
        self.linkedin.create_text_share.assert_not_called()

        with patch.dict(os.environ, {"PUBLISHING_KILL_SWITCH": "true"}):
            blocked = self.client.post(
                f"/content/{content_id}/publish",
                json={"execute": True},
            )
        self.assertEqual(blocked.status_code, 409)
        self.linkedin.create_text_share.assert_not_called()

    def test_approved_linkedin_content_publishes_once(self) -> None:
        content_id = self.create_linkedin_content()
        self.client.post(
            f"/content/{content_id}/approval",
            json={"decision": "approved"},
        )
        self.linkedin.create_text_share.return_value = LinkedInPublishResult(
            ok=True,
            status_code=201,
            post_urn="urn:li:share:123",
            response_body="{}",
            error="",
        )

        with patch.dict(os.environ, {"PUBLISHING_KILL_SWITCH": "false"}):
            published = self.client.post(
                f"/content/{content_id}/publish",
                json={"execute": True},
            )
            repeated = self.client.post(
                f"/content/{content_id}/publish",
                json={"execute": True},
            )

        self.assertEqual(published.status_code, 200)
        self.assertEqual(published.json()["status"], "published")
        self.assertEqual(repeated.status_code, 409)
        self.linkedin.create_text_share.assert_called_once_with(
            "A durable LinkedIn draft."
        )
        with self.factory() as session:
            job = session.scalar(select(PublishJobRecord))
            events = list(session.scalars(select(PublishEventRecord)))
            content = session.get(ContentItemRecord, content_id)
        self.assertEqual(job.status, "published")
        self.assertEqual(len(events), 1)
        self.assertEqual(content.status, "published")

    def test_failed_publish_attempt_is_persisted_for_audit(self) -> None:
        content_id = self.create_linkedin_content()
        self.client.post(
            f"/content/{content_id}/approval",
            json={"decision": "approved"},
        )
        self.linkedin.create_text_share.return_value = LinkedInPublishResult(
            ok=False,
            status_code=429,
            post_urn="",
            response_body="rate limited",
            error="Too many requests",
        )

        with patch.dict(os.environ, {"PUBLISHING_KILL_SWITCH": "false"}):
            response = self.client.post(
                f"/content/{content_id}/publish",
                json={"execute": True},
            )

        self.assertEqual(response.status_code, 502)
        with self.factory() as session:
            job = session.scalar(select(PublishJobRecord))
            event = session.scalar(select(PublishEventRecord))
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempts, 1)
        self.assertEqual(job.last_error, "Too many requests")
        self.assertEqual(event.status, "failed")

    def test_metrics_and_analytics_summary_use_database_state(self) -> None:
        content_id = self.create_linkedin_content()
        metric = self.client.post(
            "/metrics",
            json={
                "observation_date": "2026-10-06",
                "channel": "linkedin",
                "content_item_id": content_id,
                "values": {"impressions": 1200, "clicks": 18},
                "note": "First observation",
            },
        )
        summary = self.client.get("/analytics/summary")

        self.assertEqual(metric.status_code, 201)
        self.assertEqual(summary.status_code, 200)
        self.assertEqual(summary.json()["metrics_count"], 1)
        self.assertEqual(summary.json()["content"]["total"], 1)


if __name__ == "__main__":
    unittest.main()
