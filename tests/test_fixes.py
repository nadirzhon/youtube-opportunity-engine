"""Tests for the three architectural fixes: adaptive scheduler, persistent quota,
publication-linked feedback."""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import config, store
from yoe.providers.mock import MockYouTubeProvider
from yoe.quota import QuotaManager
from yoe.scheduler import tick
from yoe.worker import Worker


# -- 1. adaptive scheduler actually skips work ----------------------------
def test_adaptive_collect_skips_channels_not_due():
    conn = store.connect(":memory:")
    p = MockYouTubeProvider(1337)
    t0 = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
    first = store.collect(conn, p, adaptive=True, now_dt=t0)
    assert first["channels"] > 0 and first["skipped_channels"] == 0
    # a minute later: mature channels aren't due yet → skipped, quota saved
    second = store.collect(conn, p, adaptive=True, now_dt=t0 + dt.timedelta(minutes=1))
    assert second["skipped_channels"] > 0
    assert second["channels"] < first["channels"]
    conn.close()


def test_non_adaptive_still_collects_everything():
    conn = store.connect(":memory:")
    p = MockYouTubeProvider(1337)
    a = store.collect(conn, p)                 # default adaptive=False
    b = store.collect(conn, p)
    assert a["channels"] == b["channels"]      # unchanged legacy behaviour
    conn.close()


def test_tick_charges_only_for_fetched_channels():
    conn = store.connect(":memory:")
    p = MockYouTubeProvider(1337)
    q = QuotaManager(daily_quota=100000)
    tick(conn, p, q, adaptive=True)
    used_after_full = q.quota_used
    # second tick right away: channels not due → far less quota spent
    before = q.quota_used
    tick(conn, p, q, adaptive=True)
    assert q.quota_used - before < used_after_full
    conn.close()


# -- 2. quota persists across worker (process) restarts -------------------
def test_quota_survives_a_fresh_worker_on_same_db():
    conn = store.connect(":memory:")
    s = config.Settings(worker_interval_sec=5, youtube_daily_quota=100000)
    w1 = Worker(s, conn=conn)
    w1.run_cycle()
    spent = w1.quota.quota_used
    assert spent > 0
    # a brand-new Worker (like the next GitHub Action run) on the same DB must
    # restore the accumulated quota, not start from zero
    w2 = Worker(s, conn=conn)
    assert w2.quota.quota_used == spent
    conn.close()


# -- 3. feedback links to the exact published variant ---------------------
def test_feedback_links_to_stored_publication():
    conn = store.connect(":memory:")
    pub_id = store.save_publication(conn, {
        "topic": "ai-agents", "niche": "ai-agents", "angle": "hands-on",
        "hook_style": "story", "title_structure": "howto", "title": "Real title",
        "duration_sec": 480, "dimensions": {"momentum": 0.7}})
    assert pub_id > 0

    from yoe.learning import record_result_for_publication
    eid = record_result_for_publication(conn, pub_id, performance=0.82, publish_hour=9)
    exps = store.load_experiments(conn)
    assert len(exps) == 1
    e = exps[0]
    # the recorded experiment carries the EXACT stored variant, not a regeneration
    assert e["title"] == "Real title" and e["angle"] == "hands-on"
    assert e["performance"] == 0.82 and e["dimensions"] == {"momentum": 0.7}
    conn.close()
