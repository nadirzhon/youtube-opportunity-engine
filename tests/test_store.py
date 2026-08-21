"""Persistence tests (stdlib sqlite3, in-memory). Run: pytest -q"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import store
from yoe.pipeline import run_from_store
from yoe.providers.mock import MockYouTubeProvider


@pytest.fixture()
def conn():
    c = store.connect(":memory:")
    yield c
    c.close()


def test_collect_persists_entities(conn):
    r = store.collect(conn, MockYouTubeProvider(seed=1337))
    assert r["state"] == "completed"
    assert r["channels"] > 0 and r["videos"] > 0 and r["snapshots"] > 0
    assert conn.execute("SELECT COUNT(*) FROM channels").fetchone()[0] == r["channels"]
    assert conn.execute("SELECT COUNT(*) FROM videos").fetchone()[0] == r["videos"]
    assert store.snapshot_count(conn) == r["snapshots"]


def test_snapshots_idempotent_by_age(conn):
    prov = MockYouTubeProvider(seed=1337)
    store.collect(conn, prov)
    first = store.snapshot_count(conn)
    store.collect(conn, prov)                 # same static data again
    assert store.snapshot_count(conn) == first  # no duplicates
    assert store.run_count(conn) == 2           # but the run is recorded (audit)


def test_engine_runs_on_stored_history(conn):
    store.collect(conn, MockYouTubeProvider(seed=1337))
    report = run_from_store(conn)
    assert report.breakouts
    top = report.opportunities[0]
    assert top.topic == "ai-agents-security"
    assert top.stage.value == "accelerating"


def test_history_series_persisted(conn):
    store.collect(conn, MockYouTubeProvider(seed=1337))
    vids = store.load_videos(conn)
    assert vids
    assert any(len(v.snapshots) >= 3 for v in vids), "time-series history persisted"


def test_stored_run_matches_live_run(conn):
    """Engine output from the DB matches a direct live run — persistence is faithful."""
    from yoe.pipeline import run
    store.collect(conn, MockYouTubeProvider(seed=1337))
    stored_top = run_from_store(conn).opportunities[0]
    live_top = run(MockYouTubeProvider(seed=1337)).opportunities[0]
    assert stored_top.topic == live_top.topic
    assert abs(stored_top.score - live_top.score) < 0.01
