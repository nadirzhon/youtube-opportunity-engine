"""
Trend & niche engine.

Clusters videos into topics and decides, for each topic, whether it's a
repeatable opportunity or one-off viral noise — the key question the spec asks.
The signal that separates them is *breadth*: a real trend has several
INDEPENDENT channels accelerating on the same topic, not one lucky video.

Clustering here is keyword/topic-tag based (deterministic, dependency-free). A
later phase swaps in embedding-based clustering behind the same interface.
"""

from __future__ import annotations

import statistics as st

from .anomaly import acceleration, velocity
from .models import TopicCluster, TrendStage, Video


def cluster_by_topic(videos: list[Video]) -> dict[str, list[Video]]:
    clusters: dict[str, list[Video]] = {}
    for v in videos:
        for t in (v.topics or ("uncategorized",)):
            clusters.setdefault(t, []).append(v)
    return clusters


def _stage(n_channels: int, young_share: float, avg_age: float) -> TrendStage:
    """Map breadth + youth onto a trend stage.

    The signal that separates a repeatable trend from one-off noise is BREADTH
    (independent channels) combined with YOUTH (a high share of recent videos
    still pulling views). Individual videos naturally decelerate, so per-video
    acceleration is a poor stage signal — young_share is what matters.
    """
    if n_channels <= 1:
        return TrendStage.LATENT
    if n_channels >= 3 and young_share >= 0.5:
        return TrendStage.ACCELERATING
    if n_channels >= 2 and young_share >= 0.3:
        return TrendStage.EMERGING
    if n_channels >= 4 and young_share < 0.2:
        return TrendStage.SATURATED
    if n_channels >= 3:
        return TrendStage.MAINSTREAM
    return TrendStage.DECLINING if young_share < 0.15 else TrendStage.EMERGING


def analyze_topics(videos: list[Video]) -> list[TopicCluster]:
    out: list[TopicCluster] = []
    for topic, vids in cluster_by_topic(videos).items():
        channels = sorted({v.channel_id for v in vids})
        vels = [velocity(v) for v in vids]
        accs = [acceleration(v) for v in vids]
        ages = [v.published_hours_ago for v in vids]
        topic_vel = sum(vels)
        topic_acc = st.mean(accs) if accs else 0.0
        avg_age = st.mean(ages) if ages else 0.0
        young_share = (len([a for a in ages if a <= 72]) / len(ages)) if ages else 0.0
        # dispersion: how evenly growth is spread across channels (0 = concentrated)
        by_ch: dict[str, float] = {}
        for v, vel in zip(vids, vels):
            by_ch[v.channel_id] = by_ch.get(v.channel_id, 0.0) + max(vel, 0.0)
        vals = list(by_ch.values())
        dispersion = (st.pstdev(vals) / (st.mean(vals) + 1e-9)) if len(vals) > 1 else 0.0
        dispersion = 1.0 - min(1.0, dispersion)  # 1 = evenly spread across channels

        stage = _stage(len(channels), young_share, avg_age)
        out.append(TopicCluster(
            topic=topic,
            video_ids=[v.video_id for v in vids],
            channel_ids=channels,
            stage=stage,
            velocity=round(topic_vel, 1),
            acceleration=round(topic_acc, 3),
            signals={
                "independent_channels": float(len(channels)),
                "avg_age_hours": round(avg_age, 1),
                "young_share": round(young_share, 2),
                "channel_spread": round(dispersion, 2),
                "video_count": float(len(vids)),
            },
        ))
    out.sort(key=lambda c: (c.signals["independent_channels"], c.velocity), reverse=True)
    return out
