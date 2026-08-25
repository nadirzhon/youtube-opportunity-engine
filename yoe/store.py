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
  performance REAL, video_url TEXT, dimensions TEXT
);
CREATE INDEX IF NOT EXISTS ix_exp_niche ON experiments(niche);
CREATE TABLE IF NOT EXISTS publications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT,
  topic TEXT, niche TEXT, angle TEXT, hook_style TEXT, title_structure TEXT,
  title TEXT, duration_sec INTEGER, dimensions TEXT, video_url TEXT
);
CREATE TABLE IF NOT EXISTS kv (
  key TEXT PRIMARY KEY, value TEXT, updated_at TEXT
);
"""


def _resolve_url(url: str | None) -> str:
    return url or os.environ.get("DATABASE_URL") or "sqlite:///yoe.db"


def _is_postgres(url: str) -> bool:
    return url.startswith(("postgres://", "postgresql://"))


def _url_to_path(url: str | None) -> str:
    url = _resolve_url(url)
    if url.startswith("sqlite:///"):
        return url[len("sqlite:///"):]
    if url.startswith("sqlite://"):
        return url[len("sqlite://"):] or ":memory:"
    return url  # already a plain path or :memory:


# ---------------------------------------------------------------------------
# Postgres adapter — a thin wrapper that presents the exact sqlite3 surface the
# rest of this module uses (execute/executescript/commit/close, cursor.lastrowid,
# rows addressable by both name and index). Same code, same SQL, other engine.
# Postgres is the multi-host / high-concurrency option; sqlite stays the default.
# ---------------------------------------------------------------------------
def _pg_translate_ddl(script: str) -> list[str]:
    """sqlite schema → Postgres: autoincrement PK becomes BIGSERIAL. Everything
    else in our schema (IF NOT EXISTS, ON CONFLICT ... excluded, UNIQUE, REAL) is
    already valid Postgres. Returns individual statements (psycopg runs one/exec)."""
    script = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    return [s.strip() for s in script.split(";") if s.strip()]


class _PgRow(dict):
    """Row addressable by column name (like sqlite3.Row) AND by position."""
    def __init__(self, cols, values):
        super().__init__(zip(cols, values))
        self._v = tuple(values)

    def __getitem__(self, k):
        return self._v[k] if isinstance(k, int) else dict.__getitem__(self, k)


def _pg_row_factory(cursor):
    cols = [c.name for c in cursor.description] if cursor.description else []
    def make(values):
        return _PgRow(cols, values)
    return make


class _PgCursor:
    def __init__(self, raw, conn):
        self._raw, self._conn = raw, conn

    def fetchone(self):
        return self._raw.fetchone()

    def fetchall(self):
        return self._raw.fetchall()

    @property
    def lastrowid(self):
        with self._conn._pg.cursor() as c:
            c.execute("SELECT lastval()")
            row = c.fetchone()
            return row[0] if row else None


class _PgConnection:
    """Presents the sqlite3.Connection surface over a psycopg connection."""
    def __init__(self, pg):
        self._pg = pg
        self._pg.autocommit = True   # mirror sqlite's per-statement durability

    def execute(self, sql, params=()):
        cur = self._pg.cursor(row_factory=_pg_row_factory)
        cur.execute(sql.replace("?", "%s"), tuple(params))
        return _PgCursor(cur, self)

    def executescript(self, script):
        with self._pg.cursor() as cur:
            for stmt in _pg_translate_ddl(script):
                cur.execute(stmt)

    def commit(self):
        pass  # autocommit on

    def close(self):
        self._pg.close()

    def __getattr__(self, name):
        return getattr(self._pg, name)


def _connect_postgres(url: str):
    import psycopg  # lazy: only when a Postgres URL is configured
    conn = _PgConnection(psycopg.connect(url))
    conn.executescript(_SCHEMA)
    return conn


def connect(url: str | None = None):
    resolved = _resolve_url(url)
    if _is_postgres(resolved):
        return _connect_postgres(resolved)

    path = _url_to_path(resolved)
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


def init_db(conn) -> None:
    conn.executescript(_SCHEMA)


# ---------------------------------------------------------------------------
# Collection — persist a provider's readings, accumulating history.
# ---------------------------------------------------------------------------
def _channel_cadence_hours(min_age: float) -> float:
    """How long before a channel is worth re-fetching, from its youngest video's
    age (the scheduler's adaptive rule): fresh channels often, mature rarely."""
    from .scheduler import sampling_priority
    return {"high": 1.0, "medium": 6.0, "low": 24.0}[sampling_priority(min_age)]


def collect(conn: sqlite3.Connection, provider, *, adaptive: bool = False,
            now_dt: dt.datetime | None = None) -> dict:
    """Persist a provider's readings. With `adaptive=True`, channels not yet due
    (per their maturity-based cadence) are skipped — so mature channels aren't
    re-fetched every cycle, saving real API quota. Due-times persist in kv."""
    now_dt = now_dt or dt.datetime.now(dt.timezone.utc)
    now = now_dt.isoformat()
    prov = "mock" if getattr(provider, "is_mock", False) else "youtube"
    cur = conn.execute(
        "INSERT INTO runs(started_at, provider, state) VALUES(?,?,?)", (now, prov, "running"))
    run_id = cur.lastrowid

    next_due = get_state(conn, "channel_next_due", {}) or {}

    n_ch = n_vid = n_snap = n_skipped = 0
    for ch in provider.list_channels():
        conn.execute(
            "INSERT INTO channels(channel_id,title,subscriber_count,video_count,topics,updated_at)"
            " VALUES(?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET"
            " title=excluded.title, subscriber_count=excluded.subscriber_count,"
            " video_count=excluded.video_count, topics=excluded.topics, updated_at=excluded.updated_at",
            (ch.channel_id, ch.title, ch.subscriber_count, ch.video_count, ",".join(ch.topics), now))
        # Adaptive skip: not due yet → don't spend quota fetching its videos.
        due_at = next_due.get(ch.channel_id)
        if adaptive and due_at and now < due_at:
            n_skipped += 1
            continue
        vids = provider.list_videos(ch.channel_id)
        n_ch += 1
        min_age = min((v.published_hours_ago for v in vids), default=999.0)
        next_due[ch.channel_id] = (now_dt + dt.timedelta(
            hours=_channel_cadence_hours(min_age))).isoformat()
        for v in vids:
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

    set_state(conn, "channel_next_due", next_due)
    conn.execute("UPDATE runs SET state=?, finished_at=?, channels=?, videos=?, snapshots=? WHERE id=?",
                 ("completed", dt.datetime.now(dt.timezone.utc).isoformat(), n_ch, n_vid, n_snap, run_id))
    conn.commit()
    return {"run_id": run_id, "provider": prov, "channels": n_ch,
            "videos": n_vid, "snapshots": n_snap, "skipped_channels": n_skipped,
            "state": "completed"}


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
    import json
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    dims = exp.get("dimensions")
    cur = conn.execute(
        "INSERT INTO experiments(created_at,topic,niche,angle,hook_style,title_structure,"
        "title,duration_sec,publish_hour,performance,video_url,dimensions)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (now, exp.get("topic"), exp.get("niche"), exp.get("angle"),
         exp.get("hook_style"), exp.get("title_structure"), exp.get("title"),
         exp.get("duration_sec"), exp.get("publish_hour"),
         exp.get("performance"), exp.get("video_url"),
         json.dumps(dims) if dims else None))
    conn.commit()
    return cur.lastrowid


