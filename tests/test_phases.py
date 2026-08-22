"""Tests for Phase 2/6/7/8 (quota, scheduler, video factory, learning, security)."""

from __future__ import annotations

import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import security, store
from yoe.agents import build_opportunity
from yoe.factory import build as build_video
from yoe.learning import Bandit, insights, niche_priors
from yoe.pipeline import run
from yoe.providers.mock import MockYouTubeProvider
from yoe.quota import BudgetExceeded, QuotaManager, backoff_delay
from yoe.scheduler import due_for_snapshot, sampling_priority, tick


# -- Phase 2: quota & cost ------------------------------------------------
def test_quota_hard_stop_on_youtube_units():
    q = QuotaManager(daily_quota=150)
    q.charge_quota("search.list")            # 100
    assert not q.can_afford_quota("search.list")  # +100 > 150
    with pytest.raises(BudgetExceeded):
        q.charge_quota("search.list")


def test_cost_budget_and_per_channel():
    q = QuotaManager(daily_budget_usd=0.10, per_channel_budget_usd=0.06)
    q.charge("llm_request", channel="A")     # 0.01
    assert q.can_afford("voice_generation", channel="A")   # 0.05 → 0.06 ok
    q.charge("voice_generation", channel="A")
    assert not q.can_afford("llm_request", channel="A")    # over per-channel
    assert q.day_spend == pytest.approx(0.06)


def test_cache_dedup():
    q = QuotaManager()
    calls = {"n": 0}
    def produce():
        calls["n"] += 1
        return 42
    assert q.cached("k", produce) == 42
    assert q.cached("k", produce) == 42
    assert calls["n"] == 1 and q.cache_hits == 1


def test_backoff_grows():
    assert backoff_delay(0) < backoff_delay(2) <= 60


# -- Phase 2: scheduler ---------------------------------------------------
def test_sampling_cadence():
    assert sampling_priority(5) == "high"
    assert sampling_priority(80) == "medium"
    assert sampling_priority(400) == "low"
    assert due_for_snapshot(5, 2) and not due_for_snapshot(400, 2)


def test_scheduler_tick_collects_under_quota():
    conn = store.connect(":memory:")
    q = QuotaManager(daily_quota=100000)
    res = tick(conn, MockYouTubeProvider(1337), q)
    assert res.collected["channels"] > 0
    assert res.quota["quota_used"] > 0
    conn.close()


def test_scheduler_skips_when_over_quota():
    conn = store.connect(":memory:")
    res = tick(conn, MockYouTubeProvider(1337), QuotaManager(daily_quota=1))
    assert res.skipped_over_budget
    assert res.collected["channels"] == 0
    conn.close()


# -- Phase 6: video factory ----------------------------------------------
def test_video_factory_produces_draft():
    opp = run(MockYouTubeProvider(1337)).opportunities[0]
    pkg = build_opportunity(opp)
    with tempfile.TemporaryDirectory() as d:
        proj = build_video(pkg.script, d)
        assert proj.scenes and proj.images and proj.duration_sec > 0
        assert os.path.exists(proj.voice.path)
        assert os.path.exists(proj.subtitles.path)
        assert "ffmpeg" in proj.draft.meta and "ffmpeg -y" in proj.draft.meta["ffmpeg"]
        # one image per scene
        assert len(proj.images) == len(proj.scenes)


def test_ffmpeg_command_references_all_inputs():
    opp = run(MockYouTubeProvider(1337)).opportunities[0]
    pkg = build_opportunity(opp)
    with tempfile.TemporaryDirectory() as d:
        proj = build_video(pkg.script, d)
        cmd = proj.draft.meta["ffmpeg"]
        assert cmd.count("-loop 1") == len(proj.images)   # every scene image is an input
        assert proj.voice.path in cmd                     # narration mapped


# -- Phase 7: learning ----------------------------------------------------
def test_bandit_learns_best_arm():
    b = Bandit(seed=1)
    for _ in range(60):
        b.update("good", success=True)
        b.update("bad", success=False)
    picks = [b.choose(["good", "bad"]) for _ in range(50)]
    assert picks.count("good") > picks.count("bad")     # shifts toward the winner
    assert b.ranking()[0][0] == "good"


def test_insights_lift_and_priors():
    exps = [
        {"niche": "ai", "angle": "hands-on", "hook_style": "story", "title_structure": "howto",
         "duration_sec": 480, "publish_hour": 9, "performance": 0.8},
        {"niche": "ai", "angle": "hands-on", "hook_style": "story", "title_structure": "howto",
         "duration_sec": 500, "publish_hour": 9, "performance": 0.9},
        {"niche": "ai", "angle": "listicle", "hook_style": "question", "title_structure": "list",
         "duration_sec": 900, "publish_hour": 20, "performance": 0.2},
    ]
    ins = insights(exps)
    assert ins["n"] == 3 and 0 <= ins["baseline"] <= 1
    top_angle = ins["attributes"]["angle"][0]
    assert top_angle["value"] == "hands-on" and top_angle["lift"] > 0
    priors = niche_priors(exps, "angle")
    a, b = priors["ai"]["hands-on"]
    assert a > b            # winning angle gets a stronger success prior


# -- Phase 8: security ----------------------------------------------------
def test_open_in_dev_mode(monkeypatch):
    monkeypatch.delenv("YOE_API_KEYS", raising=False)
    p = security.authenticate(None)
    assert p.role == "admin" and p.can("editor")


def test_keys_and_rbac(monkeypatch):
    monkeypatch.setenv("YOE_API_KEYS", "vk:viewer,ak:admin")
    viewer = security.authenticate("vk")
    assert viewer.role == "viewer" and not viewer.can("admin")
    admin = security.authenticate("ak")
    assert admin.can("admin")
    with pytest.raises(PermissionError):
        security.authenticate("bogus")
