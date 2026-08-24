"""Tests for self-calibrating opportunity scoring."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe.learning import calibrate, calibration_report
from yoe.opportunity import WEIGHTS as SPEC


def _exp(dims: dict, perf: float) -> dict:
    return {"dimensions": dims, "performance": perf}


def test_no_data_returns_spec_priors():
    assert calibrate([]) == dict(SPEC)
    assert calibrate([_exp({"trend_velocity": 0.5}, 0.7)]) == dict(SPEC)  # n<2


def test_weights_always_sum_to_one():
    w = calibrate([_exp({d: 0.5 for d in SPEC}, 0.5) for _ in range(5)])
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_predictive_dimension_gains_weight():
    # anomaly_strength perfectly tracks performance; freshness is pure noise.
    exps = []
    for i in range(12):
        perf = i / 11.0
        dims = {d: 0.5 for d in SPEC}
        dims["anomaly_strength"] = perf          # perfectly correlated
        dims["freshness"] = (i % 2) * 1.0        # uncorrelated
        exps.append(_exp(dims, perf))
    w = calibrate(exps)
    # the predictive dimension is lifted above its prior; the noise one isn't
    assert w["anomaly_strength"] > SPEC["anomaly_strength"]
    assert w["anomaly_strength"] == max(w.values())
    assert abs(sum(w.values()) - 1.0) < 1e-6


def test_regularization_moves_slowly_with_few_points():
    strong = {d: 0.5 for d in SPEC}
    # only 2 points: data says trend_velocity is everything, but reg should damp it
    exps = [_exp({**strong, "trend_velocity": 0.1}, 0.1),
            _exp({**strong, "trend_velocity": 0.9}, 0.9)]
    w2 = calibrate(exps, reg=8.0)
    shift = abs(w2["trend_velocity"] - SPEC["trend_velocity"])
    # with reg=8 and n=2, movement is damped far below the un-regularized 0.82
    # (data alone would push trend_velocity to ~1.0); reg keeps it modest.
    assert shift < 0.2
    # a lower reg lets the same data move it more
    w_loose = calibrate(exps, reg=1.0)
    assert abs(w_loose["trend_velocity"] - SPEC["trend_velocity"]) > shift


def test_report_shape():
    exps = [_exp({d: 0.5 for d in SPEC}, 0.6) for _ in range(3)]
    rep = calibration_report(exps)
    assert rep["n_usable"] == 3
    assert abs(sum(rep["weights"].values()) - 1.0) < 1e-6
    assert len(rep["dimensions"]) == len(SPEC)
    assert {"dimension", "prior", "calibrated", "shift"} <= set(rep["dimensions"][0])
