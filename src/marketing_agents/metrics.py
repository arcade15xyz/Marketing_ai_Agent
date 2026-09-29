from __future__ import annotations

import argparse
from datetime import datetime

from .config import DATA_DIR, append_action, read_json, timezone, write_json


METRIC_FIELDS = [
    "impressions",
    "views",
    "clicks",
    "reactions",
    "comments",
    "shares",
    "profile_views",
    "inbound_dms",
    "newsletter_signups",
    "leads",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Record manual performance metrics for a content item.")
    parser.add_argument("--date", required=True, help="Content date in YYYY-MM-DD format.")
    parser.add_argument("--platform", required=True, help="Platform, for example blog, linkedin, or reddit.")
    parser.add_argument("--url", default="", help="Published URL or platform URN.")
    parser.add_argument("--note", default="", help="Optional qualitative note.")
    for field in METRIC_FIELDS:
        parser.add_argument(f"--{field.replace('_', '-')}", type=int, default=0)

    args = parser.parse_args()

    metrics_path = DATA_DIR / "metrics.json"
    metrics = read_json(metrics_path)
    entry = {
        "date": args.date,
        "platform": args.platform,
        "url": args.url,
        "note": args.note,
        "recorded_at": datetime.now(timezone()).isoformat(timespec="seconds"),
        "metrics": {field: getattr(args, field) for field in METRIC_FIELDS},
    }

    metrics = [
        item
        for item in metrics
        if not (item.get("date") == args.date and item.get("platform") == args.platform)
    ]
    metrics.append(entry)
    write_json(metrics_path, metrics)
    append_action(
        agent="analytics",
        action="record_metrics",
        result="success",
        details={"date": args.date, "platform": args.platform, "metrics": entry["metrics"]},
    )
    print(f"Recorded metrics for {args.date} / {args.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

