from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, OUTPUT_DIR, append_action, read_json, timezone, write_json
from .linkedin_client import LinkedInClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish approved content through official APIs only.")
    parser.add_argument("--date", required=True, help="Content date in YYYY-MM-DD format.")
    parser.add_argument("--platform", required=True, choices=["linkedin", "reddit"])
    parser.add_argument("--execute", action="store_true", help="Actually publish. Without this, runs a dry-run.")
    args = parser.parse_args()

    publisher = Publisher()
    result = publisher.publish(date=args.date, platform=args.platform, execute=args.execute)
    print(result)
    return 0


class Publisher:
    def publish(self, date: str, platform: str, execute: bool) -> str:
        if self._kill_switch_enabled():
            append_action("publisher", "publish", "blocked", {"date": date, "platform": platform, "reason": "kill_switch"})
            return "Publishing blocked: PUBLISHING_KILL_SWITCH is enabled."

        if platform == "reddit":
            append_action("publisher", "publish", "blocked", {"date": date, "platform": platform, "reason": "reddit_draft_only"})
            return "Publishing blocked: Reddit is draft-and-approve only in Phase 5."

        approval = self._approval_item(date, platform)
        if approval is None:
            append_action("publisher", "publish", "blocked", {"date": date, "platform": platform, "reason": "missing_approval"})
            return f"Publishing blocked: no approval item for {date} / {platform}."
        if approval.get("approval_status") != "approved":
            append_action("publisher", "publish", "blocked", {"date": date, "platform": platform, "reason": "not_approved"})
            return f"Publishing blocked: approval status is {approval.get('approval_status')}."
        if approval.get("draft_status") != "queued_for_approval":
            append_action("publisher", "publish", "blocked", {"date": date, "platform": platform, "reason": "draft_status"})
            return f"Publishing blocked: draft status is {approval.get('draft_status')}."

        if approval.get("publish_status") == "published":
            append_action(
                "publisher",
                "publish",
                "blocked",
                {"date": date, "platform": platform, "reason": "already_published"},
            )
            return f"Publishing blocked: {date} / {platform} is already published."

        draft_path = self._draft_path(date, platform)
        if not draft_path.exists():
            append_action("publisher", "publish", "blocked", {"date": date, "platform": platform, "reason": "missing_draft"})
            return f"Publishing blocked: draft file not found at {draft_path}."

        text = self._extract_content(draft_path.read_text(encoding="utf-8"))
        if not text.strip():
            append_action("publisher", "publish", "blocked", {"date": date, "platform": platform, "reason": "empty_draft"})
            return "Publishing blocked: draft content is empty."

        if not execute:
            self._log_publish_attempt(date, platform, "dry_run", "", "Dry-run only. Nothing was published.")
            append_action("publisher", "publish", "dry_run", {"date": date, "platform": platform})
            return f"Dry-run passed for {date} / {platform}. Add --execute to publish through the official API."

        if platform == "linkedin":
            result = LinkedInClient().create_text_share(text)
            if result.ok:
                self._mark_published(date, platform, result.post_urn)
                self._log_publish_attempt(date, platform, "published", result.post_urn, result.response_body)
                append_action("publisher", "publish", "published", {"date": date, "platform": platform, "post_urn": result.post_urn})
                return f"Published to LinkedIn: {result.post_urn}"

            self._log_publish_attempt(date, platform, "failed", "", result.error or result.response_body)
            append_action("publisher", "publish", "failed", {"date": date, "platform": platform, "error": result.error or result.response_body})
            return f"LinkedIn publish failed: {result.error or result.response_body}"

        return f"Unsupported platform: {platform}"

    def _kill_switch_enabled(self) -> bool:
        value = os.getenv("PUBLISHING_KILL_SWITCH", "true").strip().lower()
        return value not in {"false", "0", "off", "no"}

    def _approval_item(self, date: str, platform: str) -> dict | None:
        queue = read_json(DATA_DIR / "approval_queue.json")
        for item in queue:
            if item.get("date") == date and item.get("platform") == platform:
                return item
        return None

    def _draft_path(self, date: str, platform: str) -> Path:
        if platform == "linkedin":
            return OUTPUT_DIR / date / "06-linkedin-draft.md"
        if platform == "reddit":
            return OUTPUT_DIR / date / "07-reddit-draft.md"
        raise ValueError(f"Unsupported platform: {platform}")

    def _extract_content(self, markdown: str) -> str:
        marker = "## Content"
        if marker not in markdown:
            return markdown.strip()
        return markdown.split(marker, 1)[1].strip()

    def _mark_published(self, date: str, platform: str, post_urn: str) -> None:
        queue_path = DATA_DIR / "approval_queue.json"
        queue = read_json(queue_path)
        for item in queue:
            if item.get("date") == date and item.get("platform") == platform:
                item["published_url"] = post_urn
                item["publish_status"] = "published"
                item["published_at"] = datetime.now(timezone()).isoformat(timespec="seconds")
                break
        write_json(queue_path, queue)

    def _log_publish_attempt(self, date: str, platform: str, status: str, post_urn: str, message: str) -> None:
        log_path = DATA_DIR / "publish_log.json"
        log = read_json(log_path)
        log.append(
            {
                "date": date,
                "platform": platform,
                "status": status,
                "post_urn": post_urn,
                "message": message,
                "timestamp": datetime.now(timezone()).isoformat(timespec="seconds"),
            }
        )
        write_json(log_path, log)


if __name__ == "__main__":
    raise SystemExit(main())

