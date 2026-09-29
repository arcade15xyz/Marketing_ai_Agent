from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, UTC

from sqlalchemy.orm import Session, sessionmaker

from .agents import TopicBacklogExhaustedError
from .db_models import AgentRunRecord, TopicRecord
from .models import Draft, RepurposedPackage, ReviewResult, Topic
from .repositories import LifecycleRepository, TopicRepository


@dataclass(frozen=True)
class DatabaseRunContext:
    run_id: str
    agent_run_id: str
    topic_id: str
    topic: Topic


class DatabasePipelineState:
    """Persist daily pipeline state without coupling agents to SQLAlchemy."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def reserve(self, run_date: str) -> DatabaseRunContext:
        run_id = f"daily-{run_date}"
        with self.session_factory() as session:
            topics = TopicRepository(session)
            topic = topics.reserve_next(
                run_id=run_id,
                last_pillar=topics.last_used_pillar(),
            )
            if topic is None:
                session.commit()
                raise TopicBacklogExhaustedError(
                    "No eligible unused topics remain in the database backlog."
                )
            agent_run = LifecycleRepository(session).add_agent_run(
                run_date=date.fromisoformat(run_date),
                agent="manager",
                status="running",
                inputs={"topic_id": topic.id},
            )
            context = DatabaseRunContext(
                run_id=run_id,
                agent_run_id=agent_run.id,
                topic_id=topic.id,
                topic=self._domain_topic(session, topic),
            )
            session.commit()
            return context

    def complete(
        self,
        context: DatabaseRunContext,
        draft: Draft,
        review: ReviewResult,
        repurposed: RepurposedPackage,
    ) -> None:
        with self.session_factory() as session:
            lifecycle = LifecycleRepository(session)
            master = lifecycle.create_content(
                run_id=context.run_id,
                channel="master",
                title=draft.title,
                body=draft.body,
                status=f"draft:{review.status}",
                topic_id=context.topic_id,
                metadata={"sources": draft.sources, "review_notes": review.notes},
            )
            for platform_draft in repurposed.drafts:
                content = lifecycle.create_content(
                    run_id=context.run_id,
                    channel=platform_draft.platform,
                    title=platform_draft.title,
                    body=platform_draft.body,
                    status=platform_draft.status,
                    topic_id=context.topic_id,
                    parent_content_id=master.id,
                    metadata={"notes": platform_draft.notes},
                )
                lifecycle.ensure_approval(content_item_id=content.id)

            TopicRepository(session).mark_used(
                topic_id=context.topic_id,
                run_id=context.run_id,
            )
            agent_run = session.get(AgentRunRecord, context.agent_run_id)
            if agent_run is not None:
                agent_run.status = "completed"
                agent_run.outputs = {
                    "content_id": master.id,
                    "review_status": review.status,
                }
                agent_run.completed_at = datetime.now(UTC)
            session.commit()

    def fail(self, context: DatabaseRunContext, error: Exception) -> None:
        with self.session_factory() as session:
            topic = session.get(TopicRecord, context.topic_id)
            if topic is not None and topic.status == "reserved":
                TopicRepository(session).release(
                    topic_id=context.topic_id,
                    run_id=context.run_id,
                )
            agent_run = session.get(AgentRunRecord, context.agent_run_id)
            if agent_run is not None:
                agent_run.status = "failed"
                agent_run.error = str(error)
                agent_run.completed_at = datetime.now(UTC)
            session.commit()

    def _domain_topic(self, session: Session, topic: TopicRecord) -> Topic:
        return Topic(
            pillar=topic.pillar,
            topic=topic.name,
            angle=topic.angle,
            format=topic.format,
            sources=TopicRepository(session).sources(topic.id),
        )
