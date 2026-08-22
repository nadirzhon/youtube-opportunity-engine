"""Tests for the 24/7 worker: cycle, heartbeat, error isolation, graceful stop."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import config, store
from yoe.worker import Worker


def _settings(**kw):
    base = dict(worker_interval_sec=5, worker_auto_build=False, worker_min_opp_score=60)
    base.update(kw)
    return config.Settings(**base)


def test_single_cycle_collects_analyzes_and_heartbeats():
    conn = store.connect(":memory:")
    w = Worker(_settings(), conn=conn)
    summary = w.run_cycle()
    assert summary["provider"] == "mock"
    assert summary["collected"]["channels"] > 0
    assert summary["opportunities"] and summary["opportunities"][0]["topic"] == "ai-agents-security"
    beat = store.get_state(conn, "worker")
    assert beat["healthy"] and beat["cycles"] == 1 and beat["errors"] == 0
    conn.close()


def test_auto_build_when_enabled():
    conn = store.connect(":memory:")
    w = Worker(_settings(worker_auto_build=True), conn=conn)
    s = w.run_cycle()
    assert s["auto_built"] and s["auto_built"]["quality_passed"] is True
    assert store.experiment_count(conn) == 0   # auto-build creates a package, not an experiment
    conn.close()


def test_history_accumulates_across_cycles():
    conn = store.connect(":memory:")
    w = Worker(_settings(), conn=conn)
    w._sleep = lambda s: None                  # don't wait the real interval in tests
    w.run_forever(install_signals=False, max_cycles=3)
    assert w._cycles == 3 and w._errors == 0
    assert store.snapshot_count(conn) > 0
    conn.close()


def test_loop_survives_a_failing_cycle_and_backs_off():
    """A cycle that raises must not kill the loop; it increments errors, writes an
    unhealthy heartbeat, and backs off exponentially — then recovery works."""
    conn = store.connect(":memory:")
    w = Worker(_settings(), conn=conn)

    calls = {"n": 0}
    real_cycle = w.run_cycle

    def flaky_cycle():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise RuntimeError("boom")
        return real_cycle()

    backoffs: list[float] = []
    w.run_cycle = flaky_cycle
    w._sleep = lambda s: (backoffs.append(s),
                          setattr(w, "_stop", len(backoffs) >= 3) or None)[1]

    w.run_forever(install_signals=False)

    assert w._errors == 2                      # two failures absorbed, loop lived
    assert backoffs[0] < backoffs[1]           # exponential growth
    beat = store.get_state(conn, "worker")
    # after the two failures a successful cycle ran (calls["n"] == 3)
    assert calls["n"] >= 3 and beat["healthy"] is True
    conn.close()


def test_quota_resets_on_utc_day_rollover():
    """A long-lived worker must reset the daily quota at the day boundary, or it
    skips collection forever once day 1's quota is spent."""
    import datetime as dt
    conn = store.connect(":memory:")
    w = Worker(_settings(), conn=conn)
    w.quota.quota_used = 9999            # pretend today's quota is nearly spent
    w._quota_day = dt.date(2000, 1, 1)   # force a stale "current day"
    w._maybe_roll_quota_day()            # today != 2000-01-01 → must reset
    assert w.quota.quota_used == 0
    assert w._quota_day == dt.datetime.now(dt.timezone.utc).date()
    conn.close()


def test_request_stop_ends_the_loop():
    conn = store.connect(":memory:")
    w = Worker(_settings(), conn=conn)
    w.request_stop()
    w.run_forever(install_signals=False)       # already asked to stop → no cycles
    assert w._cycles == 0
    conn.close()
