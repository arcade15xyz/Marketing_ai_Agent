from __future__ import annotations

from .models import Draft, PlatformDraft, RepurposedPackage, ResearchPacket, ReviewResult, StrategyBrief


def render_research(packet: ResearchPacket) -> str:
    lines = [
        "# Research Packet",
        "",
        f"Run date: {packet.run_date}",
        "",
    ]
    for index, topic in enumerate(packet.candidates, start=1):
        lines.extend(
            [
                f"## {index}. {topic.topic}",
                "",
                f"- Pillar: {topic.pillar}",
                f"- Format: {topic.format}",
                f"- Angle: {topic.angle}",
                "- Sources:",
            ]
        )
        lines.extend([f"  - {source}" for source in topic.sources])
        lines.append("")
    return "\n".join(lines)


def render_strategy(brief: StrategyBrief) -> str:
    topic = brief.topic
    return f"""# Strategy Brief

Run date: {brief.run_date}

## Selected Topic

{topic.topic}

## Pillar

{topic.pillar}

## Format

{topic.format}

## Angle

{topic.angle}

## Target Reader

{brief.target_reader}

## Call To Action

{brief.call_to_action}

## Sources

{chr(10).join(f"- {source}" for source in topic.sources)}
"""


def render_draft(draft: Draft) -> str:
    sources = "\n".join(f"- {source}" for source in draft.sources)
    return f"""{draft.body}

## Sources

{sources}
"""


def render_review(review: ReviewResult) -> str:
    notes = "\n".join(f"- {note}" for note in review.notes)
    sources = "\n".join(f"- {source}" for source in review.required_sources)
    return f"""# Technical Review

Status: {review.status}

## Notes

{notes}

## Required Sources

{sources}
"""


def render_platform_draft(draft: PlatformDraft) -> str:
    notes = "\n".join(f"- {note}" for note in draft.notes)
    return f"""# {draft.platform.title()} Draft

Status: {draft.status}

Title: {draft.title}

## Notes

{notes}

## Content

{draft.body}
"""


def render_approval_manifest(
    run_date: str,
    repurposed: RepurposedPackage,
    review: ReviewResult,
) -> str:
    items = "\n".join(
        [
            f"""- Platform: {draft.platform}
  Status: pending
  Draft status: {draft.status}
  Title: {draft.title}"""
            for draft in repurposed.drafts
        ]
    )
    return f"""# Approval Queue

Run date: {run_date}

Technical review status: {review.status}

Publishing status: not_enabled

## Approval Instructions

Use the local queue CLI to approve or reject a platform draft:

```powershell
python -m src.marketing_agents.approval_queue --date {run_date} --platform linkedin --decision approved
python -m src.marketing_agents.approval_queue --date {run_date} --platform blog --decision rejected
python -m src.marketing_agents.approval_queue --date {run_date} --platform reddit --decision needs_changes --note "Check r/androiddev rules first."
```

Approval only updates local state. It does not publish.

## Items

{items}
"""


def render_package(
    packet: ResearchPacket,
    brief: StrategyBrief,
    draft: Draft,
    review: ReviewResult,
    repurposed: RepurposedPackage,
) -> str:
    platform_lines = "\n".join(
        f"- {item.platform}: {item.status}" for item in repurposed.drafts
    )
    return f"""# Daily AOSP Content Package

Run date: {packet.run_date}

Review status: {review.status}

## Selected Topic

{brief.topic.topic}

## Files

- `01-research.md`
- `02-strategy.md`
- `03-master-draft.md`
- `04-technical-review.md`
- `05-blog-draft.md`
- `06-linkedin-draft.md`
- `07-reddit-draft.md`
- `approval.md`

## Platform Drafts

{platform_lines}

## Draft

{draft.body}

## Review Notes

{chr(10).join(f"- {note}" for note in review.notes)}
"""

