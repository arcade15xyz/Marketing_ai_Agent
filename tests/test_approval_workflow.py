from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.approval_workflow import (
    ApprovalWorkflowStateError,
    WeeklyApprovalService,
)
from src.marketing_agents.db_models import ApprovalRecord, Base
from src.marketing_agents.models import (
    ContentSourceMode,
    WeeklyBatchSpec,
    WeeklyBatchStatus,
)
from src.marketing_agents.repositories import LifecycleRepository, WeeklyBatchRepository


class WeeklyApprovalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.factory()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def create_pending_batch(self):
        batches = WeeklyBatchRepository(self.session)
        lifecycle = LifecycleRepository(self.session)
        batch = batches.create(
            WeeklyBatchSpec(
                week_start=date(2026, 10, 5),
                source_mode=ContentSourceMode.AI,
                expected_item_count=2,
            )
        )
        required = []
        for position in (1, 2):
            master = lifecycle.create_content(
                run_id=f"weekly-2026-10-05-{position}",
                weekly_batch_id=batch.id,
                batch_position=position,
                channel="master",
                title=f"Master {position}",
                body="Authoritative content",
                status="queued_for_approval",
            )
            required.append(master)
            if position == 1:
                linked_in = lifecycle.create_content(
                    run_id=f"weekly-2026-10-05-{position}-linkedin",
                    weekly_batch_id=batch.id,
                    batch_position=position,
                    parent_content_id=master.id,
                    channel="linkedin",
                    title="LinkedIn draft",
                    body="LinkedIn content",
                    status="queued_for_approval",
                )
                required.append(linked_in)
                lifecycle.create_content(
                    run_id=f"weekly-2026-10-05-{position}-reddit",
                    weekly_batch_id=batch.id,
                    batch_position=position,
                    parent_content_id=master.id,
                    channel="reddit",
                    title="Reddit draft",
                    body="Reddit content",
                    status="needs_rules_check",
                )
        batches.transition(batch.id, WeeklyBatchStatus.VALIDATING)
        batches.transition(batch.id, WeeklyBatchStatus.PENDING_APPROVAL)
        self.session.flush()
        return batch, required

    def test_sync_creates_only_required_approval_records(self) -> None:
        batch, required = self.create_pending_batch()

        summary = WeeklyApprovalService(self.session).ensure_batch_approvals(batch.id)
        approvals = list(self.session.scalars(select(ApprovalRecord)))

        self.assertEqual(summary.required_count, 3)
        self.assertEqual(summary.pending_count, 3)
        self.assertEqual(summary.missing_count, 0)
        self.assertFalse(summary.ready)
        self.assertEqual(
            {approval.content_item_id for approval in approvals},
            {content.id for content in required},
        )

    def test_final_approval_marks_batch_ready_and_revocation_demotes_it(self) -> None:
        batch, required = self.create_pending_batch()
        service = WeeklyApprovalService(self.session)
        service.ensure_batch_approvals(batch.id)

        for content in required[:-1]:
            update = service.decide(content.id, decision="approved")
            self.assertEqual(update.weekly_summary.batch_status, "pending_approval")

        final = service.decide(required[-1].id, decision="approved")

        self.assertTrue(final.weekly_summary.ready)
        self.assertEqual(final.weekly_summary.batch_status, "ready")
        self.assertEqual(batch.status, "ready")
        self.assertIsNotNone(batch.finalized_at)

        revoked = service.decide(
            required[0].id,
            decision="needs_changes",
            note="Add a primary source.",
        )

        self.assertFalse(revoked.weekly_summary.ready)
        self.assertEqual(revoked.weekly_summary.batch_status, "pending_approval")
        self.assertEqual(revoked.weekly_summary.needs_changes_count, 1)
        self.assertIsNone(batch.finalized_at)

    def test_publishing_batch_rejects_approval_changes(self) -> None:
        batch, required = self.create_pending_batch()
        service = WeeklyApprovalService(self.session)
        service.ensure_batch_approvals(batch.id)
        for content in required:
            service.decide(content.id, decision="approved")
        WeeklyBatchRepository(self.session).transition(
            batch.id,
            WeeklyBatchStatus.PUBLISHING,
        )

        with self.assertRaisesRegex(ApprovalWorkflowStateError, "cannot change"):
            service.decide(required[0].id, decision="needs_changes")

        approval = self.session.scalar(
            select(ApprovalRecord).where(
                ApprovalRecord.content_item_id == required[0].id
            )
        )
        self.assertEqual(approval.status, "approved")


if __name__ == "__main__":
    unittest.main()
