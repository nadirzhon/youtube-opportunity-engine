"""
Backtesting — does the score actually predict the future? (Idea validation.)

Everything else answers "what looks like an opportunity *now*". This module
answers the only question that decides whether the idea has edge: **if we had
scored at time T using only data available then, would the high-scored topics
have actually grown afterwards?**

Method (proper temporal holdout — no lookahead):
  1. truncate every video's snapshot series to `cutoff_hours` (the decision time)
  2. run the full engine on that truncated world → scores + raw dimensions at T
  3. measure each topic's *realized* growth AFTER T from the untruncated series
  4. report predictive power: rank correlation of score↔future growth,
     precision@k and lift over the base rate

It also emits **calibration labels from observation alone** — (dimensions at T,
realized future growth) pairs — so the scorer can learn what predicts growth
WITHOUT us publishing anything. That is the cheapest, fastest learning signal the
system has, and it makes the idea self-validating.

Pure stdlib, deterministic. Honest by construction: a flat/negative correlation
here means the scoring has no edge on this data, and the report says so.
"""

from __future__ import annotations

import dataclasses
import statistics as st

from .models import Channel, Video
from .pipeline import _run_on


# ---------------------------------------------------------------------------
# Temporal holdout helpers
# ---------------------------------------------------------------------------
def _truncate(video: Video, cutoff_hours: float) -> Video | None:
    """A copy of the video as it looked at `cutoff_hours`: only snapshots ≤ T."""
    past = [s for s in video.snapshots if s.at_hours <= cutoff_hours]
    if not past:
        return None
    return dataclasses.replace(video, snapshots=past,
                               published_hours_ago=min(video.published_hours_ago,
                                                       max(s.at_hours for s in past)))


def realized_growth(video: Video, cutoff_hours: float) -> float | None:
    """Fractional view growth from T to the last observation. None if we can't
    measure it (no data at T, or no future data, or zero base)."""
    past = [s for s in video.snapshots if s.at_hours <= cutoff_hours]
    future = [s for s in video.snapshots if s.at_hours > cutoff_hours]
    if not past or not future:
        return None
    base = past[-1].view_count
    if base <= 0:
        return None
    return (future[-1].view_count - base) / base


