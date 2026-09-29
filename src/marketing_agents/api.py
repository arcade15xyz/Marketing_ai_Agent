import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .api_schemas import (
    AgentRunRead,
    AnalyticsSummary,
    ApprovalDecision,
    ApprovalRead,
    ContentItemRead,
    HealthResponse,
    MetricCreate,
    MetricRead,
    PublishRequest,
    PublishResponse,
    TopicCreate,
    TopicRead,
    WeeklyBatchRead,
)
from .api_service import (
    ApiConflictError,
    ApiPublishFailedError,
    ApiResourceNotFoundError,
    DatabaseContentPublisher,
    LinkedInClientFactory,
    publishing_kill_switch_enabled,
)
from .db import configured_session_factory, database_url
from .db_models import (
    AgentRunRecord,
    ApprovalRecord,
    ContentItemRecord,
    MetricRecord,
    PublishJobRecord,
    TopicRecord,
    WeeklyBatchRecord,
)
from .linkedin_client import LinkedInClient
from .repositories import LifecycleRepository, TopicRepository


SessionFactory = sessionmaker[Session]


def _status_counts(session: Session, model: type, status_column) -> dict[str, int]:
    rows = session.execute(
        select(status_column, func.count()).select_from(model).group_by(status_column)
    )
    result = {str(row_status): count for row_status, count in rows}
    result["total"] = sum(result.values())
    return result


def _approval_response(
    approval: ApprovalRecord,
    content: ContentItemRecord,
) -> ApprovalRead:
    return ApprovalRead(
        id=approval.id,
        content_item_id=approval.content_item_id,
        channel=content.channel,
        title=content.title,
        status=approval.status,
        reviewer_notes=approval.reviewer_notes,
        decided_at=approval.decided_at,
        created_at=approval.created_at,
        updated_at=approval.updated_at,
    )


