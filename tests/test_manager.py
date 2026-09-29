from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.marketing_agents.manager import ManagerAgent


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class ManagerAgentTests(unittest.TestCase):
    def test_run_creates_complete_draft_package_and_pending_approvals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            data_dir = root / "data"
            output_dir = root / "outputs"
            data_dir.mkdir()
            write_json(
                data_dir / "topic_backlog.json",
                [
                    {
                        "pillar": "Architecture deep dives",
                        "topic": "System and vendor boundaries",
                        "angle": "Treat boundaries as architecture.",
                        "format": "deep dive",
                        "sources": ["https://source.android.com/docs/core/architecture"],
                    }
                ],
            )
            write_json(data_dir / "content_log.json", [])
            write_json(data_dir / "approval_queue.json", [])
            write_json(
                data_dir / "approved_sources.json",
                {
                    "technical_authorities": ["source.android.com"],
                    "community_public_sources": [],
                },
            )

            with (
                patch("src.marketing_agents.manager.DATA_DIR", data_dir),
                patch("src.marketing_agents.manager.OUTPUT_DIR", output_dir),
                patch("src.marketing_agents.agents.DATA_DIR", data_dir),
            ):
                paths = ManagerAgent().run("2026-09-29")

            expected_files = [
                paths.research,
                paths.strategy,
                paths.draft,
                paths.review,
                paths.blog,
                paths.linkedin,
                paths.reddit,
                paths.approval,
                paths.package,
            ]
            self.assertTrue(all(path.exists() for path in expected_files))

            queue = json.loads((data_dir / "approval_queue.json").read_text(encoding="utf-8"))
            self.assertEqual({item["platform"] for item in queue}, {"blog", "linkedin", "reddit"})
            self.assertTrue(all(item["approval_status"] == "pending" for item in queue))


if __name__ == "__main__":
    unittest.main()
