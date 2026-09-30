from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db_models import ApprovalRecord, ContentItemRecord
from .models import WeeklyBatchStatus
from .repositories import LifecycleRepository, WeeklyBatchRepository


class ApprovalWorkflowError(RuntimeError):
    """Raised when weekly approval state cannot be evaluated safely."""


class ApprovalWorkflowStateError(ApprovalWorkflowError):
    """Raised when an approval is changed after publishing has started."""


@dataclass(frozen=True)
class WeeklyApprovalSummary:
    batch_id: str
    batch_status: str
    required_count: int
    approved_count: int
    pending_count: int
    needs_changes_count: int
    rejected_count: int
    missing_count: int
    ready: bool


@dataclass(frozen=True)
class ApprovalUpdate:
    approval: ApprovalRecord
    weekly_summary: WeeklyApprovalSummary | None


class WeeklyApprovalService:
    """Maintain per-content approvals and the weekly batch readiness gate."""

    LOCKED_BATCH_STATUSES = {
        WeeklyBatchStatus.PUBLISHING.value,
        WeeklyBatchStatus.COMPLETED.value,
        WeeklyBatchStatus.CANCELLED.value,
        WeeklyBatchStatus.REPLACED.value,
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def ensure_batch_approvals(self, batch_id: str) -> WeeklyApprovalSummary:
        batch = WeeklyBatchRepository(self.session).get(batch_id)
        required = self._required_content(batch.id)
        if not required:
            raise ApprovalWorkflowError(
                "Weekly batch has no content requiring approval."
            )

        lifecycle = LifecycleRepository(self.session)
        for content in required:
            lifecycle.ensure_approval(content_item_id=content.id)
        return self._refresh(batch.id)

    def summary(self, batch_id: str) -> WeeklyApprovalSummary:
        batch = WeeklyBatchRepository(self.session).get(batch_id)
        return self._summary(batch.id)

    def decide(
        self,
        content_item_id: str,
        *,
        decision: str,
        note: str = "",
    ) -> ApprovalUpdate:
        content = self.session.get(ContentItemRecord, content_item_id)
        if content is None:
            raise ApprovalWorkflowError(
                f"Content item not found: {content_item_id}"
            )

        if content.weekly_batch_id is not None:
            batch = WeeklyBatchRepository(self.session).get(
                content.weekly_batch_id
            )
            if batch.status in self.LOCKED_BATCH_STATUSES:
                raise ApprovalWorkflowStateError(
                    f"Approvals cannot change while weekly batch is {batch.status}."
                )

        approval = LifecycleRepository(self.session).ensure_approval(
            content_item_id=content.id,
            status=decision,
            notes=note,
            decided_at=datetime.now(UTC),
            update_existing=True,
        )
        summary = (
            self._refresh(content.weekly_batch_id)
            if content.weekly_batch_id is not None
            else None
        )
        return ApprovalUpdate(approval=approval, weekly_summary=summary)

    def _refresh(self, batch_id: str) -> WeeklyApprovalSummary:
        batch = WeeklyBatchRepository(self.session).get(batch_id)
        summary = self._summary(batch.id)
        batches = WeeklyBatchRepository(self.session)

        if (
            summary.ready
            and batch.status == WeeklyBatchStatus.PENDING_APPROVAL.value
        ):
            batches.transition(batch.id, WeeklyBatchStatus.READY)
        elif (
            not summary.ready
            and batch.status == WeeklyBatchStatus.READY.value
        ):
            batches.transition(batch.id, WeeklyBatchStatus.PENDING_APPROVAL)

        if batch.status != summary.batch_status:
            summary = self._summary(batch.id)
        return summary

    def _summary(self, batch_id: str) -> WeeklyApprovalSummary:
        batch = WeeklyBatchRepository(self.session).get(batch_id)
        required = self._required_content(batch.id)
        approvals = {
            approval.content_item_id: approval
            for approval in self.session.scalars(
                select(ApprovalRecord).where(
                    ApprovalRecord.content_item_id.in_(
                        [content.id for content in required]
                    )
                )
            )
        } if required else {}

        counts = {
            "approved": 0,
            "pending": 0,
            "needs_changes": 0,
            "rejected": 0,
        }
        missing = 0
        for content in required:
            approval = approvals.get(content.id)
            if approval is None:
                missing += 1
            elif approval.status in counts:
                counts[approval.status] += 1
            else:
                counts["pending"] += 1

        ready = bool(required) and counts["approved"] == len(required)
        return WeeklyApprovalSummary(
            batch_id=batch.id,
            batch_status=batch.status,
            required_count=len(required),
            approved_count=counts["approved"],
            pending_count=counts["pending"],
            needs_changes_count=counts["needs_changes"],
            rejected_count=counts["rejected"],
            missing_count=missing,
            ready=ready,
        )

    def _required_content(self, batch_id: str) -> list[ContentItemRecord]:
        items = list(
            self.session.scalars(
                select(ContentItemRecord)
                .where(ContentItemRecord.weekly_batch_id == batch_id)
                .order_by(
                    ContentItemRecord.batch_position,
                    ContentItemRecord.channel,
                )
            )
        )
        return [
            item
            for item in items
            if item.channel == "master"
            or item.status == "queued_for_approval"
        ]