def create_app(
    *,
    session_factory: SessionFactory | None = None,
    linkedin_client_factory: LinkedInClientFactory = LinkedInClient,
) -> FastAPI:
    app = FastAPI(
        title="Marketing AI Agent API",
        version="0.1.0",
        description="Database-backed control plane for topics, content, approvals, publishing, and analytics.",
    )

    def get_session() -> Iterator[Session]:
        factory = session_factory or configured_session_factory()
        with factory() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    SessionDependency = Annotated[Session, Depends(get_session)]

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": "Marketing AI Agent API",
            "health": "/health",
            "docs": "/docs",
        }

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    def health() -> HealthResponse:
        return HealthResponse(
            status="ok",
            storage_backend=os.getenv("STORAGE_BACKEND", "json").strip().lower(),
            database_configured=bool(database_url()),
            content_source_mode=os.getenv("CONTENT_SOURCE_MODE", "json").strip().lower(),
            publishing_kill_switch=publishing_kill_switch_enabled(),
        )

    @app.post(
        "/topics",
        response_model=TopicRead,
        status_code=status.HTTP_201_CREATED,
        tags=["topics"],
    )
    def create_topic(payload: TopicCreate, session: SessionDependency) -> TopicRecord:
        topic = TopicRepository(session).add(**payload.model_dump())
        session.commit()
        session.refresh(topic)
        return topic

    @app.get("/topics", response_model=list[TopicRead], tags=["topics"])
    def list_topics(
        session: SessionDependency,
        topic_status: str | None = Query(default=None, alias="status"),
    ) -> list[TopicRecord]:
        return TopicRepository(session).list(status=topic_status)

    @app.get("/batches", response_model=list[WeeklyBatchRead], tags=["batches"])
    def list_batches(
        session: SessionDependency,
        week_start: date | None = None,
        batch_status: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[WeeklyBatchRecord]:
        statement = select(WeeklyBatchRecord).order_by(
            WeeklyBatchRecord.week_start.desc(),
            WeeklyBatchRecord.version.desc(),
        )
        if week_start is not None:
            statement = statement.where(WeeklyBatchRecord.week_start == week_start)
        if batch_status is not None:
            statement = statement.where(WeeklyBatchRecord.status == batch_status)
        return list(session.scalars(statement.offset(offset).limit(limit)))

    @app.get(
        "/batches/{batch_id}",
        response_model=WeeklyBatchRead,
        tags=["batches"],
    )
    def get_batch(batch_id: str, session: SessionDependency) -> WeeklyBatchRecord:
        batch = session.get(WeeklyBatchRecord, batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail="Weekly batch not found.")
        return batch

    @app.get(
        "/batches/{batch_id}/content",
        response_model=list[ContentItemRead],
        tags=["content"],
    )
    def list_batch_content(
        batch_id: str,
        session: SessionDependency,
        channel: str | None = None,
    ) -> list[ContentItemRecord]:
        if session.get(WeeklyBatchRecord, batch_id) is None:
            raise HTTPException(status_code=404, detail="Weekly batch not found.")
        statement = (
            select(ContentItemRecord)
            .where(ContentItemRecord.weekly_batch_id == batch_id)
            .order_by(ContentItemRecord.batch_position, ContentItemRecord.channel)
        )
        if channel is not None:
            statement = statement.where(ContentItemRecord.channel == channel)
        return list(session.scalars(statement))

    @app.get("/content", response_model=list[ContentItemRead], tags=["content"])
    def list_content(
        session: SessionDependency,
        channel: str | None = None,
        content_status: str | None = Query(default=None, alias="status"),
        limit: int = Query(default=100, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> list[ContentItemRecord]:
        statement = select(ContentItemRecord).order_by(
            ContentItemRecord.created_at.desc()
        )
        if channel is not None:
            statement = statement.where(ContentItemRecord.channel == channel)
        if content_status is not None:
            statement = statement.where(ContentItemRecord.status == content_status)
        return list(session.scalars(statement.offset(offset).limit(limit)))

    @app.get(
        "/content/{content_item_id}",
        response_model=ContentItemRead,
        tags=["content"],
    )
    def get_content(
        content_item_id: str,
        session: SessionDependency,
    ) -> ContentItemRecord:
        content = session.get(ContentItemRecord, content_item_id)
        if content is None:
            raise HTTPException(status_code=404, detail="Content item not found.")
        return content

    @app.get("/approvals", response_model=list[ApprovalRead], tags=["approvals"])
    def list_approvals(
        session: SessionDependency,
        approval_status: str | None = Query(default="pending", alias="status"),
    ) -> list[ApprovalRead]:
        statement = (
            select(ApprovalRecord, ContentItemRecord)
            .join(ContentItemRecord, ApprovalRecord.content_item_id == ContentItemRecord.id)
            .order_by(ApprovalRecord.created_at)
        )
        if approval_status is not None:
            statement = statement.where(ApprovalRecord.status == approval_status)
        return [
            _approval_response(approval, content)
            for approval, content in session.execute(statement)
        ]

    @app.post(
        "/content/{content_item_id}/approval",
        response_model=ApprovalRead,
        tags=["approvals"],
    )
    def decide_approval(
        content_item_id: str,
        payload: ApprovalDecision,
        session: SessionDependency,
    ) -> ApprovalRead:
        content = session.get(ContentItemRecord, content_item_id)
        if content is None:
            raise HTTPException(status_code=404, detail="Content item not found.")
        approval = LifecycleRepository(session).ensure_approval(
            content_item_id=content.id,
            status=payload.decision,
            notes=payload.note,
            decided_at=datetime.now(UTC),
            update_existing=True,
        )
        session.commit()
        session.refresh(approval)
        return _approval_response(approval, content)

    @app.post(
        "/content/{content_item_id}/publish",
        response_model=PublishResponse,
        tags=["publishing"],
    )
    def publish_content(
        content_item_id: str,
        payload: PublishRequest,
        session: SessionDependency,
    ) -> PublishResponse:
        try:
            outcome = DatabaseContentPublisher(
                session,
                client_factory=linkedin_client_factory,
            ).publish(content_item_id, execute=payload.execute)
        except ApiResourceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ApiPublishFailedError as exc:
            session.commit()
            raise HTTPException(
                status_code=502,
                detail=str(exc),
            ) from exc
        except ApiConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.commit()
        return PublishResponse(**outcome.__dict__)

    @app.get("/runs", response_model=list[AgentRunRead], tags=["runs"])
    def list_runs(
        session: SessionDependency,
        run_status: str | None = Query(default=None, alias="status"),
        agent: str | None = None,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> list[AgentRunRecord]:
        statement = select(AgentRunRecord).order_by(AgentRunRecord.created_at.desc())
        if run_status is not None:
            statement = statement.where(AgentRunRecord.status == run_status)
        if agent is not None:
            statement = statement.where(AgentRunRecord.agent == agent)
        return list(session.scalars(statement.limit(limit)))

    @app.post(
        "/metrics",
        response_model=MetricRead,
        status_code=status.HTTP_201_CREATED,
        tags=["analytics"],
    )
    def create_metric(
        payload: MetricCreate,
        session: SessionDependency,
    ) -> MetricRecord:
        if (
            payload.content_item_id is not None
            and session.get(ContentItemRecord, payload.content_item_id) is None
        ):
            raise HTTPException(status_code=404, detail="Content item not found.")
        metric = LifecycleRepository(session).add_metric(**payload.model_dump())
        try:
            session.commit()
        except IntegrityError as exc:
            raise HTTPException(
                status_code=409,
                detail="A metric already exists for this content, channel, and date.",
            ) from exc
        session.refresh(metric)
        return metric

    @app.get("/metrics", response_model=list[MetricRead], tags=["analytics"])
    def list_metrics(
        session: SessionDependency,
        channel: str | None = None,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> list[MetricRecord]:
        statement = select(MetricRecord).order_by(MetricRecord.recorded_at.desc())
        if channel is not None:
            statement = statement.where(MetricRecord.channel == channel)
        return list(session.scalars(statement.limit(limit)))

    @app.get(
        "/analytics/summary",
        response_model=AnalyticsSummary,
        tags=["analytics"],
    )
    def analytics_summary(session: SessionDependency) -> AnalyticsSummary:
        return AnalyticsSummary(
            topics=TopicRepository(session).stats(),
            content=_status_counts(
                session,
                ContentItemRecord,
                ContentItemRecord.status,
            ),
            approvals=_status_counts(
                session,
                ApprovalRecord,
                ApprovalRecord.status,
            ),
            publish_jobs=_status_counts(
                session,
                PublishJobRecord,
                PublishJobRecord.status,
            ),
            metrics_count=session.scalar(select(func.count(MetricRecord.id))) or 0,
        )

    return app


app = create_app()
