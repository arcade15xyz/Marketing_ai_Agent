from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from .ai_weekly import AIWeeklyBatchService
from .api_service import (
    ApiConflictError,
    ApiPublishFailedError,
    DatabaseContentPublisher,
    LinkedInClientFactory,
    publishing_kill_switch_enabled,
)
from .content_sources import (
    configured_content_source_mode,
    configured_weekly_post_count,
)
from .db_models import (
    ApprovalRecord,
    ContentItemRecord,
    PublishJobRecord,
    TopicRecord,
)
from .llm import LLMProvider, create_llm_provider
from .models import ContentSourceMode
from .repositories import WeeklyBatchRepository
from .weekly_import import JsonWeeklyBatchImporter
from .weekly_json import load_weekly_json


class SchedulerConfigurationError(RuntimeError):
    """Raised when a weekly scheduler command is missing required configuration."""


class WeeklyPreparationError(RuntimeError):
    """Raised when a weekly batch cannot be prepared or validated."""


@dataclass(frozen=True)
class WeeklyPreparationOutcome:
    week_start: date
    source_mode: str
    item_count: int
    dry_run: bool
    batch_id: str = ""
    content_item_ids: tuple[str, ...] = ()
    created: bool = False


ProviderFactory = Callable[[], LLMProvider]


