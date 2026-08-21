"""Structured outputs for the content agents (dataclasses, stdlib)."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class ResearchThesis:
    topic: str
    audience_desire: str
    emotional_trigger: str
    content_gap: str
    recommended_angle: str
    oversupplied_angles: list[str]
    risks: list[str]
    evidence: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Concept:
    premise: str                 # one sentence
    target_viewer: str
    viewer_promise: str
    unique_angle: str
    hook: str
    story_arc: list[str]
    thumbnail_concept: str
    title_hypotheses: list[str]
    why_differentiated: str
    suggested_duration_sec: int
    originality: float = 1.0     # 1.0 = fully original vs source/breakout titles
    rank_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Script:
    title: str
    hook: str
    sections: list[dict]         # [{heading, beats:[...], retention_device}]
    outro: str
    word_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class QualityCheck:
    name: str
    passed: bool
    score: float                 # 0..100
    note: str


@dataclass
class QualityResult:
    passed: bool
    score: float                 # overall 0..100
    checks: list[QualityCheck]
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class OpportunityPackage:
    topic: str
    thesis: ResearchThesis
    concepts: list[Concept]
    chosen: Concept
    script: Script
    quality: QualityResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "topic": self.topic,
            "thesis": self.thesis.to_dict(),
            "concepts": [c.to_dict() for c in self.concepts],
            "chosen": self.chosen.to_dict(),
            "script": self.script.to_dict(),
            "quality": self.quality.to_dict(),
        }
