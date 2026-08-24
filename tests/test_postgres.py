"""
Postgres adapter tests.

The DDL-translation test always runs (pure function). The full round-trip runs
only when YOE_TEST_PG_URL points at a reachable Postgres — otherwise it's skipped,
so the suite stays green on machines without a database. Locally it was verified
against postgres:16.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import store
from yoe.providers.mock import MockYouTubeProvider


def test_ddl_translation_is_postgres_valid():
    stmts = store._pg_translate_ddl(store._SCHEMA)
    joined = "\n".join(stmts)
    assert "AUTOINCREMENT" not in joined              # sqlite-only, must be gone
    assert "BIGSERIAL PRIMARY KEY" in joined          # became Postgres serial
    assert all(";" not in s for s in stmts)           # split into single statements
    assert any(s.startswith("CREATE TABLE") for s in stmts)


def test_url_scheme_detection():
    assert store._is_postgres("postgresql://u:p@h/db")
    assert store._is_postgres("postgres://u:p@h/db")
    assert not store._is_postgres("sqlite:///yoe.db")
    assert not store._is_postgres("/tmp/x.db")


_PG_URL = os.environ.get("YOE_TEST_PG_URL")
pg = pytest.mark.skipif(not _PG_URL, reason="set YOE_TEST_PG_URL to run Postgres tests")


@pg
def test_postgres_full_roundtrip():
    conn = store.connect(_PG_URL)
    # clean slate — the schema uses IF NOT EXISTS, so wipe rows between runs
    for t in ("video_snapshots", "videos", "channels", "runs", "experiments", "kv"):
        conn.execute(f"DELETE FROM {t}")

    r1 = store.collect(conn, MockYouTubeProvider(1337))
    assert r1["channels"] > 0 and r1["snapshots"] > 0
    r2 = store.collect(conn, MockYouTubeProvider(1337))
    assert r2["snapshots"] == 0                       # ON CONFLICT idempotency on PG

    from yoe.pipeline import run_from_store
    rep = run_from_store(conn, calibrate=False)
    assert rep.opportunities and rep.opportunities[0].topic == "ai-agents-security"

    eid = store.save_experiment(conn, {"niche": "ai", "performance": 0.8,
                                       "dimensions": {"anomaly_strength": 0.9}})
    assert eid and store.experiment_count(conn) == 1
    assert store.load_experiments(conn)[0]["dimensions"] == {"anomaly_strength": 0.9}

    store.set_state(conn, "worker", {"healthy": True, "cycles": 5})
    assert store.get_state(conn, "worker")["cycles"] == 5
    conn.close()
