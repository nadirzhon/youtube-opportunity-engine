"""
Self-calibrating opportunity scoring (Phase 7 — closing the loop on the SCORE).

The opportunity score is a weighted sum of dimensions (trend_velocity,
anomaly_strength, ...). The spec ships hand-tuned weights — a reasonable prior,
but a *guess*. This module makes the weights **earn their place**: it correlates
each dimension's value (recorded when we acted on an opportunity) with the
content's measured performance, and shifts weight toward the dimensions that
actually predicted success.

Crucially it is **regularized toward the spec priors by sample size** — with a
handful of experiments the weights barely move (you can't learn 10 weights from
3 points without overfitting); as real outcomes accumulate, the data takes over.
So it degrades to the spec defaults when it knows nothing, and sharpens as it
learns. Pure stdlib, deterministic.

An experiment must carry `dimensions` (the opportunity's raw 0..1 signals at the
time) and `performance` (0..1 outcome). Experiments without dimensions are
ignored by the calibrator.
"""

from __future__ import annotations

import statistics as st

from ..opportunity import WEIGHTS as SPEC_WEIGHTS


def _pearson(xs: list[float], ys: list[float]) -> float:
    """Pearson correlation; 0 when a series has no variance (undefined)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = st.mean(xs), st.mean(ys)
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs)
    dy = sum((y - my) ** 2 for y in ys)
    if dx <= 0 or dy <= 0:
        return 0.0
    return num / (dx ** 0.5 * dy ** 0.5)


def calibrate(experiments: list[dict], *, priors: dict[str, float] | None = None,
              reg: float = 8.0) -> dict[str, float]:
    """Return calibrated weights (sum ~1). Blends the spec priors with data-driven
    weights derived from dimension↔performance correlation, regularized by `reg`:
    weight = (reg·prior + N·data) / (reg + N). Falls back to priors when there is
    no usable signal."""
    priors = priors or SPEC_WEIGHTS
    usable = [e for e in experiments
              if isinstance(e.get("dimensions"), dict) and e.get("performance") is not None]
    n = len(usable)
    if n < 2:
        return dict(priors)

    perfs = [float(e["performance"]) for e in usable]
    corr: dict[str, float] = {}
    for dim in priors:
        vals = [float(e["dimensions"].get(dim, 0.0)) for e in usable]
        corr[dim] = max(0.0, _pearson(vals, perfs))   # only positive predictors earn weight

    total = sum(corr.values())
    if total <= 0:
        return dict(priors)                            # no dimension predicts → keep priors
    data_w = {d: corr[d] / total for d in priors}

    blended = {d: (reg * priors[d] + n * data_w[d]) / (reg + n) for d in priors}
    s = sum(blended.values()) or 1.0
    return {d: round(blended[d] / s, 4) for d in priors}


def calibration_report(experiments: list[dict], *, reg: float = 8.0) -> dict:
    """Human-readable view: sample size, per-dimension correlation with
    performance, and the resulting weight shift vs the spec priors."""
    usable = [e for e in experiments
              if isinstance(e.get("dimensions"), dict) and e.get("performance") is not None]
    weights = calibrate(experiments, reg=reg)
    perfs = [float(e["performance"]) for e in usable]
    rows = []
    for dim in SPEC_WEIGHTS:
        vals = [float(e["dimensions"].get(dim, 0.0)) for e in usable] if usable else []
        r = round(_pearson(vals, perfs), 3) if len(usable) >= 2 else None
        rows.append({
            "dimension": dim,
            "prior": SPEC_WEIGHTS[dim],
            "calibrated": weights[dim],
            "shift": round(weights[dim] - SPEC_WEIGHTS[dim], 4),
            "corr_with_performance": r,
        })
    rows.sort(key=lambda x: x["calibrated"], reverse=True)
    return {"n_usable": len(usable), "reg": reg, "weights": weights, "dimensions": rows}
