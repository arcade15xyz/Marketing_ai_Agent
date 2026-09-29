from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, field_validator
from sqlalchemy.orm import Session, sessionmaker

from .agents import RepurposerAgent, TechnicalReviewerAgent
from .db_models import SystemEventRecord, TopicRecord
from .llm import LLMProvider
from .llm_tracking import DatabaseLLMRunRecorder
from .models import (
    ContentSourceMode,
    Draft,
    Topic,
    StrategyBrief,
    WeeklyBatchResult,
    WeeklyBatchSpec,
    WeeklyBatchStatus,
    WeeklyContentItem,
)
from .prompts import PromptTemplate
from .repositories import LifecycleRepository, TopicRepository, WeeklyBatchRepository


AI_WRITER_PROMPT = PromptTemplate(
    name="weekly_ai_writer",
    version="v1",
    system=(
        "You write technically grounded long-form marketing content for AOSP, "
        "embedded Android, BSP, automotive, and IoT engineering audiences. "
        "Return a complete article, not an outline. Do not invent facts or sources."
    ),
    user_template=(
        "Write one complete blog article.\n"
        "Topic: {topic}\n"
        "Pillar: {pillar}\n"
        "Angle: {angle}\n"
        "Requested format: {format}\n"
        "Approved sources:\n{sources}\n\n"
        "The body must be publication-ready Markdown. Avoid unsupported claims. "
        "Do not include placeholders or verification markers."
    ),
)


class AIWeeklyPreparationError(RuntimeError):
    """Raised when an AI weekly batch cannot be completed safely."""


class AIWeeklyBatchIncompleteError(AIWeeklyPreparationError):
    """Raised when the topic backlog cannot fill every configured slot."""


class AIWeeklyBatchConflictError(AIWeeklyPreparationError):
    """Raised when AI preparation conflicts with an existing weekly batch."""


class AIBlogOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    body: str

    @field_validator("title", "body")
    @classmethod
    def require_complete_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


@dataclass(frozen=True)
class TopicReservation:
    position: int
    reservation_id: str
    topic_id: str
    topic: Topic


@dataclass(frozen=True)
class AIPreparedWeeklyBatch:
    batch_id: str
    content_item_ids: tuple[str, ...]
    result: WeeklyBatchResult
    created: bool


