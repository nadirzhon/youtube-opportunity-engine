"""Tests for the closed learning loop and the thumbnail engine (Phase 5/7)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import store
from yoe.agents import build_opportunity
from yoe.agents import thumbnail as thumb
from yoe.agents.schemas import Concept
from yoe.learning import (
    learned_boost, package_to_experiment, rerank_with_experience,
    record_publication, classify_hook, classify_title,
)
from yoe.pipeline import run
from yoe.providers.mock import MockYouTubeProvider


def _concept(angle="hands-on", promise="ship it in an hour", orig=1.0):
    return Concept(
        premise="do X the right way", target_viewer="builders",
        viewer_promise=promise, unique_angle=angle,
        hook="Here's what nobody tells you about X", story_arc=["a", "b"],
        thumbnail_concept="hero shot", title_hypotheses=["How to ship X fast"],
        why_differentiated="w", suggested_duration_sec=480, originality=orig)


# -- thumbnail engine -----------------------------------------------------
def test_thumbnail_generates_five_scored_options():
    opts = thumb.generate(_concept())
    assert len(opts) == 5
    assert all(0 <= t.overall <= 100 for t in opts)
    assert all(set(t.scores) >= {"clarity", "curiosity", "mobile_legible",
                                 "uniqueness", "honesty"} for t in opts)
    # ranked best-first among accepted
    accepted = [t for t in opts if t.accepted]
    assert accepted and accepted == sorted(accepted, key=lambda t: t.overall, reverse=True)
    # overlay stays short (mobile legibility)
    assert all(len(t.overlay_text.split()) <= 3 for t in opts)


def test_thumbnail_honesty_gate_rejects_misleading():
    # no concrete promise → open_loop drops below the honesty gate and is rejected
    thin = _concept(promise="")
    opts = thumb.generate(thin)
    ol = next(t for t in opts if t.direction == "open_loop")
    assert not ol.accepted and ol.scores["honesty"] < thumb.MIN_HONESTY
    # the best pick is always an accepted (honest) option
    assert thumb.best(thin).accepted


# -- classification -------------------------------------------------------
def test_hook_and_title_classifiers():
    assert classify_hook("Why does X fail?") == "question"
    assert classify_hook("I tried X for 30 days") == "story"
    assert classify_hook("Everyone gets X wrong") == "bold_claim"
    assert classify_title("How to ship X") == "howto"
    assert classify_title("Is X worth it?") == "question"
    assert classify_title("Top 5 X mistakes") == "list"


# -- experiment persistence ----------------------------------------------
def test_record_and_load_experiment_roundtrip():
    conn = store.connect(":memory:")
    opp = run(MockYouTubeProvider(1337)).opportunities[0]
    pkg = build_opportunity(opp)
    eid = record_publication(conn, pkg, performance=0.8, publish_hour=9,
                             video_url="https://x/y")
    assert eid > 0 and store.experiment_count(conn) == 1
    rows = store.load_experiments(conn, niche=pkg.topic)
    assert rows and rows[0]["performance"] == 0.8
    assert rows[0]["angle"] == pkg.chosen.unique_angle
    assert rows[0]["hook_style"] in {"question", "story", "bold_claim", "direct"}
    conn.close()


def test_package_to_experiment_clips_performance():
    pkg = run(MockYouTubeProvider(1337)).opportunities[0]
    pkg = build_opportunity(pkg)
    e = package_to_experiment(pkg, performance=1.7)
    assert e["performance"] == 1.0            # clipped into [0,1]
    assert e["niche"] == e["topic"]


# -- the loop actually biases the next choice -----------------------------
def test_learned_boost_prefers_winning_angle():
    history = (
        [{"niche": "ai", "angle": "hands-on", "performance": 0.9}] * 5 +
        [{"niche": "ai", "angle": "listicle", "performance": 0.1}] * 5
    )
    scorer = learned_boost(history, attr="angle")
    assert scorer("hands-on") > 0 > scorer("listicle")
    assert scorer("never-seen") == 0.0        # unseen → neutral, still explorable
    # bandit is warm-started for exploration
    assert "hands-on" in scorer.bandit.arms


def test_rerank_moves_proven_angle_up():
    winner = _concept(angle="hands-on")
    winner.rank_score = 0.50
    loser = _concept(angle="listicle")
    loser.rank_score = 0.55                    # starts ahead
    history = ([{"niche": "ai", "angle": "hands-on", "performance": 0.95}] * 6 +
               [{"niche": "ai", "angle": "listicle", "performance": 0.05}] * 6)
    scorer = learned_boost(history, attr="angle")
    ranked = rerank_with_experience([loser, winner], scorer)
    assert ranked[0].unique_angle == "hands-on"   # experience overturns the order


def test_build_opportunity_accepts_experience_and_emits_thumbnails():
    opp = run(MockYouTubeProvider(1337)).opportunities[0]
    history = [{"niche": opp.topic, "angle": "hands-on", "performance": 0.9}] * 4
    scorer = learned_boost(history, attr="angle")
    pkg = build_opportunity(opp, experience=scorer)
    assert pkg.thumbnails and pkg.thumbnails[0].accepted
    d = pkg.to_dict()
    assert d["thumbnails"] and "overlay_text" in d["thumbnails"][0]
