from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.marketing_agents.agents import (
    StrategistAgent,
    ResearchAgent,
    TechnicalReviewerAgent,
    TopicBacklogExhaustedError,
)
from src.marketing_agents.models import Draft, ResearchPacket, Topic


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class StrategistAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.topic = Topic(
            pillar="Architecture",
            topic="System and vendor boundaries",
            angle="Treat boundaries as architecture.",
            format="deep dive",
            sources=["https://source.android.com/docs/core/architecture"],
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_reuses_same_topic_when_rerunning_same_date(self) -> None:
        write_json(
            self.data_dir / "content_log.json",
            [{"date": "2026-09-29", "topic": self.topic.topic, "pillar": self.topic.pillar}],
        )
        packet = ResearchPacket(run_date="2026-09-29", candidates=[self.topic])

        with patch("src.marketing_agents.agents.DATA_DIR", self.data_dir):
            brief = StrategistAgent().run(packet)

        self.assertEqual(brief.topic, self.topic)

    def test_stops_when_all_topics_are_exhausted(self) -> None:
        write_json(
            self.data_dir / "content_log.json",
            [{"date": "2026-09-28", "topic": self.topic.topic, "pillar": self.topic.pillar}],
        )
        packet = ResearchPacket(run_date="2026-09-29", candidates=[self.topic])

        with patch("src.marketing_agents.agents.DATA_DIR", self.data_dir):
            with self.assertRaisesRegex(TopicBacklogExhaustedError, "No eligible unused topics"):
                StrategistAgent().run(packet)

    def test_uses_unused_topic_when_only_same_pillar_remains(self) -> None:
        remaining_topic = Topic(
            pillar=self.topic.pillar,
            topic="AIDL HAL contracts",
            angle="Treat interfaces as contracts.",
            format="deep dive",
            sources=["https://source.android.com/docs/core/architecture/aidl/aidl-hals"],
        )
        write_json(
            self.data_dir / "content_log.json",
            [{"date": "2026-09-28", "topic": self.topic.topic, "pillar": self.topic.pillar}],
        )
        packet = ResearchPacket(run_date="2026-09-29", candidates=[self.topic, remaining_topic])

        with patch("src.marketing_agents.agents.DATA_DIR", self.data_dir):
            brief = StrategistAgent().run(packet)

        self.assertEqual(brief.topic, remaining_topic)

    def test_research_exposes_the_complete_backlog(self) -> None:
        topics = [
            {
                "pillar": "Architecture",
                "topic": f"Topic {index}",
                "angle": "An angle.",
                "format": "deep dive",
                "sources": ["https://source.android.com/docs/core/architecture"],
            }
            for index in range(10)
        ]
        write_json(self.data_dir / "topic_backlog.json", topics)

        with patch("src.marketing_agents.agents.DATA_DIR", self.data_dir):
            packet = ResearchAgent().run("2026-09-29")

        self.assertEqual(len(packet.candidates), 10)


class TechnicalReviewerAgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        write_json(
            self.data_dir / "approved_sources.json",
            {
                "technical_authorities": ["source.android.com"],
                "community_public_sources": [],
            },
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_blocks_unverified_content(self) -> None:
        draft = Draft(
            title="Draft",
            body="A claim that is [UNVERIFIED].",
            sources=["https://source.android.com/docs/core/architecture"],
        )

        with patch("src.marketing_agents.agents.DATA_DIR", self.data_dir):
            result = TechnicalReviewerAgent().run(draft)

        self.assertEqual(result.status, "blocked")

    def test_blocks_unapproved_source_domain(self) -> None:
        draft = Draft(
            title="Draft",
            body="A claim.",
            sources=["https://example.com/aosp"],
        )

        with patch("src.marketing_agents.agents.DATA_DIR", self.data_dir):
            result = TechnicalReviewerAgent().run(draft)

        self.assertEqual(result.status, "blocked")
        self.assertTrue(any("not approved" in note for note in result.notes))


if __name__ == "__main__":
    unittest.main()
