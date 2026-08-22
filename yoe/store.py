"""
Persistence — time-series storage on stdlib sqlite3 (zero dependencies).

The whole point of this layer: preserve **snapshots over time** so velocity and
acceleration come from real history, not a single read. The YouTube Data API
returns current counters only; the collector records a snapshot each run and the
series accumulates.

SQLite by default (file `yoe.db`, or `:memory:` in tests). A SQLAlchemy/Postgres
adapter is a drop-in for scale later — this module is the reference behaviour and
keeps the project dependency-free.

Idempotency: snapshots are unique per (video_id, age_hours), so re-collecting the
same reading upserts instead of duplicating, and distinct ages build the series.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3

from .models import Channel, Video, VideoSnapshot

_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
  channel_id TEXT PRIMARY KEY, title TEXT, subscriber_count INTEGER,
  video_count INTEGER, topics TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS videos (
  video_id TEXT PRIMARY KEY, channel_id TEXT, title TEXT,
  published_hours_ago REAL, duration_sec INTEGER, category TEXT, topics TEXT
);
CREATE TABLE IF NOT EXISTS video_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT, video_id TEXT, run_id INTEGER,
  age_hours REAL, view_count INTEGER, like_count INTEGER, comment_count INTEGER,
  captured_at TEXT,
  UNIQUE(video_id, age_hours)
);
CREATE INDEX IF NOT EXISTS ix_snap_video ON video_snapshots(video_id, age_hours);
CREATE INDEX IF NOT EXISTS ix_video_channel ON videos(channel_id);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
  provider TEXT, state TEXT, channels INTEGER, videos INTEGER,
  snapshots INTEGER, cost_usd REAL
);
CREATE TABLE IF NOT EXISTS experiments (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
  topic TEXT, niche TEXT, angle TEXT, hook_style TEXT, title_structure TEXT,
  title TEXT, duration_sec INTEGER, publish_hour INTEGER,
  performance REAL, video_url TEXT
);
CREATE INDEX IF NOT EXISTS ix_exp_niche ON experiments(niche);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
);
"""


def _url_to_path(url: str | None) -> str:
    url = url or os.environ.get("DATABASE_URL") or "sqlite:///yoe.db"
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        return url[len("sqlite://"):] or ":memory:"
    return url  # already a plain path or :memory:


def connect(url: str | None = None) -> sqlite3.Connection:
    path = _url_to_path(url)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
    conn.row_factory = sqlite3.Row
    if path != ":memory:":
        # WAL + a busy timeout let the API (reader) and worker (writer) share one
        # file safely in a 24/7 deployment without "database is locked" errors.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(_SCHEMA)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Collection — persist a provider's readings, accumulating history.
# ---------------------------------------------------------------------------
def collect(conn: sqlite3.Connection, provider) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    prov = "mock" if getattr(provider, "is_mock", False) else "youtube"
    cur = conn.execute(
        "INSERT INTO runs(started_at, provider, state) VALUES(?,?,?)", (now, prov, "running"))
    run_id = cur.lastrowid

    n_ch = n_vid = n_snap = 0
    for ch in provider.list_channels():
        conn.execute(
            "INSERT INTO channels(channel_id,title,subscriber_count,video_count,topics,updated_at)"
            " VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET"
            " title=excluded.title, subscriber_count=excluded.subscriber_count,"
            " video_count=excluded.video_count, topics=excluded.topics, updated_at=excluded.updated_at",
            (ch.channel_id, ch.title, ch.subscriber_count, ch.video_count, ",".join(ch.topics), now))
        n_ch += 1
        for v in provider.list_videos(ch.channel_id):
            conn.execute(
                "INSERT INTO videos(video_id,channel_id,title,published_hours_ago,duration_sec,category,topics)"
                " VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id) DO UPDATE SET"
                " title=excluded.title, duration_sec=excluded.duration_sec,"
                " category=excluded.category, topics=excluded.topics",
                (v.video_id, v.channel_id, v.title, v.published_hours_ago,
                 v.duration_sec, v.category, ",".join(v.topics)))
            n_vid += 1
            for s in v.snapshots:
                exists = conn.execute(
                    "SELECT 1 FROM video_snapshots WHERE video_id=? AND age_hours=?",
                    (v.video_id, s.at_hours)).fetchone()
                conn.execute(
                    "INSERT INTO video_snapshots(video_id,run_id,age_hours,view_count,like_count,comment_count,captured_at)"
                    " VALUES(?,?,?,?,?,?,?) ON CONFLICT(video_id,age_hours) DO UPDATE SET"
                    " view_count=excluded.view_count, like_count=excluded.like_count,"
                    " comment_count=excluded.comment_count",
                    (v.video_id, run_id, s.at_hours, s.view_count, s.like_count, s.comment_count, now))
                if not exists:
                    n_snap += 1  # count only genuinely new time points

    conn.execute("UPDATE runs SET state=?, finished_at=?, channels=?, videos=?, snapshots=? WHERE id=?",
                 ("completed", dt.datetime.now(dt.timezone.utc).isoformat(), n_ch, n_vid, n_snap, run_id))
    conn.commit()
    return {"run_id": run_id, "provider": prov, "channels": n_ch,
            "videos": n_vid, "snapshots": n_snap, "state": "completed"}


