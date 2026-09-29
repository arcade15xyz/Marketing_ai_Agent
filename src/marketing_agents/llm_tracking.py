from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from .db_models import AgentRunRecord
from .llm import LLMResult
from .repositories import LifecycleRepository


class DatabaseLLMRunRecorder:
    """Store LLM call metadata without persisting secrets or full prompts."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def begin(
        self,
        *,
        run_date: date,
        agent: str,
        prompt_version: str,
        input_metadata: Mapping[str, Any] | None = None,
    ) -> str:
        inputs = dict(input_metadata or {})
        inputs["prompt_version"] = prompt_version
        with self.session_factory() as session:
            run = LifecycleRepository(session).add_agent_run(
                run_date=run_date,
                agent=agent,
                status="running",
                inputs=inputs,
            )
            run_id = run.id
            session.commit()
            return run_id

    def complete(
        self,
        agent_run_id: str,
        result: LLMResult,
        *,
        output_metadata: Mapping[str, Any] | None = None,
    ) -> None:
        with self.session_factory() as session:
            run = self._required_run(session, agent_run_id)
            run.status = "completed"
            run.outputs = dict(output_metadata or {})
            run.model_name = result.model
            run.latency_ms = result.latency_ms
            run.input_tokens = result.usage.input_tokens
            run.output_tokens = result.usage.output_tokens
            run.cost_usd = (
                Decimal(str(result.usage.cost_usd))
                if result.usage.cost_usd is not None
                else None
            )
            run.completed_at = result.completed_at
            session.commit()

    def fail(self, agent_run_id: str, error: Exception) -> None:
        with self.session_factory() as session:
            run = self._required_run(session, agent_run_id)
            run.status = "failed"
            run.error = f"{type(error).__name__}: {error}"
            run.completed_at = datetime.now(UTC)
            session.commit()

    def _required_run(self, session: Session, agent_run_id: str) -> AgentRunRecord:
        run = session.get(AgentRunRecord, agent_run_id)
        if run is None:
            raise LookupError(f"Agent run not found: {agent_run_id}")
        return run
