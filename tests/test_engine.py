"""Tests for the YouTube Opportunity Engine core. Run: pytest -q"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import anomaly, opportunity, trend
from yoe.models import AnomalyClass, TrendStage, Video, VideoSnapshot, Channel
from yoe.pipeline import run
from yoe.providers.mock import MockYouTubeProvider


def _vid(vid, ch, snaps, age=48, topics=("t",)):
    return Video(vid, ch, vid, age, 600, "cat", topics,
                 [VideoSnapshot(*s) for s in snaps])


# -- anomaly math ---------------------------------------------------------
def test_velocity_and_acceleration():
    v = _vid("v", "c", [(1, 100), (2, 300), (3, 700)])  # rising velocity
    assert anomaly.velocity(v) == 400  # (700-300)/(3-2)
    assert anomaly.acceleration(v) > 0  # velocity increased


def test_breakout_scores_higher_than_normal():
    ch = Channel("c", "c", 10000, 100)
    normal = [_vid(f"n{i}", "c", [(24, 1000)]) for i in range(6)]
    breakout = _vid("BIG", "c", [(1, 2000), (12, 15000), (24, 30000)], age=24)
    results = anomaly.score_channel(ch, normal + [breakout])
    top = results[0]
    assert top.video_id == "BIG"
    assert top.classification in (AnomalyClass.BREAKOUT, AnomalyClass.EXTREME_BREAKOUT)
    assert top.score > 55
    # a normal video stays normal
    norm = next(r for r in results if r.video_id == "n0")
    assert norm.classification == AnomalyClass.NORMAL


def test_anomaly_has_explanation():
    ch = Channel("c", "c", 10000, 100)
    vids = [_vid(f"n{i}", "c", [(24, 1000)]) for i in range(5)]
    vids.append(_vid("BIG", "c", [(24, 40000)], age=24))
    for r in anomaly.score_channel(ch, vids):
        assert r.explanation  # never empty


# -- trend / niche --------------------------------------------------------
def test_single_channel_topic_is_latent_not_a_trend():
    vids = [_vid(f"v{i}", "solo", [(24, 5000)], topics=("niche",)) for i in range(3)]
    clusters = {c.topic: c for c in trend.analyze_topics(vids)}
    assert clusters["niche"].stage == TrendStage.LATENT


def test_broad_young_topic_accelerates():
    vids = []
    for ch in range(4):                       # 4 independent channels
        vids.append(_vid(f"c{ch}v", f"ch{ch}", [(6, 8000), (12, 20000)], age=12, topics=("hot",)))
    clusters = {c.topic: c for c in trend.analyze_topics(vids)}
    assert clusters["hot"].stage == TrendStage.ACCELERATING
    assert clusters["hot"].signals["independent_channels"] == 4


# -- opportunity scoring --------------------------------------------------
def test_scoring_bounds_and_breakdown_sums():
    report = run(MockYouTubeProvider(seed=1337))
    for o in report.opportunities:
        assert 0 <= o.score <= 100
        assert 0 <= o.confidence <= 1
        assert abs(sum(o.breakdown.values()) - o.score) < 0.5  # breakdown reconciles


def test_saturated_topic_lists_reasons_against():
    # A broad, all-old topic → not open → must warn.
    vids = [_vid(f"c{c}v{i}", f"ch{c}", [(300, 4000)], age=300, topics=("old",))
            for c in range(5) for i in range(2)]
    clusters = trend.analyze_topics(vids)
    from yoe.anomaly import score_channel
    anoms = {"old": []}
    opps = opportunity.rank_opportunities(clusters, anoms, big_channel_ids=set())
    old = next(o for o in opps if o.topic == "old")
    assert old.reasons_against  # uncertainty/risks are surfaced


# -- end-to-end acceptance ------------------------------------------------
def test_e2e_planted_trend_is_top_opportunity():
    """The acceptance scenario: the engine finds the planted repeatable trend,
    ranks it #1, marks it accelerating and recommends pursuing it."""
    report = run(MockYouTubeProvider(seed=1337))
    assert report.breakouts, "should detect planted breakouts"
    top = report.opportunities[0]
    assert top.topic == "ai-agents-security"
    assert top.stage == TrendStage.ACCELERATING
    assert "Pursue" in top.recommended_action
    assert top.confidence >= 0.6
    assert top.evidence  # evidence-backed


def test_e2e_is_deterministic():
    a = run(MockYouTubeProvider(seed=1337)).opportunities[0].score
    b = run(MockYouTubeProvider(seed=1337)).opportunities[0].score
    assert a == b