class WeeklyPreparationService:
    """Select exactly one weekly source and prepare the complete durable batch."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        provider_factory: ProviderFactory = create_llm_provider,
    ) -> None:
        self.session_factory = session_factory
        self.provider_factory = provider_factory

    async def prepare(
        self,
        week_start: date,
        *,
        input_path: Path | str | None = None,
        count: int | None = None,
        dry_run: bool = False,
        environ: Mapping[str, str] | None = None,
    ) -> WeeklyPreparationOutcome:
        mode = configured_content_source_mode(environ)
        resolved_count = (
            configured_weekly_post_count(environ) if count is None else count
        )
        if not 1 <= resolved_count <= 7:
            raise SchedulerConfigurationError(
                "Weekly post count must be an integer between 1 and 7."
            )

        if mode is ContentSourceMode.JSON:
            if input_path is None:
                raise SchedulerConfigurationError(
                    "--input is required when CONTENT_SOURCE_MODE=json."
                )
            result = load_weekly_json(
                input_path,
                week_start=week_start,
                count=resolved_count,
            )
            if dry_run:
                return WeeklyPreparationOutcome(
                    week_start=week_start,
                    source_mode=mode.value,
                    item_count=len(result.items),
                    dry_run=True,
                )
            with self.session_factory() as session:
                imported = JsonWeeklyBatchImporter(session).import_batch(result)
                session.commit()
                return WeeklyPreparationOutcome(
                    week_start=week_start,
                    source_mode=mode.value,
                    item_count=len(result.items),
                    dry_run=False,
                    batch_id=imported.batch_id,
                    content_item_ids=imported.content_item_ids,
                    created=imported.created,
                )

        if dry_run:
            return self._validate_ai_capacity(week_start, resolved_count)

        prepared = await AIWeeklyBatchService(
            self.session_factory,
            self.provider_factory(),
        ).prepare(week_start, resolved_count)
        return WeeklyPreparationOutcome(
            week_start=week_start,
            source_mode=mode.value,
            item_count=len(prepared.result.items),
            dry_run=False,
            batch_id=prepared.batch_id,
            content_item_ids=prepared.content_item_ids,
            created=prepared.created,
        )

    def _validate_ai_capacity(
        self,
        week_start: date,
        count: int,
    ) -> WeeklyPreparationOutcome:
        with self.session_factory() as session:
            existing = WeeklyBatchRepository(session).latest_for_week(week_start)
            if existing is not None:
                if existing.source_mode != ContentSourceMode.AI.value:
                    raise WeeklyPreparationError(
                        "A weekly batch already exists with a different source mode."
                    )
                if existing.expected_item_count != count:
                    raise WeeklyPreparationError(
                        "The existing AI batch has a different expected item count."
                    )
                masters = WeeklyBatchRepository(session).master_items(existing.id)
                if len(masters) == count:
                    return WeeklyPreparationOutcome(
                        week_start=week_start,
                        source_mode=ContentSourceMode.AI.value,
                        item_count=count,
                        dry_run=True,
                        batch_id=existing.id,
                        content_item_ids=tuple(item.id for item in masters),
                        created=False,
                    )

            available = session.scalar(
                select(func.count(TopicRecord.id)).where(
                    TopicRecord.status == "unused"
                )
            ) or 0
            if available < count:
                raise WeeklyPreparationError(
                    f"AI mode requires {count} unused topics; only {available} are available."
                )

        return WeeklyPreparationOutcome(
            week_start=week_start,
            source_mode=ContentSourceMode.AI.value,
            item_count=count,
            dry_run=True,
        )


@dataclass(frozen=True)
class PublishDueOutcome:
    due_count: int
    dry_run_count: int
    published_count: int
    failed_count: int
    blocked_count: int
    blocked_messages: tuple[str, ...] = ()


class DuePublishService:
    """Process already-scheduled jobs without generating or scheduling content."""

    ELIGIBLE_STATUSES = ("ready", "failed", "retrying")

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        client_factory: LinkedInClientFactory,
    ) -> None:
        self.session_factory = session_factory
        self.client_factory = client_factory

    def publish_due(
        self,
        *,
        now: datetime | None = None,
        execute: bool = False,
        limit: int = 100,
        max_attempts: int = 3,
        environ: Mapping[str, str] | None = None,
    ) -> PublishDueOutcome:
        if limit < 1:
            raise SchedulerConfigurationError("limit must be at least 1.")
        if max_attempts < 1:
            raise SchedulerConfigurationError("max_attempts must be at least 1.")
        if execute and publishing_kill_switch_enabled(environ):
            raise ApiConflictError(
                "Publishing is blocked because PUBLISHING_KILL_SWITCH is enabled."
            )

        instant = now or datetime.now(UTC)
        with self.session_factory() as session:
            due_ids = list(
                session.scalars(
                    select(PublishJobRecord.id)
                    .join(
                        ContentItemRecord,
                        PublishJobRecord.content_item_id == ContentItemRecord.id,
                    )
                    .join(
                        ApprovalRecord,
                        ApprovalRecord.content_item_id == ContentItemRecord.id,
                    )
                    .where(
                        PublishJobRecord.scheduled_at.is_not(None),
                        PublishJobRecord.scheduled_at <= instant,
                        PublishJobRecord.status.in_(self.ELIGIBLE_STATUSES),
                        PublishJobRecord.attempts < max_attempts,
                        PublishJobRecord.channel == "linkedin",
                        ContentItemRecord.status == "queued_for_approval",
                        ApprovalRecord.status == "approved",
                    )
                    .order_by(PublishJobRecord.scheduled_at, PublishJobRecord.created_at)
                    .limit(limit)
                )
            )

        dry_runs = 0
        published = 0
        failed = 0
        blocked = 0
        blocked_messages: list[str] = []
        for job_id in due_ids:
            with self.session_factory() as session:
                claim = select(PublishJobRecord).where(
                    PublishJobRecord.id == job_id,
                    PublishJobRecord.status.in_(self.ELIGIBLE_STATUSES),
                    PublishJobRecord.attempts < max_attempts,
                )
                if execute and session.get_bind().dialect.name == "postgresql":
                    claim = claim.with_for_update(skip_locked=True)
                job = session.scalar(claim.limit(1))
                if job is None:
                    continue
                if execute:
                    job.status = "publishing"
                    session.flush()
                try:
                    outcome = DatabaseContentPublisher(
                        session,
                        client_factory=self.client_factory,
                    ).publish(
                        job.content_item_id,
                        execute=execute,
                        publish_job_id=job.id,
                        environ=environ,
                    )
                except ApiPublishFailedError as exc:
                    session.commit()
                    failed += 1
                    blocked_messages.append(str(exc))
                except ApiConflictError as exc:
                    session.rollback()
                    blocked += 1
                    blocked_messages.append(str(exc))
                else:
                    session.commit()
                    if outcome.status == "published":
                        published += 1
                    else:
                        dry_runs += 1

        return PublishDueOutcome(
            due_count=len(due_ids),
            dry_run_count=dry_runs,
            published_count=published,
            failed_count=failed,
            blocked_count=blocked,
            blocked_messages=tuple(blocked_messages),
        )
