from __future__ import annotations

from datetime import datetime

from .agents import ResearchAgent, RepurposerAgent, StrategistAgent, TechnicalReviewerAgent, WriterAgent
from .config import DATA_DIR, OUTPUT_DIR, read_json, timezone, write_json, write_text
from .models import PipelinePaths
from .rendering import (
    render_approval_manifest,
    render_draft,
    render_package,
    render_platform_draft,
    render_research,
    render_review,
    render_strategy,
)


class ManagerAgent:
    """Coordinate specialist agents without doing their lane work."""

    def __init__(self) -> None:
        self.research_agent = ResearchAgent()
        self.strategist_agent = StrategistAgent()
        self.writer_agent = WriterAgent()
        self.reviewer_agent = TechnicalReviewerAgent()
        self.repurposer_agent = RepurposerAgent()

    def run(self, run_date: str | None = None) -> PipelinePaths:
        if run_date is None:
            run_date = datetime.now(timezone()).date().isoformat()

        output_dir = OUTPUT_DIR / run_date
        paths = PipelinePaths(
            root=OUTPUT_DIR,
            output_dir=output_dir,
            research=output_dir / "01-research.md",
            strategy=output_dir / "02-strategy.md",
            draft=output_dir / "03-master-draft.md",
            review=output_dir / "04-technical-review.md",
            blog=output_dir / "05-blog-draft.md",
            linkedin=output_dir / "06-linkedin-draft.md",
            reddit=output_dir / "07-reddit-draft.md",
            approval=output_dir / "approval.md",
            package=output_dir / "PACKAGE.md",
        )

        packet = self.research_agent.run(run_date)
        write_text(paths.research, render_research(packet))

        brief = self.strategist_agent.run(packet)
        write_text(paths.strategy, render_strategy(brief))

        draft = self.writer_agent.run(brief)
        write_text(paths.draft, render_draft(draft))

        review = self.reviewer_agent.run(draft)
        write_text(paths.review, render_review(review))

        repurposed = self.repurposer_agent.run(draft, review, brief)
        for platform_draft in repurposed.drafts:
            if platform_draft.platform == "blog":
                write_text(paths.blog, render_platform_draft(platform_draft))
            if platform_draft.platform == "linkedin":
                write_text(paths.linkedin, render_platform_draft(platform_draft))
            if platform_draft.platform == "reddit":
                write_text(paths.reddit, render_platform_draft(platform_draft))

        write_text(paths.approval, render_approval_manifest(run_date, repurposed, review))
        self._record_approval_state(run_date, repurposed)

        write_text(paths.package, render_package(packet, brief, draft, review, repurposed))
        self._record_content_log(run_date, brief, review.status)

        return paths

    def _record_content_log(self, run_date: str, brief, review_status: str) -> None:
        log_path = DATA_DIR / "content_log.json"
        content_log = read_json(log_path)
        entry = {
            "date": run_date,
            "topic": brief.topic.topic,
            "pillar": brief.topic.pillar,
            "format": brief.topic.format,
            "platform": "blog",
            "url": "",
            "metrics": {},
            "status": f"draft:{review_status}",
        }

        content_log = [existing for existing in content_log if existing.get("date") != run_date]
        content_log.append(entry)
        write_json(log_path, content_log)

    def _record_approval_state(self, run_date: str, repurposed) -> None:
        queue_path = DATA_DIR / "approval_queue.json"
        if queue_path.exists():
            queue = read_json(queue_path)
        else:
            queue = []

        queue = [item for item in queue if item.get("date") != run_date]
        for draft in repurposed.drafts:
            queue.append(
                {
                    "date": run_date,
                    "platform": draft.platform,
                    "title": draft.title,
                    "draft_status": draft.status,
                    "approval_status": "pending",
                    "publishing_enabled": False,
                    "publish_status": "not_published",
                    "published_url": "",
                    "decision_note": "",
                }
            )
        write_json(queue_path, queue)

