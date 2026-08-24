"""
Domain model for the YouTube Opportunity Engine.

Plain dataclasses (stdlib only) so the intelligence core runs and is testable
without a database. The FastAPI/SQLAlchemy layer (a later phase) maps these to
tables — the shapes here are the source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TrendStage(str, Enum):
    LATENT = "latent"
    EMERGING = "emerging"
    ACCELERATING = "accelerating"
    MAINSTREAM = "mainstream"
    SATURATED = "saturated"
    DECLINING = "declining"


class AnomalyClass(str, Enum):
    NORMAL = "normal"
    INTERESTING = "interesting"
    BREAKOUT = "breakout"
    EXTREME_BREAKOUT = "extreme_breakout"


@dataclass
class Channel:
    channel_id: str
    title: str
    subscriber_count: int
    video_count: int
    topics: tuple[str, ...] = ()


@dataclass
class VideoSnapshot:
    """A point-in-time reading of a video's counters — the basis for velocity."""
    at_hours: float          # hours since the video was published
    view_count: int
    like_count: int = 0
    comment_count: int = 0


@dataclass
class Video:
    video_id: str
    channel_id: str
    title: str
    published_hours_ago: float
    duration_sec: int
    category: str
    topics: tuple[str, ...] = ()
    snapshots: list[VideoSnapshot] = field(default_factory=list)

    @property
    def latest(self) -> VideoSnapshot | None:
        return self.snapshots[-1] if self.snapshots else None

    @property
    def views(self) -> int:
        return self.latest.view_count if self.latest else 0


@dataclass
class AnomalyResult:
    video_id: str
    channel_id: str
    score: float                       # 0..100
    classification: AnomalyClass
    features: dict[str, float]
    explanation: list[str]

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["classification"] = self.classification.value
        return d


@dataclass
class TopicCluster:
    topic: str
    video_ids: list[str]
    channel_ids: list[str]
    stage: TrendStage
    velocity: float                    # aggregate topic view-velocity
    acceleration: float
    signals: dict[str, float]


@dataclass
class Opportunity:
    topic: str
    score: float                       # 0..100
    confidence: float                  # 0..1
    stage: TrendStage
    breakdown: dict[str, float]        # per-dimension weighted contribution
    evidence: list[str]
    reasons_against: list[str]
    sample_video_ids: list[str]
    recommended_action: str
    dimensions: dict[str, float] = field(default_factory=dict)  # raw 0..1 signals

    def to_dict(self) -> dict[str, Any]:
        d = self.__dict__.copy()
        d["stage"] = self.stage.value
        return d