class AIWeeklyBatchService:
    """Generate and persist one complete AI-authored weekly batch."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: LLMProvider,
        *,
        recorder: DatabaseLLMRunRecorder | None = None,
        reviewer: TechnicalReviewerAgent | None = None,
        repurposer: RepurposerAgent | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.recorder = recorder or DatabaseLLMRunRecorder(session_factory)
        self.reviewer = reviewer or TechnicalReviewerAgent()
        self.repurposer = repurposer or RepurposerAgent()

    async def prepare(
        self,
        week_start: date,
        count: int,
    ) -> AIPreparedWeeklyBatch:
        spec = WeeklyBatchSpec(
            week_start=week_start,
            source_mode=ContentSourceMode.AI,
            expected_item_count=count,
        )
        batch_id, created, existing = self._open_batch(spec)
        if existing is not None:
            return existing

        reservations = self._reserve_topics(batch_id, spec)

        try:
            result = await self._generate(spec, batch_id, reservations)
            content_ids = self._persist(batch_id, result, reservations)
        except Exception as exc:
            self._fail_batch(batch_id, reservations, exc)
            raise

        return AIPreparedWeeklyBatch(
            batch_id=batch_id,
            content_item_ids=content_ids,
            result=result,
            created=created,
        )

    def _open_batch(
        self,
        spec: WeeklyBatchSpec,
    ) -> tuple[str, bool, AIPreparedWeeklyBatch | None]:
        with self.session_factory() as session:
            batches = WeeklyBatchRepository(session)
            batch = batches.latest_for_week(spec.week_start)
            created = batch is None
            if batch is None:
                batch = batches.create(
                    spec,
                    configuration={
                        "prompt_version": AI_WRITER_PROMPT.identifier,
                    },
                )
            elif batch.source_mode != ContentSourceMode.AI.value:
                raise AIWeeklyBatchConflictError(
                    "A weekly batch already exists with a different source mode."
                )
            elif batch.expected_item_count != spec.expected_item_count:
                raise AIWeeklyBatchConflictError(
                    "The existing AI batch has a different expected item count."
                )

            masters = batches.master_items(batch.id)
            if len(masters) == batch.expected_item_count:
                result = self._result_from_records(spec, masters)
                prepared = AIPreparedWeeklyBatch(
                    batch_id=batch.id,
                    content_item_ids=tuple(item.id for item in masters),
                    result=result,
                    created=False,
                )
                session.commit()
                return batch.id, False, prepared
            if masters:
                raise AIWeeklyBatchConflictError(
                    "The existing AI batch is partially persisted and requires "
                    "explicit recovery."
                )
            if batch.status in {
                WeeklyBatchStatus.FAILED.value,
                WeeklyBatchStatus.INCOMPLETE.value,
            }:
                batches.transition(batch.id, WeeklyBatchStatus.DRAFT)
            elif batch.status != WeeklyBatchStatus.DRAFT.value:
                raise AIWeeklyBatchConflictError(
                    f"The existing AI batch is {batch.status} and cannot be regenerated."
                )

            batch_id = batch.id
            session.commit()
            return batch_id, created, None

    def _reserve_topics(
        self,
        batch_id: str,
        spec: WeeklyBatchSpec,
    ) -> tuple[TopicReservation, ...]:
        with self.session_factory() as session:
            repository = TopicRepository(session)
            reservations: list[TopicReservation] = []
            last_pillar = repository.last_used_pillar()
            for position in range(1, spec.expected_item_count + 1):
                reservation_id = self._reservation_id(batch_id, position)
                topic = repository.reserve_next(
                    run_id=reservation_id,
                    last_pillar=last_pillar,
                )
                if topic is None:
                    for reserved in reservations:
                        repository.release(
                            topic_id=reserved.topic_id,
                            run_id=reserved.reservation_id,
                        )
                    batch = WeeklyBatchRepository(session).get(batch_id)
                    WeeklyBatchRepository(session).transition(
                        batch.id,
                        WeeklyBatchStatus.INCOMPLETE,
                        reason=(
                            "The topic backlog could not supply "
                            f"{spec.expected_item_count} unique topics."
                        ),
                    )
                    session.add(
                        SystemEventRecord(
                            event_type="WEEKLY_BATCH_INCOMPLETE",
                            payload={
                                "batch_id": batch_id,
                                "week_start": spec.week_start.isoformat(),
                                "expected_item_count": spec.expected_item_count,
                                "reserved_item_count": len(reservations),
                            },
                        )
                    )
                    session.commit()
                    raise AIWeeklyBatchIncompleteError(
                        "The topic backlog does not contain enough unique topics."
                    )

                domain_topic = self._domain_topic(repository, topic)
                reservations.append(
                    TopicReservation(
                        position=position,
                        reservation_id=reservation_id,
                        topic_id=topic.id,
                        topic=domain_topic,
                    )
                )
                last_pillar = topic.pillar

            session.commit()
            return tuple(reservations)

    async def _generate(
        self,
        spec: WeeklyBatchSpec,
        batch_id: str,
        reservations: tuple[TopicReservation, ...],
    ) -> WeeklyBatchResult:
        items: list[WeeklyContentItem] = []
        model_names: set[str] = set()
        for reservation in reservations:
            topic = reservation.topic
            agent_run_id = self.recorder.begin(
                run_date=spec.week_start,
                agent="weekly_ai_writer",
                prompt_version=AI_WRITER_PROMPT.identifier,
                input_metadata={
                    "batch_id": batch_id,
                    "topic_id": reservation.topic_id,
                    "position": reservation.position,
                },
            )
            try:
                llm_result = await self.provider.generate(
                    system_prompt=AI_WRITER_PROMPT.system,
                    user_prompt=AI_WRITER_PROMPT.render_user(
                        topic=topic.topic,
                        pillar=topic.pillar,
                        angle=topic.angle,
                        format=topic.format,
                        sources="\n".join(f"- {source}" for source in topic.sources),
                    ),
                    response_schema=AIBlogOutput,
                    prompt_version=AI_WRITER_PROMPT.identifier,
                )
                if llm_result.parsed is None:
                    raise AIWeeklyPreparationError(
                        "The AI provider returned no structured blog output."
                    )
                draft = Draft(
                    title=llm_result.parsed.title,
                    body=llm_result.parsed.body,
                    sources=topic.sources,
                )
                review = self.reviewer.run(draft)
                if review.status != "pass":
                    raise AIWeeklyPreparationError(
                        "Technical review blocked generated content: "
                        + "; ".join(review.notes)
                    )
                brief = StrategyBrief(
                    run_date=spec.week_start.isoformat(),
                    topic=topic,
                    target_reader="IoT founders, automotive teams, and CTOs",
                    call_to_action=(
                        "Use this as an architecture review prompt before "
                        "starting AOSP customization or BSP work."
                    ),
                )
                repurposed = self.repurposer.run(draft, review, brief)

                model_names.add(llm_result.model)
                items.append(
                    WeeklyContentItem(
                        position=reservation.position,
                        scheduled_date=spec.week_start
                        + timedelta(days=reservation.position - 1),
                        title=draft.title,
                        body=draft.body,
                        channel="blog",
                        source_mode=ContentSourceMode.AI,
                        source_reference=f"topic:{reservation.topic_id}",
                        sources=tuple(draft.sources),
                        metadata={
                            "topic_id": reservation.topic_id,
                            "pillar": topic.pillar,
                            "angle": topic.angle,
                            "format": topic.format,
                            "review_notes": review.notes,
                            "prompt_version": AI_WRITER_PROMPT.identifier,
                            "llm_request_id": llm_result.request_id,
                            "llm_model": llm_result.model,
                            "platform_drafts": [
                                {
                                    "platform": platform.platform,
                                    "title": platform.title,
                                    "body": platform.body,
                                    "status": platform.status,
                                    "notes": platform.notes,
                                }
                                for platform in repurposed.drafts
                            ],
                        },
                    )
                )
                self.recorder.complete(
                    agent_run_id,
                    llm_result,
                    output_metadata={
                        "batch_id": batch_id,
                        "topic_id": reservation.topic_id,
                        "position": reservation.position,
                        "title": draft.title,
                        "review_status": review.status,
                    },
                )
            except Exception as exc:
                self.recorder.fail(agent_run_id, exc)
                raise

        return WeeklyBatchResult(
            spec=spec,
            items=tuple(items),
            source_metadata={
                "prompt_version": AI_WRITER_PROMPT.identifier,
                "models": sorted(model_names),
            },
        )

    def _persist(
        self,
        batch_id: str,
        result: WeeklyBatchResult,
        reservations: tuple[TopicReservation, ...],
    ) -> tuple[str, ...]:
        by_position = {item.position: item for item in result.items}
        with self.session_factory() as session:
            batches = WeeklyBatchRepository(session)
            lifecycle = LifecycleRepository(session)
            batch = batches.get(batch_id)
            batches.transition(batch.id, WeeklyBatchStatus.VALIDATING)
            batch.configuration_snapshot = {
                **batch.configuration_snapshot,
                **dict(result.source_metadata),
            }
            content_ids: list[str] = []
            for reservation in reservations:
                item = by_position[reservation.position]
                content = lifecycle.create_content(
                    run_id=(
                        f"weekly-{result.spec.week_start}-v{batch.version}"
                        f"-slot-{item.position}"
                    ),
                    channel="master",
                    title=item.title,
                    body=item.body,
                    status="queued_for_approval",
                    weekly_batch_id=batch.id,
                    source_mode=ContentSourceMode.AI,
                    batch_position=item.position,
                    topic_id=reservation.topic_id,
                    metadata={
                        "scheduled_date": item.scheduled_date.isoformat(),
                        "input_channel": item.channel,
                        "sources": list(item.sources),
                        "source_reference": item.source_reference,
                        **dict(item.metadata),
                    },
                )
                content_ids.append(content.id)
                for platform in item.metadata.get("platform_drafts", []):
                    lifecycle.create_content(
                        run_id=content.run_id,
                        channel=platform["platform"],
                        title=platform["title"],
                        body=platform["body"],
                        status=platform["status"],
                        weekly_batch_id=batch.id,
                        source_mode=ContentSourceMode.AI,
                        batch_position=item.position,
                        topic_id=reservation.topic_id,
                        parent_content_id=content.id,
                        metadata={
                            "scheduled_date": item.scheduled_date.isoformat(),
                            "notes": platform["notes"],
                        },
                    )
                TopicRepository(session).mark_used(
                    topic_id=reservation.topic_id,
                    run_id=reservation.reservation_id,
                )

            batches.transition(batch.id, WeeklyBatchStatus.PENDING_APPROVAL)
            session.commit()
            return tuple(content_ids)

    def _fail_batch(
        self,
        batch_id: str,
        reservations: tuple[TopicReservation, ...],
        error: Exception,
    ) -> None:
        with self.session_factory() as session:
            topics = TopicRepository(session)
            for reservation in reservations:
                topic = session.get(TopicRecord, reservation.topic_id)
                if (
                    topic is not None
                    and topic.status == "reserved"
                    and topic.reserved_by_run_id == reservation.reservation_id
                ):
                    topics.release(
                        topic_id=reservation.topic_id,
                        run_id=reservation.reservation_id,
                    )

            batch = WeeklyBatchRepository(session).get(batch_id)
            if batch.status in {
                WeeklyBatchStatus.DRAFT.value,
                WeeklyBatchStatus.VALIDATING.value,
            }:
                WeeklyBatchRepository(session).transition(
                    batch.id,
                    WeeklyBatchStatus.FAILED,
                    reason=f"{type(error).__name__}: {error}",
                )
            session.commit()

    def _result_from_records(
        self,
        spec: WeeklyBatchSpec,
        records,
    ) -> WeeklyBatchResult:
        return WeeklyBatchResult(
            spec=spec,
            items=tuple(
                WeeklyContentItem(
                    position=record.batch_position,
                    scheduled_date=date.fromisoformat(
                        record.metadata_json["scheduled_date"]
                    ),
                    title=record.title,
                    body=record.body,
                    channel=record.metadata_json.get("input_channel", "blog"),
                    source_mode=ContentSourceMode.AI,
                    source_reference=record.metadata_json.get(
                        "source_reference",
                        f"topic:{record.topic_id}",
                    ),
                    sources=tuple(record.metadata_json.get("sources", [])),
                    metadata={
                        key: value
                        for key, value in record.metadata_json.items()
                        if key
                        not in {
                            "scheduled_date",
                            "input_channel",
                            "sources",
                            "source_reference",
                        }
                    },
                )
                for record in records
            ),
            source_metadata={
                "prompt_version": AI_WRITER_PROMPT.identifier,
                "restored": True,
            },
        )

    def _domain_topic(
        self,
        repository: TopicRepository,
        topic: TopicRecord,
    ) -> Topic:
        return Topic(
            pillar=topic.pillar,
            topic=topic.name,
            angle=topic.angle,
            format=topic.format,
            sources=repository.sources(topic.id),
        )

    def _reservation_id(self, batch_id: str, position: int) -> str:
        return str(uuid5(NAMESPACE_URL, f"weekly:{batch_id}:slot:{position}"))