# ---------------------------------------------------------------------------
# Reading — reconstruct domain objects from stored history.
# ---------------------------------------------------------------------------
def load_channels(conn: sqlite3.Connection) -> list[Channel]:
    rows = conn.execute("SELECT * FROM channels").fetchall()
    return [Channel(r["channel_id"], r["title"], r["subscriber_count"], r["video_count"],
                    tuple(t for t in (r["topics"] or "").split(",") if t)) for r in rows]


def load_videos(conn: sqlite3.Connection) -> list[Video]:
    vids = conn.execute("SELECT * FROM videos").fetchall()
    out: list[Video] = []
    for r in vids:
        snaps = conn.execute(
            "SELECT age_hours,view_count,like_count,comment_count FROM video_snapshots"
            " WHERE video_id=? ORDER BY age_hours", (r["video_id"],)).fetchall()
        series = [VideoSnapshot(s["age_hours"], s["view_count"], s["like_count"], s["comment_count"])
                  for s in snaps]
        age = max((s["age_hours"] for s in snaps), default=r["published_hours_ago"])
        out.append(Video(
            video_id=r["video_id"], channel_id=r["channel_id"], title=r["title"],
            published_hours_ago=age, duration_sec=r["duration_sec"], category=r["category"],
            topics=tuple(t for t in (r["topics"] or "").split(",") if t), snapshots=series))
    return out


# ---------------------------------------------------------------------------
# Experiments — the learning loop's memory. Each published asset + its measured
# performance is one row; the learner reads these back to compound over time.
# ---------------------------------------------------------------------------
def save_experiment(conn: sqlite3.Connection, exp: dict) -> int:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    cur = conn.execute(
        "INSERT INTO experiments(created_at,topic,niche,angle,hook_style,title_structure,"
        "title,duration_sec,publish_hour,performance,video_url)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (now, exp.get("topic"), exp.get("niche"), exp.get("angle"),
         exp.get("hook_style"), exp.get("title_structure"), exp.get("title"),
         exp.get("duration_sec"), exp.get("publish_hour"),
         exp.get("performance"), exp.get("video_url")))
    conn.commit()
    return cur.lastrowid


def load_experiments(conn: sqlite3.Connection, niche: str | None = None) -> list[dict]:
    if niche:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE niche=? ORDER BY id", (niche,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM experiments ORDER BY id").fetchall()
    return [dict(r) for r in rows]


def experiment_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]


# ---------------------------------------------------------------------------
# Key/value state — the worker's heartbeat and counters, readable by the API's
# /status so a 24/7 deployment is observable without extra infrastructure.
# ---------------------------------------------------------------------------
def set_state(conn: sqlite3.Connection, key: str, value) -> None:
    import json
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO kv(key,value,updated_at) VALUES(?,?,?)"
        " ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
        (key, json.dumps(value), now))
    conn.commit()


def get_state(conn: sqlite3.Connection, key: str, default=None):
    import json
    row = conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row["value"]) if row else default


def snapshot_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM video_snapshots").fetchone()[0]


def run_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
