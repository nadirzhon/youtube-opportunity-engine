"""
Pipeline orchestrator — the end-to-end intelligence loop.

collect (provider) → anomalies (per channel) → topic clusters/trend stage →
opportunity scoring → ranked, explainable report. This is the through-line the
acceptance test exercises; the API and dashboard (later phases) call into it.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import anomaly, opportunity, trend
from .models import AnomalyResult, Channel, Opportunity, TopicCluster, Video

# Channels above this subscriber count count as "established" for competition.
_BIG_CHANNEL_SUBS = 100_000


@dataclass
class EngineReport:
    channels: list[Channel]
    videos: list[Video]
    anomalies: list[AnomalyResult]
    topics: list[TopicCluster]
    opportunities: list[Opportunity]

    @property
    def breakouts(self) -> list[AnomalyResult]:
        from .models import AnomalyClass
        return [a for a in self.anomalies
                if a.classification in (AnomalyClass.BREAKOUT, AnomalyClass.EXTREME_BREAKOUT)]


def run(provider) -> EngineReport:
    channels = provider.list_channels()
    big = {c.channel_id for c in channels if c.subscriber_count >= _BIG_CHANNEL_SUBS}

    all_videos: list[Video] = []
    all_anoms: list[AnomalyResult] = []
    for ch in channels:
        vids = provider.list_videos(ch.channel_id)
        all_videos.extend(vids)
        all_anoms.extend(anomaly.score_channel(ch, vids))

    topics = trend.analyze_topics(all_videos)

    anoms_by_topic: dict[str, list[AnomalyResult]] = {}
    vid_topic = {v.video_id: (v.topics[0] if v.topics else "uncategorized") for v in all_videos}
    for a in all_anoms:
        anoms_by_topic.setdefault(vid_topic.get(a.video_id, "uncategorized"), []).append(a)

    opps = opportunity.rank_opportunities(topics, anoms_by_topic, big)
    return EngineReport(channels, all_videos, sorted(all_anoms, key=lambda a: a.score, reverse=True),
                        topics, opps)
