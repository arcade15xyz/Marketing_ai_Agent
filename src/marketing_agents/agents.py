from __future__ import annotations

from urllib.parse import urlparse

from .config import DATA_DIR, read_json
from .models import Draft, PlatformDraft, RepurposedPackage, ResearchPacket, ReviewResult, StrategyBrief, Topic


COMPANY_WEBSITE = "https://ftechizsolutions.com/"


class TopicBacklogExhaustedError(RuntimeError):
    """Raised when no unused topic is available for a new content run."""


class ResearchAgent:
    """Find candidate topics from the approved local backlog."""

    def run(self, run_date: str) -> ResearchPacket:
        topics = [Topic(**item) for item in read_json(DATA_DIR / "topic_backlog.json")]
        return ResearchPacket(run_date=run_date, candidates=topics)


class StrategistAgent:
    """Pick one topic while avoiding immediate pillar repetition."""

    def run(self, packet: ResearchPacket) -> StrategyBrief:
        content_log = read_json(DATA_DIR / "content_log.json")
        existing_for_date = next(
            (entry for entry in reversed(content_log) if entry.get("date") == packet.run_date),
            None,
        )
        if existing_for_date:
            for candidate in packet.candidates:
                if candidate.topic == existing_for_date.get("topic"):
                    return StrategyBrief(
                        run_date=packet.run_date,
                        topic=candidate,
                        target_reader="IoT founders, automotive teams, and CTOs",
                        call_to_action="Use this as an early architecture review prompt before starting AOSP customization or BSP work.",
                    )

        last_pillar = content_log[-1]["pillar"] if content_log else None
        used_topics = {entry["topic"] for entry in content_log}

        unused_candidates = [
            candidate for candidate in packet.candidates if candidate.topic not in used_topics
        ]
        selected = next(
            (candidate for candidate in unused_candidates if candidate.pillar != last_pillar),
            None,
        )

        if selected is None and unused_candidates:
            selected = unused_candidates[0]

        if selected is None:
            raise TopicBacklogExhaustedError(
                "No eligible unused topics remain in the topic backlog."
            )

        return StrategyBrief(
            run_date=packet.run_date,
            topic=selected,
            target_reader="IoT founders, automotive teams, and CTOs",
            call_to_action="Use this as an early architecture review prompt before starting AOSP customization or BSP work.",
        )


class WriterAgent:
    """Create the master blog draft from the strategy brief."""

    def run(self, brief: StrategyBrief) -> Draft:
        topic = brief.topic
        title = topic.topic
        focus = self._focus_for_pillar(topic.pillar)
        body = f"""# {title}

Most Android platform work becomes expensive when the ownership model is discovered too late.

For {brief.target_reader}, the question is rarely just "can we make this work once?" The better question is whether the change will still be understandable during the next board revision, Android upgrade, or production support cycle.

## The engineering point

{topic.angle}

In this area, the useful review habit is to identify ownership before implementation. {focus}

When that ownership is unclear, the first build may still pass locally. The cost usually appears later:

- upgrade work becomes harder to estimate;
- product and vendor assumptions spread into places they do not belong;
- debugging requires more context than the team has written down;
- compatibility checks become late surprises instead of early signals.

## A practical review habit

Before accepting the change, ask:

- Which team or module owns this behavior?
- Is this generic platform logic, product configuration, device-specific code, or vendor-specific implementation?
- Does this change affect a public interface, build dependency, partition boundary, or compatibility requirement?
- Can the next engineer understand why this was changed?
- What will happen when the product moves to a newer Android release?

This is the type of review that prevents AOSP customization from becoming a pile of patches with no ownership model.

## Takeaway

Good AOSP engineering is not just making Android run on custom hardware.

It is making sure the product can still be upgraded, debugged, and maintained after the first successful boot.

For Ftechiz Pvt. Ltd., this is where BSP projects and custom Android ROM work should start: with clean ownership, verified assumptions, and a platform boundary that will survive production.
"""
        return Draft(title=title, body=body, sources=topic.sources)

    def _focus_for_pillar(self, pillar: str) -> str:
        focus_by_pillar = {
            "Architecture deep dives": "That means keeping Android framework behavior, HAL contracts, system services, and vendor implementation in their proper lanes.",
            "Build system": "That means keeping Android.bp modules, product configuration, dependencies, and build variants easy to reason about.",
            "Security": "That means treating SELinux, verified boot, permissions, and hardening choices as design constraints instead of final-week cleanup.",
            "Customization": "That means deciding where product behavior belongs before patches spread across framework, device, and vendor trees.",
            "Boot/OTA": "That means reviewing init, partition layout, recovery, and update strategy as one lifecycle problem.",
            "Platform": "That means looking at Android as a maintained product platform, not only a firmware image.",
            "Debugging": "That means naming the failing layer before collecting more logs.",
            "Industry": "That means separating headline-level changes from the engineering decisions they force.",
        }
        return focus_by_pillar.get(pillar, "That means connecting the implementation detail to long-term maintenance cost.")