# ---------------------------------------------------------------------------
# Correlation / ranking metrics (stdlib)
# ---------------------------------------------------------------------------
def _pearson(xs: list[float], ys: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    return num / (dx ** 0.5 * dy ** 0.5) if dx > 0 and dy > 0 else 0.0


def _rank(xs: list[float]) -> list[float]:
    """Average-rank of each value (ties share the mean rank)."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _spearman(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 2:
        return 0.0
    return _pearson(_rank(xs), _rank(ys))


def _precision_at_k(scores: list[float], outcomes: list[float], k: int) -> tuple[float, float]:
    """Of the top-k by score, the fraction whose outcome beats the median outcome,
    and the lift over the base rate (fraction above median overall)."""
    n = len(scores)
    if n == 0 or k <= 0:
        return 0.0, 0.0
    k = min(k, n)
    med = st.median(outcomes)
    base = sum(1 for o in outcomes if o > med) / n or 1e-9
    top = sorted(range(n), key=lambda i: scores[i], reverse=True)[:k]
    hits = sum(1 for i in top if outcomes[i] > med) / k
    return round(hits, 3), round(hits / base, 2)


# ---------------------------------------------------------------------------
# The backtest
# ---------------------------------------------------------------------------
def run_backtest(channels: list[Channel], videos_by_channel: dict[str, list[Video]],
                 cutoff_hours: float, *, k: int = 3,
                 weights: dict[str, float] | None = None) -> dict:
    """Score the world as of `cutoff_hours`, then grade against what actually
    happened. Pass `weights` (e.g. calibrated ones) to test whether they improve
    predictive power. Returns predictive-power metrics + per-topic detail."""
    # 1) truncated world → engine scores at T
    trunc: dict[str, list[Video]] = {}
    for cid, vids in videos_by_channel.items():
        keep = [t for t in (_truncate(v, cutoff_hours) for v in vids) if t is not None]
        if keep:
            trunc[cid] = keep
    report = _run_on(channels, trunc, weights=weights)
    score_by_topic = {o.topic: o.score for o in report.opportunities}
    dims_by_topic = {o.topic: o.dimensions for o in report.opportunities}

    # 2) realized future growth per topic (from the untruncated series)
    growth_by_topic: dict[str, list[float]] = {}
    for vids in videos_by_channel.values():
        for v in vids:
            g = realized_growth(v, cutoff_hours)
            if g is None:
                continue
            topic = v.topics[0] if v.topics else "uncategorized"
            growth_by_topic.setdefault(topic, []).append(g)

    # 3) align topics that have both a score and a measurable future
    rows = []
    for topic, score in score_by_topic.items():
        gs = growth_by_topic.get(topic)
        if not gs:
            continue
        rows.append({"topic": topic, "score": score,
                     "realized_growth": round(st.mean(gs), 4),
                     "n_videos": len(gs)})
    rows.sort(key=lambda r: r["score"], reverse=True)

    scores = [r["score"] for r in rows]
    growth = [r["realized_growth"] for r in rows]
    p_at_k, lift = _precision_at_k(scores, growth, k)

    return {
        "cutoff_hours": cutoff_hours,
        "n_topics_evaluated": len(rows),
        "spearman_score_vs_growth": round(_spearman(scores, growth), 3),
        "pearson_score_vs_growth": round(_pearson(scores, growth), 3),
        "precision_at_k": p_at_k,
        "lift_over_base": lift,
        "k": k,
        "topics": rows,
        "verdict": _verdict(rows, _spearman(scores, growth)),
    }


def _verdict(rows: list[dict], spearman: float) -> str:
    if len(rows) < 3:
        return "inconclusive — too few topics with a measurable future; needs more history."
    if spearman >= 0.3:
        return f"positive edge — higher scores tracked higher realized growth (ρ={spearman:.2f})."
    if spearman <= -0.3:
        return f"NEGATIVE edge — the score anti-predicts growth (ρ={spearman:.2f}); rethink weights."
    return f"no clear edge yet (ρ={spearman:.2f}) — signal is weak; needs more/real data."


def calibration_labels(channels: list[Channel], videos_by_channel: dict[str, list[Video]],
                       cutoff_hours: float) -> list[dict]:
    """Turn a backtest into (dimensions@T, realized future growth) experiments the
    calibrator can learn from — no publishing required. Performance is the topic's
    realized growth, min-max normalized across topics into 0..1."""
    trunc: dict[str, list[Video]] = {}
    for cid, vids in videos_by_channel.items():
        keep = [t for t in (_truncate(v, cutoff_hours) for v in vids) if t is not None]
        if keep:
            trunc[cid] = keep
    report = _run_on(channels, trunc)
    dims_by_topic = {o.topic: o.dimensions for o in report.opportunities}

    growth_by_topic: dict[str, list[float]] = {}
    for vids in videos_by_channel.values():
        for v in vids:
            g = realized_growth(v, cutoff_hours)
            if g is None:
                continue
            topic = v.topics[0] if v.topics else "uncategorized"
            growth_by_topic.setdefault(topic, []).append(g)

    paired = [(t, st.mean(gs)) for t, gs in growth_by_topic.items() if t in dims_by_topic]
    if not paired:
        return []
    gvals = [g for _, g in paired]
    lo, hi = min(gvals), max(gvals)
    span = (hi - lo) or 1.0
    return [{
        "niche": t, "topic": t,
        "dimensions": dims_by_topic[t],
        "performance": round((g - lo) / span, 4),
        "source": "backtest",
    } for t, g in paired]
