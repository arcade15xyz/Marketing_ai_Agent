from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Topic:
    pillar: str
    topic: str
    angle: str
    format: str
    sources: list[str]


@dataclass(frozen=True)
class ResearchPacket:
    run_date: str
    candidates: list[Topic]


@dataclass(frozen=True)
class StrategyBrief:
    run_date: str
    topic: Topic
    target_reader: str
    call_to_action: str


@dataclass(frozen=True)
class Draft:
    title: str
    body: str
    sources: list[str]


@dataclass(frozen=True)
class ReviewResult:
    status: str
    notes: list[str]
    required_sources: list[str]


@dataclass(frozen=True)
class PlatformDraft:
    platform: str
    title: str
    body: str
    status: str
    notes: list[str]


@dataclass(frozen=True)
class RepurposedPackage:
    drafts: list[PlatformDraft]


@dataclass(frozen=True)
class AnalyticsReport:
    week_start: str
    week_end: str
    summary: list[str]
    recommendations: list[str]
    rows: list[JsonObject]


@dataclass(frozen=True)
class PipelinePaths:
    root: Path
    output_dir: Path
    research: Path
    strategy: Path
    draft: Path
    review: Path
    blog: Path
    linkedin: Path
    reddit: Path
    approval: Path
    package: Path


JsonObject = dict[str, Any]

