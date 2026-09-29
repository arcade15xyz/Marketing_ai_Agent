from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db_models import (
    AgentRunRecord,
    ApprovalRecord,
    ContentItemRecord,
    MetricRecord,
    PublishEventRecord,
    PublishJobRecord,
    ResearchSourceRecord,
    SystemEventRecord,
    TopicRecord,
    WeeklyBatchRecord,
)
from .models import ContentSourceMode, WeeklyBatchSpec, WeeklyBatchStatus

class WeeklyBatchStateError(RuntimeError):
    """Raised when a weekly batch transition is invalid."""

class WeeklyBatchValidationError(RuntimeError):
    """Raised when a weekly batch is incomplete or inconsistent."""


class WeeklyBatchRepository:
    _TRANSITIONS = {
        "draft": {"validating", "incomplete", "failed", "cancelled", "replaced"},
        "validating": {
            "pending_approval",
            "incomplete",
            "failed",
            "cancelled",
            "replaced",
        },
        "pending_approval": {
            "ready",
            "incomplete",
            "failed",
            "cancelled",
            "replaced",
        },
        "ready": {"publishing", "cancelled", "replaced"},
        "publishing": {"completed", "failed", "cancelled"},
        "incomplete": {"draft", "cancelled", "replaced"},
        "failed": {"draft", "cancelled", "replaced"},
        "completed": {"replaced"},
        "cancelled": set(),
        "replaced": set(),
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self,
        spec: WeeklyBatchSpec,
        *,
        configuration: Mapping[str, Any] | None = None,
    ) -> WeeklyBatchRecord:
        existing = self.latest_for_week(spec.week_start)
        if existing is not None:
            return existing
        return self._create_record(spec, version=1, configuration=configuration)

    def latest_for_week(self, week_start: date) -> WeeklyBatchRecord | None:
        return self.session.scalar(
            select(WeeklyBatchRecord)
            .where(WeeklyBatchRecord.week_start == week_start)
            .order_by(WeeklyBatchRecord.version.desc())
            .limit(1)
        )

    def get(self, batch_id: str) -> WeeklyBatchRecord:
        batch = self.session.get(WeeklyBatchRecord, batch_id)
        if batch is None:
            raise WeeklyBatchValidationError(f"Weekly batch not found: {batch_id}")
        return batch

    def replace(
        self,
        batch_id: str,
        spec: WeeklyBatchSpec,
        *,
        configuration: Mapping[str, Any] | None = None,
    ) -> WeeklyBatchRecord:
        current = self.get(batch_id)
        latest = self.latest_for_week(current.week_start)
        if latest is None or latest.id != current.id:
            raise WeeklyBatchStateError("Only the latest weekly batch version can be replaced.")
        if spec.week_start != current.week_start:
            raise WeeklyBatchValidationError(
                "A replacement must use the same week_start as the existing batch."
            )
        current.status = WeeklyBatchStatus.REPLACED.value
        current.finalized_at = datetime.now(UTC)
        replacement = self._create_record(
            spec,
            version=current.version + 1,
            configuration=configuration,
        )
        self.session.flush()
        return replacement

    def transition(
        self,
        batch_id: str,
        target: WeeklyBatchStatus | str,
        *,
        reason: str = "",
    ) -> WeeklyBatchRecord:
        batch = self.get(batch_id)
        try:
            target_status = WeeklyBatchStatus(target)
        except ValueError as exc:
            raise WeeklyBatchStateError(f"Unknown weekly batch status: {target}") from exc

        if batch.status == target_status.value:
            return batch
        allowed = self._TRANSITIONS.get(batch.status, set())
        if target_status.value not in allowed:
            raise WeeklyBatchStateError(
                f"Cannot transition weekly batch from {batch.status} "
                f"to {target_status.value}."
            )
        if target_status is WeeklyBatchStatus.READY:
            self._ensure_expected_items(batch)
        if target_status in {
            WeeklyBatchStatus.INCOMPLETE,
            WeeklyBatchStatus.FAILED,
        } and not reason.strip():
            raise WeeklyBatchValidationError(
                f"A reason is required when marking a batch {target_status.value}."
            )

        batch.status = target_status.value
        batch.failure_reason = reason.strip()
        if target_status in {
            WeeklyBatchStatus.READY,
            WeeklyBatchStatus.COMPLETED,
            WeeklyBatchStatus.CANCELLED,
            WeeklyBatchStatus.REPLACED,
        }:
            batch.finalized_at = datetime.now(UTC)
        self.session.flush()
        return batch

    def master_items(self, batch_id: str) -> list[ContentItemRecord]:
        return list(
            self.session.scalars(
                select(ContentItemRecord)
                .where(
                    ContentItemRecord.weekly_batch_id == batch_id,
                    ContentItemRecord.parent_content_id.is_(None),
                    ContentItemRecord.channel == "master",
                )
                .order_by(ContentItemRecord.batch_position)
            )
        )

    def _ensure_expected_items(self, batch: WeeklyBatchRecord) -> None:
        positions = {item.batch_position for item in self.master_items(batch.id)}
        expected = set(range(1, batch.expected_item_count + 1))
        if positions != expected:
            raise WeeklyBatchValidationError(
                "Weekly batch cannot become ready until every expected master "
                f"position exists; expected {sorted(expected)}, found "
                f"{sorted(position for position in positions if position is not None)}."
            )

    def _create_record(
        self,
        spec: WeeklyBatchSpec,
        *,
        version: int,
        configuration: Mapping[str, Any] | None,
    ) -> WeeklyBatchRecord:
        snapshot = dict(configuration or {})
        snapshot.update(
            {
                "source_mode": spec.source_mode.value,
                "expected_item_count": spec.expected_item_count,
            }
        )
        batch = WeeklyBatchRecord(
            week_start=spec.week_start,
            week_end=spec.week_end,
            version=version,
            source_mode=spec.source_mode.value,
            status=WeeklyBatchStatus.DRAFT.value,
            expected_item_count=spec.expected_item_count,
            configuration_snapshot=snapshot,
        )
        self.session.add(batch)
        self.session.flush()
        return batch




