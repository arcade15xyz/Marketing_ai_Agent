from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Sequence

from .analytics import AnalyticsAgent
from .config import OUTPUT_DIR, append_action, timezone, write_text
from .db import configured_session_factory, storage_backend
from .linkedin_client import LinkedInClient
from .manager import ManagerAgent
from .scheduling import (
    DuePublishService,
    SchedulerConfigurationError,
    WeeklyPreparationService,
)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)

    # Preserve the previous scheduler invocation while operators migrate to
    # explicit weekly commands.
    if not arguments or (
        arguments[0].startswith("-")
        and arguments[0] not in {"-h", "--help"}
    ):
        return _legacy_daily(arguments)

    parser = _command_parser()
    args = parser.parse_args(arguments)
    try:
        if args.command == "prepare-week":
            _require_database()
            week_start = _week_start(args.week_start)
            outcome = asyncio.run(
                WeeklyPreparationService(configured_session_factory()).prepare(
                    week_start,
                    input_path=args.input,
                    count=args.count,
                    dry_run=args.dry_run,
                )
            )
            print(json.dumps(asdict(outcome), default=str, sort_keys=True))
            return 0

        if args.command == "publish-due":
            _require_database()
            outcome = DuePublishService(
                configured_session_factory(),
                client_factory=LinkedInClient,
            ).publish_due(
                now=_instant(args.at),
                execute=args.execute,
                limit=args.limit,
                max_attempts=args.max_attempts,
            )
            print(json.dumps(asdict(outcome), default=str, sort_keys=True))
            return 1 if outcome.failed_count else 0

        if args.command == "weekly-report":
            week_start = _week_start(args.week_start).isoformat()
            report_path = _weekly_report(week_start)
            print(f"Weekly report: {report_path}")
            return 0

        if args.command == "legacy-daily":
            legacy_arguments: list[str] = []
            if args.date:
                legacy_arguments.extend(["--date", args.date])
            if args.weekly:
                legacy_arguments.append("--weekly")
            return _legacy_daily(legacy_arguments)
    except Exception as exc:
        print(f"Scheduler failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    parser.error("A scheduler command is required.")
    return 2


def _command_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare weekly content and publish already-scheduled due jobs."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser(
        "prepare-week",
        help="Prepare the complete week using CONTENT_SOURCE_MODE.",
    )
    prepare.add_argument(
        "--week-start",
        help="Monday in YYYY-MM-DD format. Defaults to the current week's Monday.",
    )
    prepare.add_argument(
        "--input",
        type=Path,
        help="Versioned weekly JSON file; required in JSON mode.",
    )
    prepare.add_argument(
        "--count",
        type=int,
        help="Override WEEKLY_POST_COUNT for this preparation run.",
    )
    prepare.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate without importing content or calling the AI provider.",
    )

    publish = subparsers.add_parser(
        "publish-due",
        help="Process due approved publish jobs without generating content.",
    )
    publish.add_argument(
        "--at",
        help="ISO-8601 cutoff time. Defaults to now.",
    )
    publish.add_argument(
        "--execute",
        action="store_true",
        help="Call the official LinkedIn API; otherwise perform dry-runs.",
    )
    publish.add_argument("--limit", type=int, default=100)
    publish.add_argument("--max-attempts", type=int, default=3)

    weekly = subparsers.add_parser(
        "weekly-report",
        help="Generate the existing weekly analytics report.",
    )
    weekly.add_argument(
        "--week-start",
        help="Monday in YYYY-MM-DD format. Defaults to the current week's Monday.",
    )

    legacy = subparsers.add_parser(
        "legacy-daily",
        help="Run the previous daily generation workflow during migration.",
    )
    legacy.add_argument("--date")
    legacy.add_argument("--weekly", action="store_true")
    return parser


def _require_database() -> None:
    if storage_backend() != "database":
        raise SchedulerConfigurationError(
            "Weekly scheduler commands require STORAGE_BACKEND=database."
        )


def _week_start(value: str | None) -> date:
    current = date.fromisoformat(value) if value else datetime.now(timezone()).date()
    monday = current.fromordinal(current.toordinal() - current.weekday())
    if value is not None and current != monday:
        raise SchedulerConfigurationError("--week-start must be a Monday.")
    return monday


def _instant(value: str | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone())
    return instant.astimezone(UTC)


def _legacy_daily(arguments: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Compatibility entry point for the previous daily pipeline."
    )
    parser.add_argument(
        "--date",
        help="Run date in YYYY-MM-DD format. Defaults to TIMEZONE local date.",
    )
    parser.add_argument(
        "--weekly",
        action="store_true",
        help="Also generate this week's analytics report.",
    )
    args = parser.parse_args(list(arguments))

    run_date = args.date or datetime.now(timezone()).date().isoformat()
    paths = ManagerAgent().run(run_date)
    append_action(
        "manager",
        "scheduled_daily",
        "success",
        {"date": run_date, "output_dir": str(paths.output_dir)},
    )
    print(f"Daily package: {paths.output_dir}")

    if args.weekly:
        report_path = _weekly_report(_monday_for(run_date))
        print(f"Weekly report: {report_path}")
    return 0


def _weekly_report(week_start: str) -> Path:
    agent = AnalyticsAgent()
    report = agent.run(week_start)
    report_path = OUTPUT_DIR / "reports" / f"weekly-{report.week_start}.md"
    write_text(report_path, agent.render(report))
    append_action(
        "analytics",
        "scheduled_weekly",
        "success",
        {"week_start": report.week_start, "path": str(report_path)},
    )
    return report_path


def _monday_for(run_date: str) -> str:
    current = datetime.fromisoformat(run_date).date()
    return current.fromordinal(current.toordinal() - current.weekday()).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
