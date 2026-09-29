from __future__ import annotations

import unittest
from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.marketing_agents.db_models import AgentRunRecord, Base
from src.marketing_agents.llm import FakeLLMProvider
from src.marketing_agents.llm_tracking import DatabaseLLMRunRecorder


class LLMRunRecorderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.recorder = DatabaseLLMRunRecorder(self.factory)

    def tearDown(self) -> None:
        self.engine.dispose()

    async def test_records_successful_call_metadata(self) -> None:
        run_id = self.recorder.begin(
            run_date=date(2026, 9, 30),
            agent="writer",
            prompt_version="writer-v1",
            input_metadata={"topic_id": "topic-1"},
        )
        result = await FakeLLMProvider(["Draft body"]).generate(
            system_prompt="System",
            user_prompt="User",
            prompt_version="writer-v1",
        )

        self.recorder.complete(run_id, result, output_metadata={"title": "Draft"})

        with self.factory() as session:
            run = session.get(AgentRunRecord, run_id)
            self.assertEqual(run.status, "completed")
            self.assertEqual(run.model_name, "fake")
            self.assertEqual(run.inputs["prompt_version"], "writer-v1")
            self.assertEqual(run.outputs["title"], "Draft")
            self.assertEqual(run.input_tokens, 0)
            self.assertIsNotNone(run.completed_at)

    async def test_records_failure_without_secrets(self) -> None:
        run_id = self.recorder.begin(
            run_date=date(2026, 9, 30),
            agent="writer",
            prompt_version="writer-v1",
        )

        self.recorder.fail(run_id, TimeoutError("provider timed out"))

        with self.factory() as session:
            run = session.get(AgentRunRecord, run_id)
            self.assertEqual(run.status, "failed")
            self.assertIn("TimeoutError", run.error)
            self.assertNotIn("ANTHROPIC_API_KEY", run.error)


if __name__ == "__main__":
    unittest.main()