class TopicStateError(RuntimeError):
    """Raised when a topic transition does not match its current state."""


class TopicRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(
        self,
        *,
        pillar: str,
        name: str,
        angle: str,
        format: str,
        sources: list[str] | None = None,
        source: str = "manual",
        priority: int = 0,
    ) -> TopicRecord:
        existing = self.session.scalar(select(TopicRecord).where(TopicRecord.name == name))
        if existing is not None:
            return existing

        topic = TopicRecord(
            pillar=pillar,
            name=name,
            angle=angle,
            format=format,
            source=source,
            priority=priority,
        )
        self.session.add(topic)
        self.session.flush()
        for url in sources or []:
            self.session.add(
                ResearchSourceRecord(
                    topic_id=topic.id,
                    url=url,
                    validation_state="seeded",
                )
            )
        return topic

    def list(self, *, status: str | None = None) -> list[TopicRecord]:
        statement = select(TopicRecord).order_by(TopicRecord.priority.desc(), TopicRecord.created_at)
        if status is not None:
            statement = statement.where(TopicRecord.status == status)
        return list(self.session.scalars(statement))

    def reserve_next(
        self,
        *,
        run_id: str,
        last_pillar: str | None = None,
    ) -> TopicRecord | None:
        existing = self.session.scalar(
            select(TopicRecord).where(
                TopicRecord.status.in_(["reserved", "used"]),
                TopicRecord.reserved_by_run_id == run_id,
            )
        )
        if existing is not None:
            return existing

        base = select(TopicRecord).where(TopicRecord.status == "unused")
        if last_pillar:
            preferred = base.where(TopicRecord.pillar != last_pillar)
            candidate = self._locked_first(preferred)
        else:
            candidate = None

        if candidate is None:
            candidate = self._locked_first(base)

        if candidate is None:
            self.session.add(
                SystemEventRecord(
                    event_type="TOPIC_BACKLOG_EXHAUSTED",
                    payload={"run_id": run_id},
                )
            )
            self.session.flush()
            return None

        candidate.status = "reserved"
        candidate.reserved_by_run_id = run_id
        candidate.reserved_at = datetime.now(UTC)
        self.session.flush()
        return candidate

    def _locked_first(self, statement):
        statement = statement.order_by(TopicRecord.priority.desc(), TopicRecord.created_at)
        if self.session.get_bind().dialect.name == "postgresql":
            statement = statement.with_for_update(skip_locked=True)
        return self.session.scalar(statement.limit(1))

    def sources(self, topic_id: str) -> list[str]:
        return list(
            self.session.scalars(
                select(ResearchSourceRecord.url)
                .where(ResearchSourceRecord.topic_id == topic_id)
                .order_by(ResearchSourceRecord.created_at)
            )
        )

    def last_used_pillar(self) -> str | None:
        return self.session.scalar(
            select(TopicRecord.pillar)
            .where(TopicRecord.status == "used")
            .order_by(TopicRecord.used_at.desc())
            .limit(1)
        )
    def mark_used(self, *, topic_id: str, run_id: str) -> TopicRecord:
        topic = self.session.get(TopicRecord, topic_id)
        if topic is None:
            raise TopicStateError(f"Topic not found: {topic_id}")
        if topic.status == "used" and topic.reserved_by_run_id == run_id:
            return topic
        if topic.status != "reserved" or topic.reserved_by_run_id != run_id:
            raise TopicStateError("Only the run that reserved a topic can mark it used.")

        topic.status = "used"
        topic.used_at = datetime.now(UTC)
        self.session.flush()
        return topic

    def release(self, *, topic_id: str, run_id: str) -> TopicRecord:
        topic = self.session.get(TopicRecord, topic_id)
        if topic is None:
            raise TopicStateError(f"Topic not found: {topic_id}")
        if topic.status != "reserved" or topic.reserved_by_run_id != run_id:
            raise TopicStateError("Only the run that reserved a topic can release it.")

        topic.status = "unused"
        topic.reserved_by_run_id = None
        topic.reserved_at = None
        topic.failure_count += 1
        self.session.flush()
        return topic

    def stats(self) -> dict[str, int]:
        rows = self.session.execute(
            select(TopicRecord.status, func.count(TopicRecord.id)).group_by(TopicRecord.status)
        )
        result = {"total": 0, "unused": 0, "reserved": 0, "used": 0, "failed": 0}
        for status, count in rows:
            result[status] = count
            result["total"] += count
        result["failed"] = self.session.scalar(
            select(func.count(TopicRecord.id)).where(TopicRecord.failure_count > 0)
        ) or 0
        return result


class LifecycleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_content(
        self,
        *,
        run_id: str,
        channel: str,
        title: str,
        body: str,
        status: str,
        weekly_batch_id: str | None = None,
        source_mode: ContentSourceMode | str | None = None,
        batch_position: int | None = None,
        topic_id: str | None = None,
        parent_content_id: str | None = None,
        version: int = 1,
        metadata: Mapping[str, Any] | None = None,
    ) -> ContentItemRecord:
        resolved_source_mode = (
            source_mode.value
            if isinstance(source_mode, ContentSourceMode)
            else source_mode
        )
        existing = self.session.scalar(
            select(ContentItemRecord).where(
                ContentItemRecord.run_id == run_id,
                ContentItemRecord.channel == channel,
                ContentItemRecord.version == version,
            )
        )
        if existing is not None:
            if (
                weekly_batch_id is not None
                and existing.weekly_batch_id != weekly_batch_id
            ):
                raise WeeklyBatchValidationError(
                    "An existing content item cannot be moved to another weekly batch."
                )
            if resolved_source_mode is not None and (
                existing.source_mode != resolved_source_mode
            ):
                raise WeeklyBatchValidationError(
                    "An existing content item's source mode cannot be changed."
                )
            return existing

        if weekly_batch_id is None:
            if batch_position is not None:
                raise WeeklyBatchValidationError(
                    "batch_position requires a weekly_batch_id."
                )
        else:
            batch = WeeklyBatchRepository(self.session).get(weekly_batch_id)
            if batch_position is None:
                raise WeeklyBatchValidationError(
                    "Weekly batch content requires a batch_position."
                )
            if not 1 <= batch_position <= batch.expected_item_count:
                raise WeeklyBatchValidationError(
                    "batch_position must be within the batch's expected item count."
                )
            if resolved_source_mode is None:
                resolved_source_mode = batch.source_mode
            if resolved_source_mode != batch.source_mode:
                raise WeeklyBatchValidationError(
                    "Content source mode must match its weekly batch."
                )

        item = ContentItemRecord(
            run_id=run_id,
            weekly_batch_id=weekly_batch_id,
            source_mode=resolved_source_mode,
            batch_position=batch_position,
            topic_id=topic_id,
            parent_content_id=parent_content_id,
            channel=channel,
            title=title,
            body=body,
            status=status,
            version=version,
            metadata_json=dict(metadata or {}),
        )
        self.session.add(item)
        self.session.flush()
        return item

    def ensure_approval(
        self,
        *,
        content_item_id: str,
        status: str = "pending",
        notes: str = "",
        decided_at: datetime | None = None,
        update_existing: bool = False,
    ) -> ApprovalRecord:
        approval = self.session.scalar(
            select(ApprovalRecord).where(ApprovalRecord.content_item_id == content_item_id)
        )
        if approval is None:
            approval = ApprovalRecord(
                content_item_id=content_item_id,
                status=status,
                reviewer_notes=notes,
            )
            self.session.add(approval)
        elif update_existing:
            approval.status = status
            approval.reviewer_notes = notes
        if decided_at is not None:
            approval.decided_at = decided_at
        self.session.flush()
        return approval

    def content_for_run(self, *, run_id: str, channel: str) -> ContentItemRecord | None:
        return self.session.scalar(
            select(ContentItemRecord).where(
                ContentItemRecord.run_id == run_id,
                ContentItemRecord.channel == channel,
            )
        )

    def approval_for_run(self, *, run_id: str, channel: str) -> ApprovalRecord | None:
        return self.session.scalar(
            select(ApprovalRecord)
            .join(ContentItemRecord, ApprovalRecord.content_item_id == ContentItemRecord.id)
            .where(
                ContentItemRecord.run_id == run_id,
                ContentItemRecord.channel == channel,
            )
        )

    def decide_approval(
        self,
        *,
        run_id: str,
        channel: str,
        decision: str,
        note: str = "",
    ) -> ApprovalRecord | None:
        approval = self.approval_for_run(run_id=run_id, channel=channel)
        if approval is None:
            return None
        approval.status = decision
        approval.reviewer_notes = note
        approval.decided_at = datetime.now(UTC)
        self.session.flush()
        return approval

    def ensure_publish_job(
        self,
        *,
        content_item_id: str,
        channel: str,
        idempotency_key: str,
        status: str = "pending",
    ) -> PublishJobRecord:
        existing = self.session.scalar(
            select(PublishJobRecord).where(PublishJobRecord.idempotency_key == idempotency_key)
        )
        if existing is not None:
            return existing
        job = PublishJobRecord(
            content_item_id=content_item_id,
            channel=channel,
            idempotency_key=idempotency_key,
            status=status,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def add_publish_event(
        self,
        *,
        publish_job_id: str,
        status: str,
        external_post_id: str = "",
        message: str = "",
        response_metadata: Mapping[str, Any] | None = None,
    ) -> PublishEventRecord:
        event = PublishEventRecord(
            publish_job_id=publish_job_id,
            status=status,
            external_post_id=external_post_id,
            message=message,
            response_metadata=dict(response_metadata or {}),
        )
        self.session.add(event)
        self.session.flush()
        return event

    def add_metric(
        self,
        *,
        observation_date: date,
        channel: str,
        values: Mapping[str, Any],
        content_item_id: str | None = None,
        note: str = "",
    ) -> MetricRecord:
        metric = MetricRecord(
            observation_date=observation_date,
            channel=channel,
            values=dict(values),
            content_item_id=content_item_id,
            note=note,
        )
        self.session.add(metric)
        self.session.flush()
        return metric

    def add_agent_run(
        self,
        *,
        run_date: date,
        agent: str,
        status: str,
        inputs: Mapping[str, Any] | None = None,
        outputs: Mapping[str, Any] | None = None,
    ) -> AgentRunRecord:
        run = AgentRunRecord(
            run_date=run_date,
            agent=agent,
            status=status,
            inputs=dict(inputs or {}),
            outputs=dict(outputs or {}),
        )
        self.session.add(run)
        self.session.flush()
        return run
