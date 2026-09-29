from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta

from .config import DATA_DIR, OUTPUT_DIR, append_action, read_json, timezone, write_text
from .models import AnalyticsReport


class AnalyticsAgent:
    """Generate weekly reports from local logs and manual metrics."""

    def run(self, week_start: str | None = None) -> AnalyticsReport:
        start = self._start_date(week_start)
        end = start + timedelta(days=6)
        rows = self._weekly_rows(start, end)

        summary = self._summary(rows)
        recommendations = self._recommendations(rows)

        return AnalyticsReport(
            week_start=start.isoformat(),
            week_end=end.isoformat(),
            summary=summary,
            recommendations=recommendations,
            rows=rows,
        )

    def render(self, report: AnalyticsReport) -> str:
        rows = "\n".join(
            [
                "| Date | Platform | Topic | Status | Impressions | Clicks | Comments | Leads | Notes |",
                "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
                *[self._render_row(row) for row in report.rows],
            ]
        )
        summary = "\n".join(f"- {item}" for item in report.summary)
        recommendations = "\n".join(f"- {item}" for item in report.recommendations)
        return f"""# Weekly Analytics Report

Week: {report.week_start} to {report.week_end}

## Summary

{summary}

## Recommendations For Strategist

{recommendations}

## Performance Table

{rows}
"""

    def _start_date(self, week_start: str | None) -> date:
        if week_start:
            return date.fromisoformat(week_start)
        today = datetime.now(timezone()).date()
        return today - timedelta(days=today.weekday())

    def _weekly_rows(self, start: date, end: date) -> list[dict]:
        content_log = read_json(DATA_DIR / "content_log.json")
        approval_queue = read_json(DATA_DIR / "approval_queue.json")
        metrics = read_json(DATA_DIR / "metrics.json")
        publish_log = read_json(DATA_DIR / "publish_log.json")

        rows: list[dict] = []
        for item in content_log:
            item_date = date.fromisoformat(item["date"])
            if not start <= item_date <= end:
                continue

            platforms = [
                approval
                for approval in approval_queue
                if approval.get("date") == item["date"]
            ]
            if not platforms:
                platforms = [{"platform": item.get("platform", "blog"), "approval_status": "", "publish_status": ""}]

            for platform_item in platforms:
                platform = platform_item.get("platform", "")
                metric_item = self._find_metric(metrics, item["date"], platform)
                publish_item = self._find_publish(publish_log, item["date"], platform)
                metric_values = metric_item.get("metrics", {}) if metric_item else {}
                rows.append(
                    {
                        "date": item["date"],
                        "platform": platform,
                        "topic": item.get("topic", ""),
                        "pillar": item.get("pillar", ""),
                        "format": item.get("format", ""),
                        "approval_status": platform_item.get("approval_status", ""),
                        "publish_status": platform_item.get("publish_status", ""),
                        "publish_attempt_status": publish_item.get("status", "") if publish_item else "",
                        "impressions": metric_values.get("impressions", 0),
                        "views": metric_values.get("views", 0),
                        "clicks": metric_values.get("clicks", 0),
                        "comments": metric_values.get("comments", 0),
                        "shares": metric_values.get("shares", 0),
                        "leads": metric_values.get("leads", 0),
                        "inbound_dms": metric_values.get("inbound_dms", 0),
                        "note": metric_item.get("note", "") if metric_item else "",
                    }
                )
        return rows

    def _summary(self, rows: list[dict]) -> list[str]:
        if not rows:
            return ["No content or metric records found for this week."]

        total_impressions = sum(row["impressions"] for row in rows)
        total_clicks = sum(row["clicks"] for row in rows)
        total_comments = sum(row["comments"] for row in rows)
        total_leads = sum(row["leads"] for row in rows)
        published = sum(1 for row in rows if row.get("publish_status") == "published")
        pending = sum(1 for row in rows if row.get("approval_status") == "pending")

        return [
            f"Content rows reviewed: {len(rows)}.",
            f"Published rows: {published}; pending approvals: {pending}.",
            f"Total impressions: {total_impressions}; clicks: {total_clicks}; comments: {total_comments}; leads: {total_leads}.",
        ]

    def _recommendations(self, rows: list[dict]) -> list[str]:
        if not rows:
            return ["Run the daily pipeline and record metrics before drawing strategy conclusions."]

        if all(row["impressions"] == 0 and row["views"] == 0 for row in rows):
            return [
                "Metrics are not recorded yet. Keep the next strategy decisions conservative.",
                "Prioritize publishing consistency before optimizing topic selection.",
                "Record LinkedIn impressions, comments, profile views, inbound DMs, and blog clicks each week.",
            ]

        best = max(rows, key=lambda row: (row["leads"], row["comments"], row["clicks"], row["impressions"]))
        return [
            f"Use the strongest observed topic as a pattern: {best['topic']} on {best['platform']}.",
            "Prefer formats that produce comments or inbound DMs over impressions alone.",
            "Feed high-comment questions back into the topic backlog as follow-up posts.",
        ]

    def _render_row(self, row: dict) -> str:
        status = row.get("publish_status") or row.get("approval_status")
        return (
            f"| {row['date']} | {row['platform']} | {row['topic']} | {status} | "
            f"{row['impressions']} | {row['clicks']} | {row['comments']} | {row['leads']} | {row['note']} |"
        )

    def _find_metric(self, metrics: list[dict], run_date: str, platform: str) -> dict | None:
        return next(
            (
                item
                for item in reversed(metrics)
                if item.get("date") == run_date and item.get("platform") == platform
            ),
            None,
        )

    def _find_publish(self, publish_log: list[dict], run_date: str, platform: str) -> dict | None:
        return next(
            (
                item
                for item in reversed(publish_log)
                if item.get("date") == run_date and item.get("platform") == platform
            ),
            None,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a weekly analytics report.")
    parser.add_argument("--week-start", help="Week start date in YYYY-MM-DD format. Defaults to current local Monday.")
    args = parser.parse_args()

    agent = AnalyticsAgent()
    report = agent.run(args.week_start)
    report_dir = OUTPUT_DIR / "reports"
    report_path = report_dir / f"weekly-{report.week_start}.md"
    write_text(report_path, agent.render(report))
    append_action(
        agent="analytics",
        action="weekly_report",
        result="success",
        details={"week_start": report.week_start, "week_end": report.week_end, "path": str(report_path)},
    )
    print(f"Wrote weekly analytics report to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

