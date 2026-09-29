from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.marketing_agents.publisher import Publisher


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


class PublisherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.output_dir = self.root / "outputs"
        self.data_dir.mkdir()
        self.output_dir.mkdir()
        self.action_log = self.data_dir / "action_log.json"
        write_json(self.action_log, [])
        write_json(self.data_dir / "publish_log.json", [])

        self.patchers = [
            patch("src.marketing_agents.publisher.DATA_DIR", self.data_dir),
            patch("src.marketing_agents.publisher.OUTPUT_DIR", self.output_dir),
            patch("src.marketing_agents.config.ACTION_LOG_PATH", self.action_log),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def write_approval(self, **overrides: object) -> None:
        item = {
            "date": "2026-09-29",
            "platform": "linkedin",
            "draft_status": "queued_for_approval",
            "approval_status": "approved",
            "publish_status": "not_published",
        }
        item.update(overrides)
        write_json(self.data_dir / "approval_queue.json", [item])

    def write_draft(self) -> None:
        draft_dir = self.output_dir / "2026-09-29"
        draft_dir.mkdir(parents=True)
        (draft_dir / "06-linkedin-draft.md").write_text(
            "# LinkedIn\n\n## Content\n\nSafe draft text.", encoding="utf-8"
        )

    def test_kill_switch_blocks_before_publishing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            result = Publisher().publish("2026-09-29", "linkedin", execute=True)

        self.assertIn("PUBLISHING_KILL_SWITCH", result)

    def test_unapproved_content_is_blocked(self) -> None:
        self.write_approval(approval_status="pending")

        with patch.dict(os.environ, {"PUBLISHING_KILL_SWITCH": "false"}, clear=True):
            result = Publisher().publish("2026-09-29", "linkedin", execute=True)

        self.assertIn("approval status is pending", result)

    def test_dry_run_never_calls_linkedin(self) -> None:
        self.write_approval()
        self.write_draft()

        with (
            patch.dict(os.environ, {"PUBLISHING_KILL_SWITCH": "false"}, clear=True),
            patch("src.marketing_agents.publisher.LinkedInClient") as client,
        ):
            result = Publisher().publish("2026-09-29", "linkedin", execute=False)

        self.assertIn("Dry-run passed", result)
        client.assert_not_called()

    def test_already_published_item_is_not_published_again(self) -> None:
        self.write_approval(publish_status="published", published_url="urn:li:share:123")
        self.write_draft()
        client = Mock()

        with (
            patch.dict(os.environ, {"PUBLISHING_KILL_SWITCH": "false"}, clear=True),
            patch("src.marketing_agents.publisher.LinkedInClient", return_value=client),
        ):
            result = Publisher().publish("2026-09-29", "linkedin", execute=True)

        self.assertIn("already published", result)
        client.create_text_share.assert_not_called()

    def test_reddit_remains_draft_only(self) -> None:
        with patch.dict(os.environ, {"PUBLISHING_KILL_SWITCH": "false"}, clear=True):
            result = Publisher().publish("2026-09-29", "reddit", execute=True)

        self.assertIn("draft-and-approve only", result)


if __name__ == "__main__":
    unittest.main()