class TechnicalReviewerAgent:
    """Gate drafts using approved sources and explicit uncertainty checks."""

    def run(self, draft: Draft) -> ReviewResult:
        source_config = read_json(DATA_DIR / "approved_sources.json")
        allowed = set(source_config["technical_authorities"])
        allowed.update(source_config["community_public_sources"])

        notes: list[str] = []
        status = "pass"

        if "[UNVERIFIED]" in draft.body or "[NEEDS REVIEW]" in draft.body:
            status = "blocked"
            notes.append("Draft contains unresolved verification markers.")

        if not draft.sources:
            status = "blocked"
            notes.append("Draft has no source links.")

        for source in draft.sources:
            host = urlparse(source).netloc.lower().removeprefix("www.")
            if host not in allowed:
                status = "blocked"
                notes.append(f"Source is not approved for technical authority: {source}")

        if status == "pass":
            notes.append("No unresolved verification markers found.")
            notes.append("All cited technical sources are on approved authority domains.")
            notes.append("Manual claim-level review is still required before publishing in later phases.")

        return ReviewResult(status=status, notes=notes, required_sources=draft.sources)


class RepurposerAgent:
    """Adapt a reviewed master draft into approved content channels."""

    def run(self, draft: Draft, review: ReviewResult, brief: StrategyBrief) -> RepurposedPackage:
        if review.status != "pass":
            return RepurposedPackage(
                drafts=[
                    PlatformDraft(
                        platform="approval",
                        title="Repurposing blocked",
                        body="Technical review must pass before platform drafts are prepared.",
                        status="blocked",
                        notes=["Reviewer did not pass the master draft."],
                    )
                ]
            )

        blog = PlatformDraft(
            platform="blog",
            title=draft.title,
            body=self._blog_body(draft),
            status="queued_for_approval",
            notes=["Canonical long-form version. Publish on owned site before syndication."],
        )
        linkedin = PlatformDraft(
            platform="linkedin",
            title=draft.title,
            body=self._linkedin_body(brief),
            status="queued_for_approval",
            notes=[
                "Prepared for manual/API-approved LinkedIn posting.",
                "No browser automation or scraping.",
            ],
        )
        reddit = PlatformDraft(
            platform="reddit",
            title=draft.title,
            body=self._reddit_body(brief),
            status="needs_rules_check",
            notes=[
                "Draft only. Do not auto-post.",
                "Check subreddit rules immediately before using this draft.",
                "Value-first and non-salesy by design; company link is intentionally omitted.",
            ],
        )
        return RepurposedPackage(drafts=[blog, linkedin, reddit])

    def _blog_body(self, draft: Draft) -> str:
        sources = "\n".join(f"- {source}" for source in draft.sources)
        return f"""{draft.body}

## Work With Ftechiz

For AOSP customization, BSP projects, and custom Android ROM engineering, visit {COMPANY_WEBSITE}

## Sources

{sources}
"""

    def _linkedin_body(self, brief: StrategyBrief) -> str:
        topic = brief.topic
        return f"""{topic.topic}

That sounds like an implementation detail. It usually becomes a maintenance decision.

For IoT, automotive, and custom Android products, the hard question is not only whether the first build works.

It is whether the change will still be understandable during the next board revision, Android upgrade, or production support cycle.

The angle I would use here:

{topic.angle}

Before accepting a platform patch, I like to ask:

- Which module or team owns this?
- Is it product-specific, vendor-specific, or generic Android platform logic?
- Does it affect a build dependency, HAL interface, partition boundary, or compatibility requirement?
- Will the next engineer understand why this exists?

When those answers are unclear, early progress can hide future upgrade cost.

Good BSP and custom ROM work needs clean ownership, verified assumptions, and engineering choices that are strong enough for production.

What is the AOSP change you always review carefully before release?

Ftechiz Pvt. Ltd.: {COMPANY_WEBSITE}

#AOSP #AndroidEngineering #EmbeddedAndroid #BSP #AutomotiveSoftware"""

    def _reddit_body(self, brief: StrategyBrief) -> str:
        topic = brief.topic
        return f"""Title: {topic.topic}

I have been thinking about this AOSP engineering pattern:

{topic.angle}

For teams building IoT, automotive, or custom Android devices, the risky part is often not the first successful build. It is whether the change remains understandable when the product needs a board revision, an Android upgrade, or production support.

The review questions I would use:

- Which module, partition, or team owns this behavior?
- Is this generic Android platform logic, product configuration, device-specific code, or vendor implementation?
- Does the change affect build dependencies, HAL contracts, compatibility checks, or update behavior?
- Would a new engineer understand why this exists six months later?

I am curious how other teams handle this in real AOSP/BSP work.

Where do you usually draw the line between a practical product patch and something that will become upgrade debt?

Rules check before posting:

- Confirm the target subreddit allows this type of technical discussion.
- Remove or rewrite anything that reads like promotion.
- Prefer discussion over links.
- Do not post the same draft across multiple subreddits.
"""