def load_experiments(conn: sqlite3.Connection, niche: str | None = None) -> list[dict]:
    import json
    if niche:
        rows = conn.execute(
            "SELECT * FROM experiments WHERE niche=? ORDER BY id", (niche,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM experiments ORDER BY id").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("dimensions"):
            try:
                d["dimensions"] = json.loads(d["dimensions"])
            except (ValueError, TypeError):
                d["dimensions"] = None
        out.append(d)
    return out


def experiment_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0]


# ---------------------------------------------------------------------------
# Publications — the actual built-and-published variant, stored so a later
# performance report links to THIS content (not a fresh regeneration).
# ---------------------------------------------------------------------------
def save_publication(conn: sqlite3.Connection, pub: dict) -> int:
    import json
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    dims = pub.get("dimensions")
    cur = conn.execute(
        "INSERT INTO publications(created_at,topic,niche,angle,hook_style,title_structure,"
        "title,duration_sec,dimensions,video_url) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (now, pub.get("topic"), pub.get("niche"), pub.get("angle"),
         pub.get("hook_style"), pub.get("title_structure"), pub.get("title"),
         pub.get("duration_sec"), json.dumps(dims) if dims else None, pub.get("video_url")))
    conn.commit()
    return cur.lastrowid


def get_publication(conn: sqlite3.Connection, pub_id: int) -> dict | None:
    import json
    row = conn.execute("SELECT * FROM publications WHERE id=?", (pub_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    if d.get("dimensions"):
        try:
            d["dimensions"] = json.loads(d["dimensions"])
        except (ValueError, TypeError):
            d["dimensions"] = None
    return d


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
