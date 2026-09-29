from __future__ import annotations

import argparse
from datetime import datetime

from .analytics import AnalyticsAgent
from .config import OUTPUT_DIR, append_action, timezone, write_text
from .manager import ManagerAgent


def main() -> int:
    parser = argparse.ArgumentParser(description="Scheduler-friendly entry point for daily and weekly jobs.")
    parser.add_argument("--date", help="Run date in YYYY-MM-DD format. Defaults to TIMEZONE local date.")
    parser.add_argument("--weekly", action="store_true", help="Also generate this week's analytics report.")
    args = parser.parse_args()

    run_date = args.date or datetime.now(timezone()).date().isoformat()
    paths = ManagerAgent().run(run_date)
    append_action("manager", "scheduled_daily", "success", {"date": run_date, "output_dir": str(paths.output_dir)})
    print(f"Daily package: {paths.output_dir}")

    if args.weekly:
        week_start = _monday_for(run_date)
        agent = AnalyticsAgent()
        report = agent.run(week_start)
        report_path = OUTPUT_DIR / "reports" / f"weekly-{report.week_start}.md"
        write_text(report_path, agent.render(report))
        append_action("analytics", "scheduled_weekly", "success", {"week_start": report.week_start, "path": str(report_path)})
        print(f"Weekly report: {report_path}")

    return 0


def _monday_for(run_date: str) -> str:
    current = datetime.fromisoformat(run_date).date()
    return (current.fromordinal(current.toordinal() - current.weekday())).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
