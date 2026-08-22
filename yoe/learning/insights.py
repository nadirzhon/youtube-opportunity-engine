"""
Learning insights (Phase 7).

Converts recorded experiments into "what works": for each attribute (angle, hook
style, title structure, duration bucket, publish hour) it measures mean
normalized performance and lift vs the overall average — the feature-importance
view that feeds better future recommendations. Also builds niche-specific priors
to warm-start the bandit per niche.

Pure stdlib. An Experiment is a plain dict:
  {topic, niche, angle, hook_style, title_structure, duration_sec,
   publish_hour, performance}  where performance is a 0..1 normalized score.
"""

from __future__ import annotations

import statistics as st
from collections import defaultdict

_ATTRS = ["angle", "hook_style", "title_structure", "duration_bucket", "publish_hour"]


def _duration_bucket(sec) -> str:
    sec = sec or 0
    if sec < 300:
        return "<5m"
    if sec < 600:
        return "5-10m"
    if sec < 900:
        return "10-15m"
    return "15m+"


def _normalize(exp: dict) -> dict:
    e = dict(exp)
    e["duration_bucket"] = _duration_bucket(exp.get("duration_sec"))
    e["publish_hour"] = str(exp.get("publish_hour", "?"))
    return e


def insights(experiments: list[dict]) -> dict:
    if not experiments:
        return {"n": 0, "baseline": 0.0, "attributes": {}}
    exps = [_normalize(e) for e in experiments]
    perfs = [float(e.get("performance", 0.0)) for e in exps]
    baseline = round(st.mean(perfs), 3)

    out: dict[str, list] = {}
    for attr in _ATTRS:
        groups: dict[str, list[float]] = defaultdict(list)
        for e in exps:
            v = e.get(attr)
            if v is not None:
                groups[str(v)].append(float(e.get("performance", 0.0)))
        rows = []
        for val, ps in groups.items():
            m = st.mean(ps)
            rows.append({"value": val, "mean": round(m, 3),
                         "lift": round(m - baseline, 3), "n": len(ps)})
        rows.sort(key=lambda r: r["mean"], reverse=True)
        out[attr] = rows
    return {"n": len(exps), "baseline": baseline, "attributes": out}


def niche_priors(experiments: list[dict], attr: str = "angle") -> dict[str, dict[str, tuple[float, float]]]:
    """Beta(alpha,beta) priors per niche per attribute value, to warm-start the
    bandit. A high-performing value gets a stronger success prior."""
    exps = [_normalize(e) for e in experiments]
    priors: dict[str, dict[str, tuple[float, float]]] = defaultdict(dict)
    by_niche: dict[str, list[dict]] = defaultdict(list)
    for e in exps:
        by_niche[str(e.get("niche", "_"))].append(e)
    for niche, es in by_niche.items():
        groups: dict[str, list[float]] = defaultdict(list)
        for e in es:
            groups[str(e.get(attr))].append(float(e.get("performance", 0.0)))
        for val, ps in groups.items():
            m = st.mean(ps)
            n = len(ps)
            priors[niche][val] = (round(1 + m * n, 2), round(1 + (1 - m) * n, 2))
    return dict(priors)
