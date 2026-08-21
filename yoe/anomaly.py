"""
Anomaly engine — the heart of the system.

A video is interesting when its performance is abnormal *relative to an
appropriate baseline*, not because its raw view count is high. This module:

  1. builds per-channel baselines (median views, age-normalized expectation),
  2. derives velocity / acceleration from the snapshot time-series,
  3. scores each video with a robust, explainable method (MAD z-score of the
     age-adjusted views-to-median ratio, blended with velocity), and
  4. classifies it (normal / interesting / breakout / extreme_breakout) with a
     human-readable explanation.

Pure stdlib (statistics/math) — no numpy — so it runs anywhere and is fully
deterministic for tests.
"""

from __future__ import annotations

import math
import statistics as st

from .models import AnomalyClass, AnomalyResult, Channel, Video


def _median(xs: list[float]) -> float:
    return st.median(xs) if xs else 0.0


def _mad(xs: list[float], med: float) -> float:
    """Median absolute deviation — robust spread, immune to the breakout itself."""
    if not xs:
        return 0.0
    return st.median([abs(x - med) for x in xs]) or 1e-9


def _age_expected(views_by_age: list[tuple[float, float]], age: float) -> float:
    """Expected views for a channel's video at `age` hours.

    Uses the channel's own videos: average views-per-hour across its catalog,
    projected to this age. Falls back to the median when data is thin.
    """
    rates = [v / a for a, v in views_by_age if a > 0]
    if not rates:
        return 0.0
    return st.median(rates) * age


def velocity(video: Video) -> float:
    """Views per hour over the most recent snapshot interval."""
    s = video.snapshots
    if len(s) < 2:
        return (s[0].view_count / max(s[0].at_hours, 1)) if s else 0.0
    a, b = s[-2], s[-1]
    dt = max(b.at_hours - a.at_hours, 1e-6)
    return (b.view_count - a.view_count) / dt


def acceleration(video: Video) -> float:
    """Change in velocity over the last two intervals (dv/dt)."""
    s = video.snapshots
    if len(s) < 3:
        return 0.0
    v_late = (s[-1].view_count - s[-2].view_count) / max(s[-1].at_hours - s[-2].at_hours, 1e-6)
    v_early = (s[-2].view_count - s[-3].view_count) / max(s[-2].at_hours - s[-3].at_hours, 1e-6)
    dt = max(s[-1].at_hours - s[-3].at_hours, 1e-6)
    return (v_late - v_early) / dt


def channel_baseline(videos: list[Video]) -> dict[str, float]:
    views = [float(v.views) for v in videos if v.views > 0]
    med = _median(views)
    return {
        "median_views": med,
        "mad": _mad(views, med),
        "n": float(len(views)),
    }


def score_channel(channel: Channel, videos: list[Video]) -> list[AnomalyResult]:
    base = channel_baseline(videos)
    med, mad = base["median_views"], base["mad"]
    views_by_age = [(v.published_hours_ago, float(v.views)) for v in videos if v.views > 0]
    results: list[AnomalyResult] = []

    for v in videos:
        views = float(v.views)
        expected = _age_expected(views_by_age, v.published_hours_ago) or med or 1.0
        breakout_ratio = views / expected if expected else 0.0
        median_ratio = (views / med) if med else 0.0
        vel = velocity(v)
        acc = acceleration(v)
        engagement = 0.0
        if v.latest and v.latest.view_count:
            engagement = (v.latest.like_count + v.latest.comment_count) / v.latest.view_count

        # Robust z-score of this video's views vs channel distribution.
        z = 0.6745 * (views - med) / mad if mad else 0.0

        features = {
            "views": views,
            "expected_at_age": round(expected, 1),
            "breakout_ratio": round(breakout_ratio, 2),
            "views_to_median_ratio": round(median_ratio, 2),
            "robust_z": round(z, 2),
            "views_per_hour": round(vel, 1),
            "acceleration": round(acc, 3),
            "engagement_ratio": round(engagement, 4),
            "video_age_hours": v.published_hours_ago,
        }

        score = _combine(breakout_ratio, z, vel, med)
        klass = _classify(score, breakout_ratio)
        results.append(AnomalyResult(
            video_id=v.video_id, channel_id=v.channel_id, score=round(score, 1),
            classification=klass, features=features,
            explanation=_explain(klass, features)))

    results.sort(key=lambda r: r.score, reverse=True)
    return results


def _combine(breakout_ratio: float, z: float, vel: float, med: float) -> float:
    """Blend the age-adjusted breakout ratio, robust z and raw velocity → 0..100."""
    # breakout_ratio: 1 = expected, >3 notable, >8 extreme → log-scaled
    r = max(breakout_ratio, 0.0)
    ratio_component = min(60.0, 20.0 * math.log(1 + r))      # ~0..60
    z_component = min(30.0, max(0.0, z) * 4.0)               # robust outlier
    vel_norm = vel / (med / 24 + 1e-9) if med else 0.0       # velocity vs a day's worth of median
    vel_component = min(10.0, max(0.0, math.log1p(vel_norm)) * 4.0)
    return max(0.0, min(100.0, ratio_component + z_component + vel_component))


def _classify(score: float, breakout_ratio: float) -> AnomalyClass:
    if score >= 75 or breakout_ratio >= 8:
        return AnomalyClass.EXTREME_BREAKOUT
    if score >= 55 or breakout_ratio >= 3.5:
        return AnomalyClass.BREAKOUT
    if score >= 35:
        return AnomalyClass.INTERESTING
    return AnomalyClass.NORMAL


def _explain(klass: AnomalyClass, f: dict[str, float]) -> list[str]:
    out = []
    if f["breakout_ratio"] >= 2:
        out.append(f"{f['breakout_ratio']}× the views expected for this channel at "
                   f"{f['video_age_hours']:.0f}h old.")
    if f["views_to_median_ratio"] >= 2:
        out.append(f"{f['views_to_median_ratio']}× the channel's median video.")
    if f["robust_z"] >= 3:
        out.append(f"Robust z-score {f['robust_z']} — a clear statistical outlier.")
    if f["views_per_hour"] > 0:
        out.append(f"Currently gaining ~{f['views_per_hour']:.0f} views/hour.")
    if f["acceleration"] > 0:
        out.append("Growth is still accelerating.")
    if not out:
        out.append("Within normal range for its channel.")
    return out
