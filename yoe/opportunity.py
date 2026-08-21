"""
Opportunity ranking engine.

Turns anomalies + topic clusters into explainable, scored opportunities. Uses
the exact weighted dimensions from the spec, returns a per-dimension breakdown,
a confidence score, supporting evidence AND reasons against — uncertainty is
never hidden.

Dimensions that need external product context (creator_fit, monetization,
production_feasibility) use transparent heuristics for now and are the obvious
place to plug real signals in a later phase — each is isolated so it can be
replaced without touching the scoring math.
"""

from __future__ import annotations

import math

from .models import AnomalyClass, AnomalyResult, Opportunity, TopicCluster, TrendStage

WEIGHTS = {
    "trend_velocity": 0.18,
    "anomaly_strength": 0.16,
    "growth_acceleration": 0.12,
    "competition_inverse": 0.13,
    "saturation_inverse": 0.09,
    "repeatability": 0.11,
    "creator_fit": 0.06,
    "monetization_potential": 0.06,
    "production_feasibility": 0.05,
    "freshness": 0.04,
}

# Stages that still have room to enter.
_OPEN_STAGES = {TrendStage.LATENT, TrendStage.EMERGING, TrendStage.ACCELERATING}


def _norm_log(x: float, scale: float) -> float:
    """Squash a positive unbounded value into 0..1 with diminishing returns."""
    return max(0.0, min(1.0, math.log1p(max(x, 0.0)) / math.log1p(scale)))


def _dimensions(cluster: TopicCluster, anomalies: list[AnomalyResult],
                big_channel_ids: set[str]) -> dict[str, float]:
    n_ch = cluster.signals["independent_channels"]
    avg_age = cluster.signals["avg_age_hours"]
    spread = cluster.signals["channel_spread"]
    max_anom = max((a.score for a in anomalies), default=0.0) / 100.0

    big_in_topic = len([c for c in cluster.channel_ids if c in big_channel_ids])
    competition = big_in_topic / max(n_ch, 1)          # share of established players
    saturation = 0.0 if cluster.stage in _OPEN_STAGES else (
        1.0 if cluster.stage in (TrendStage.SATURATED, TrendStage.DECLINING) else 0.5)

    return {
        "trend_velocity": _norm_log(cluster.velocity, 5000),
        "anomaly_strength": max_anom,
        "growth_acceleration": max(0.0, min(1.0, 0.5 + cluster.acceleration * 5)),
        "competition_inverse": 1.0 - competition,
        "saturation_inverse": 1.0 - saturation,
        "repeatability": min(1.0, (n_ch - 1) / 4.0) * (0.5 + 0.5 * spread),
        "creator_fit": 0.6,                            # heuristic (plug real profile later)
        "monetization_potential": 0.6,                 # heuristic (plug niche economics later)
        "production_feasibility": 0.7,                 # heuristic (plug format/cost later)
        "freshness": max(0.0, min(1.0, 1.0 - avg_age / 336.0)),  # 336h = 14d
    }


def _confidence(cluster: TopicCluster, anomalies: list[AnomalyResult]) -> float:
    n_ch = cluster.signals["independent_channels"]
    n_vid = cluster.signals["video_count"]
    strong = len([a for a in anomalies if a.classification in
                  (AnomalyClass.BREAKOUT, AnomalyClass.EXTREME_BREAKOUT)])
    c = 0.25 + 0.15 * min(n_ch, 4) + 0.05 * min(n_vid, 6) + 0.1 * min(strong, 3)
    return round(max(0.0, min(1.0, c)), 2)


def _reasons_against(cluster: TopicCluster, dims: dict[str, float], conf: float) -> list[str]:
    out = []
    if cluster.stage in (TrendStage.SATURATED, TrendStage.MAINSTREAM):
        out.append(f"Topic is {cluster.stage.value} — likely late to enter.")
    if cluster.stage == TrendStage.DECLINING:
        out.append("Topic momentum is fading (declining stage).")
    if dims["competition_inverse"] < 0.4:
        out.append("Established channels already dominate this topic.")
    if cluster.signals["independent_channels"] < 2:
        out.append("Only one channel driving it — may be one-off noise, not a trend.")
    if conf < 0.5:
        out.append(f"Low confidence ({conf}) — thin data, treat as a lead, not a bet.")
    return out


def _action(score: float, stage: TrendStage, conf: float) -> str:
    if score >= 70 and stage in _OPEN_STAGES and conf >= 0.6:
        return "Pursue now — strong, open, well-supported."
    if score >= 55 and stage in _OPEN_STAGES:
        return "Build a concept and test — promising but verify."
    if score >= 40:
        return "Watch — add to the monitor list, revisit in 48–72h."
    return "Skip — weak or saturated."


def rank_opportunities(clusters: list[TopicCluster],
                       anomalies_by_topic: dict[str, list[AnomalyResult]],
                       big_channel_ids: set[str]) -> list[Opportunity]:
    out: list[Opportunity] = []
    for cluster in clusters:
        anoms = anomalies_by_topic.get(cluster.topic, [])
        dims = _dimensions(cluster, anoms, big_channel_ids)
        breakdown = {k: round(WEIGHTS[k] * dims[k] * 100, 2) for k in WEIGHTS}
        score = round(sum(breakdown.values()), 1)
        conf = _confidence(cluster, anoms)

        top = sorted(anoms, key=lambda a: a.score, reverse=True)[:3]
        evidence = [
            f"{int(cluster.signals['independent_channels'])} independent channels active, "
            f"{int(cluster.signals['video_count'])} videos.",
            f"Topic view-velocity ~{cluster.velocity:.0f}/h, stage: {cluster.stage.value}.",
        ]
        for a in top:
            if a.explanation:
                evidence.append(f"{a.video_id}: {a.explanation[0]}")

        out.append(Opportunity(
            topic=cluster.topic, score=score, confidence=conf, stage=cluster.stage,
            breakdown=breakdown, evidence=evidence,
            reasons_against=_reasons_against(cluster, dims, conf),
            sample_video_ids=[a.video_id for a in top],
            recommended_action=_action(score, cluster.stage, conf)))
    out.sort(key=lambda o: o.score, reverse=True)
    return out
