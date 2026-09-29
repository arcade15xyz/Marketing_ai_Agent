from __future__ import annotations

import argparse
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select

from .config import DATA_DIR, OUTPUT_DIR, read_json
from .db import configured_session_factory
from .db_models import MetricRecord, PublishEventRecord, TopicRecord
from .repositories import LifecycleRepository, TopicRepository


PLATFORM_FILES = {
    "blog": "05-blog-draft.md",
    "linkedin": "06-linkedin-draft.md",
    "reddit": "07-reddit-draft.md",
}


def parse_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def read_optional_json(path: Path) -> list[dict]:
    if not path.exists():
        return []
    value = read_json(path)
    if not isinstance(value, list):
        raise ValueError(f"Expected a JSON list in {path}")
    return value


def read_draft(outputs_dir: Path, run_date: str, platform: str) -> str:
    filename = PLATFORM_FILES.get(platform)
    if filename is None:
        return ""
    path = outputs_dir / run_date / filename
    return path.read_text(encoding="utf-8") if path.exists() else ""


def import_json_state(session, *, data_dir: Path, outputs_dir: Path) -> dict[str, int]:
    topics = TopicRepository(session)
    lifecycle = LifecycleRepository(session)
    counts = {
        "topics_seen": 0,
        "content_items_seen": 0,
        "approvals_seen": 0,
        "publish_events_created": 0,
        "metrics_created": 0,
    }

    topic_by_name: dict[str, TopicRecord] = {}
    for item in read_optional_json(data_dir / "topic_backlog.json"):
        topic = topics.add(
            pillar=item["pillar"],
            name=item["topic"],
            angle=item["angle"],
            format=item["format"],
            sources=item.get("sources", []),
            source="json_import",
        )
        topic_by_name[topic.name] = topic
        counts["topics_seen"] += 1

    master_by_date: dict[str, object] = {}
    for item in read_optional_json(data_dir / "content_log.json"):
        run_date = item["date"]
        run_id = f"legacy-{run_date}"
        topic = topic_by_name.get(item.get("topic", ""))
        master_path = outputs_dir / run_date / "03-master-draft.md"
        content = lifecycle.create_content(
            run_id=run_id,
            channel="master",
            title=item.get("topic", "Imported content"),
            body=master_path.read_text(encoding="utf-8") if master_path.exists() else "",
            status=item.get("status", "draft:unknown"),
            topic_id=topic.id if topic else None,
            metadata={"legacy_date": run_date, "legacy_format": item.get("format", "")},
        )
        master_by_date[run_date] = content
        counts["content_items_seen"] += 1
        if topic is not None:
            topic.status = "used"
            topic.used_at = parse_datetime(f"{run_date}T00:00:00+00:00")

    platform_by_key: dict[tuple[str, str], object] = {}
    for item in read_optional_json(data_dir / "approval_queue.json"):
        run_date = item["date"]
        platform = item["platform"]
        master = master_by_date.get(run_date)
        content = lifecycle.create_content(
            run_id=f"legacy-{run_date}",
            channel=platform,
            title=item.get("title", "Imported content"),
            body=read_draft(outputs_dir, run_date, platform),
            status=item.get("draft_status", "queued_for_approval"),
            topic_id=master.topic_id if master else None,
            parent_content_id=master.id if master else None,
            metadata={"legacy_date": run_date},
        )
        platform_by_key[(run_date, platform)] = content
        lifecycle.ensure_approval(
            content_item_id=content.id,
            status=item.get("approval_status", "pending"),
            notes=item.get("decision_note", ""),
            decided_at=parse_datetime(item.get("decided_at")),
            update_existing=True,
        )
        counts["content_items_seen"] += 1
        counts["approvals_seen"] += 1

    for index, item in enumerate(read_optional_json(data_dir / "publish_log.json")):
        key = (item["date"], item["platform"])
        content = platform_by_key.get(key)
        if content is None:
            continue
        idempotency_key = f"legacy:{item['date']}:{item['platform']}"
        job = lifecycle.ensure_publish_job(
            content_item_id=content.id,
            channel=item["platform"],
            idempotency_key=idempotency_key,
            status=item.get("status", "unknown"),
        )
        exists = session.scalar(
            select(PublishEventRecord).where(
                PublishEventRecord.publish_job_id == job.id,
                PublishEventRecord.status == item.get("status", "unknown"),
                PublishEventRecord.message == item.get("message", ""),
            )
        )
        if exists is None:
            lifecycle.add_publish_event(
                publish_job_id=job.id,
                status=item.get("status", "unknown"),
                external_post_id=item.get("post_urn", ""),
                message=item.get("message", ""),
                response_metadata={"legacy_index": index, "timestamp": item.get("timestamp")},
            )
            counts["publish_events_created"] += 1

    for item in read_optional_json(data_dir / "metrics.json"):
        observed = date.fromisoformat(item["date"])
        content = platform_by_key.get((item["date"], item["platform"]))
        existing = session.scalar(
            select(MetricRecord).where(
                MetricRecord.observation_date == observed,
                MetricRecord.channel == item["platform"],
                MetricRecord.content_item_id == (content.id if content else None),
            )
        )
        if existing is None:
            lifecycle.add_metric(
                observation_date=observed,
                channel=item["platform"],
                values=item.get("metrics", {}),
                content_item_id=content.id if content else None,
                note=item.get("note", ""),
            )
            counts["metrics_created"] += 1

    session.flush()
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Import legacy JSON state into the configured database.")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--outputs-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with configured_session_factory()() as session:
        counts = import_json_state(
            session,
            data_dir=args.data_dir,
            outputs_dir=args.outputs_dir,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    mode = "Validated" if args.dry_run else "Imported"
    print(f"{mode} JSON state: {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
