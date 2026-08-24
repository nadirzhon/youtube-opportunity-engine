"""Tests for the backtesting / idea-validation framework."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import backtest as bt
from yoe.models import Video, VideoSnapshot
from yoe.providers.mock import MockYouTubeProvider


# -- metric primitives ----------------------------------------------------
def test_spearman_perfect_and_inverse():
    assert round(bt._spearman([1, 2, 3, 4], [10, 20, 30, 40]), 6) == 1.0
    assert round(bt._spearman([1, 2, 3, 4], [40, 30, 20, 10]), 6) == -1.0


def test_precision_at_k_and_lift():
    # scores perfectly rank the outcomes → top-k all beat the median
    scores = [5, 4, 3, 2, 1]
    outcomes = [0.9, 0.8, 0.7, 0.2, 0.1]
    p, lift = bt._precision_at_k(scores, outcomes, k=2)
    assert p == 1.0 and lift >= 1.0


# -- temporal holdout -----------------------------------------------------
def _vid(snaps):
    return Video("v", "c", "t", published_hours_ago=snaps[-1][0], duration_sec=60,
                 category="x", topics=("ai",),
                 snapshots=[VideoSnapshot(a, v) for a, v in snaps])


def test_realized_growth_uses_only_future():
    v = _vid([(1, 100), (24, 200), (72, 500)])
    # at T=24: base=200, future last=500 → +150%
    assert bt.realized_growth(v, 24) == (500 - 200) / 200
    # no future beyond T=72 → None
    assert bt.realized_growth(v, 72) is None
    # no data at/under T=0 → None
    assert bt.realized_growth(v, 0) is None


def test_truncate_drops_future_snapshots():
    v = _vid([(1, 100), (24, 200), (72, 500)])
    t = bt._truncate(v, 24)
    assert [s.at_hours for s in t.snapshots] == [1, 24]
    assert t.published_hours_ago == 24


# -- full backtest on mock ------------------------------------------------
def test_run_backtest_structure_and_honesty():
    p = MockYouTubeProvider(1337)
    channels = p.list_channels()
    vbc = {c.channel_id: p.list_videos(c.channel_id) for c in channels}
    r = bt.run_backtest(channels, vbc, cutoff_hours=48, k=3)
    assert r["n_topics_evaluated"] >= 3
    assert -1.0 <= r["spearman_score_vs_growth"] <= 1.0
    assert 0.0 <= r["precision_at_k"] <= 1.0
    assert isinstance(r["verdict"], str) and r["verdict"]
    # topics are ranked by score, each carries a realized outcome
    assert all("realized_growth" in t for t in r["topics"])
    assert r["topics"] == sorted(r["topics"], key=lambda t: t["score"], reverse=True)


def test_leading_indicator_gives_early_edge():
    """Locks in the backtest-driven improvement: with the momentum leading
    indicator, scoring at an EARLY cutoff has positive predictive edge."""
    p = MockYouTubeProvider(1337)
    channels = p.list_channels()
    vbc = {c.channel_id: p.list_videos(c.channel_id) for c in channels}
    # momentum is now a scored dimension
    from yoe.pipeline import run
    assert "momentum" in run(p).opportunities[0].dimensions
    # early decision (young videos) → the score tracks realized future growth
    r = bt.run_backtest(channels, vbc, cutoff_hours=24, k=3)
    assert r["spearman_score_vs_growth"] > 0.3
    assert r["lift_over_base"] >= 1.0


def test_calibration_labels_are_valid_experiments():
    p = MockYouTubeProvider(1337)
    channels = p.list_channels()
    vbc = {c.channel_id: p.list_videos(c.channel_id) for c in channels}
    labels = bt.calibration_labels(channels, vbc, cutoff_hours=24)
    assert labels
    for e in labels:
        assert 0.0 <= e["performance"] <= 1.0
        assert isinstance(e["dimensions"], dict) and e["dimensions"]
        assert e["source"] == "backtest"
