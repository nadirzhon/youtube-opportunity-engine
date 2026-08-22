"""
FastAPI layer over the intelligence core.

Exposes the engine as an HTTP API: health, scan, opportunities, breakouts,
topics. The heavy work is `pipeline.run(provider)`; results are cached in memory
and refreshed on demand (a later phase moves this to Postgres + a scheduler).

Run:  uvicorn yoe.api:app --reload
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config, store
from .pipeline import EngineReport, run
from .providers.factory import get_provider

app = FastAPI(title="YouTube Opportunity Engine", version="0.4.0")

_WEB_DIR = os.path.join(os.path.dirname(__file__), "web")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    """Serve the single-file analytics dashboard (same-origin → no CORS needed)."""
    with open(os.path.join(_WEB_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()

# In-memory cache of the last engine run (swapped for Postgres in a later phase).
_state: dict[str, Any] = {"report": None, "ran_at": 0.0, "provider": None, "db": None}


def _db():
    """Lazy shared store connection for the learning loop's experiment memory."""
    if _state["db"] is None:
        _state["db"] = store.connect(os.environ.get("DATABASE_URL"))
    return _state["db"]


class ScanResponse(BaseModel):
    ok: bool
    provider: str
    channels: int
    videos: int
    breakouts: int
    topics: int
    opportunities: int
    ran_at: float


def _run(force_mock: bool = False) -> EngineReport:
    settings = config.load()
    provider = get_provider(settings, force_mock=force_mock)
    report = run(provider)
    _state.update(report=report, ran_at=time.time(),
                  provider="mock" if getattr(provider, "is_mock", False) else "youtube")
    return report


def _report() -> EngineReport:
    if _state["report"] is None:
        _run()
    return _state["report"]


@app.get("/health")
def health() -> dict[str, Any]:
    settings = config.load()
    return {
        "status": "ok",
        "youtube_configured": settings.has_youtube,
        "mode": "youtube" if settings.has_youtube else "mock",
        "last_run": _state["ran_at"],
    }


@app.get("/status")
def status() -> dict[str, Any]:
    """Liveness of the 24/7 worker: heartbeat, cycles, last error, freshness of
    the stored data. A monitor can poll this to alert on a stalled worker."""
    import time as _t
    settings = config.load()
    beat = store.get_state(_db(), "worker")
    stale = None
    if beat and beat.get("last_beat"):
        try:
            last = _dt_parse(beat["last_beat"])
            age = _t.time() - last
            stale = age > 3 * max(60, beat.get("interval_sec", 1800))
            beat["heartbeat_age_sec"] = round(age)
        except Exception:  # noqa: BLE001
            pass
    return {
        "status": "ok",
        "mode": "youtube" if settings.has_youtube else "mock",
        "worker": beat or {"healthy": None, "note": "worker has not run yet"},
        "worker_stale": stale,
        "counts": {
            "channels": _count("channels"), "videos": _count("videos"),
            "snapshots": store.snapshot_count(_db()),
            "experiments": store.experiment_count(_db()),
        },
    }


def _dt_parse(iso: str) -> float:
    import datetime as _d
    return _d.datetime.fromisoformat(iso).timestamp()


def _count(table: str) -> int:
    return _db().execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


@app.post("/scan", response_model=ScanResponse)
def scan(mock: bool = Query(False, description="Force the mock provider")) -> ScanResponse:
    r = _run(force_mock=mock)
    return ScanResponse(
        ok=True, provider=_state["provider"], channels=len(r.channels),
        videos=len(r.videos), breakouts=len(r.breakouts), topics=len(r.topics),
        opportunities=len(r.opportunities), ran_at=_state["ran_at"])


@app.get("/opportunities")
def opportunities(limit: int = Query(20, ge=1, le=200),
                  min_score: float = Query(0, ge=0, le=100),
                  stage: str | None = None) -> dict[str, Any]:
    r = _report()
    items = [o.to_dict() for o in r.opportunities
             if o.score >= min_score and (stage is None or o.stage.value == stage)]
    return {"count": len(items), "opportunities": items[:limit]}


@app.get("/opportunities/{topic}")
def opportunity_detail(topic: str) -> dict[str, Any]:
    r = _report()
    o = next((o for o in r.opportunities if o.topic == topic), None)
    if o is None:
        raise HTTPException(404, f"no opportunity for topic '{topic}'")
    return o.to_dict()


@app.get("/breakouts")
def breakouts(limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
    r = _report()
    return {"count": len(r.breakouts),
            "breakouts": [a.to_dict() for a in r.breakouts[:limit]]}


@app.get("/topics")
def topics() -> dict[str, Any]:
    r = _report()
    return {"count": len(r.topics),
            "topics": [{"topic": t.topic, "stage": t.stage.value,
                        "velocity": t.velocity, "signals": t.signals,
                        "channels": len(t.channel_ids)} for t in r.topics]}


@app.post("/build/{topic}")
def build(topic: str) -> dict[str, Any]:
    """One-click 'Build Opportunity': research → concepts → script → quality gate.

    Returns the full package with every intermediate artifact for inspection.
    Uses the mock LLM until an LLM key is configured.
    """
    from .agents import build_opportunity
    r = _report()
    opp = next((o for o in r.opportunities if o.topic == topic), None)
    if opp is None:
        raise HTTPException(404, f"no opportunity for topic '{topic}'")
    source_titles = [a.video_id for a in r.breakouts]
    # bias concept choice by what has historically worked for this niche
    from .learning import learned_boost
    experience = learned_boost(store.load_experiments(_db(), niche=topic))
    pkg = build_opportunity(opp, source_titles=source_titles, experience=experience)
    return pkg.to_dict()


class FeedbackBody(BaseModel):
    performance: float          # 0..1 normalized outcome (e.g. views vs expectation)
    publish_hour: int | None = None
    video_url: str | None = None


@app.post("/feedback/{topic}")
def feedback(topic: str, body: FeedbackBody) -> dict[str, Any]:
    """Report a produced asset's measured performance. This is the loop closing:
    the outcome is stored as an experiment and biases every future /build."""
    from .agents import build_opportunity
    from .learning import record_publication
    r = _report()
    opp = next((o for o in r.opportunities if o.topic == topic), None)
    if opp is None:
        raise HTTPException(404, f"no opportunity for topic '{topic}'")
    source_titles = [a.video_id for a in r.breakouts]
    pkg = build_opportunity(opp, source_titles=source_titles)
    eid = record_publication(_db(), pkg, performance=body.performance,
                             publish_hour=body.publish_hour, video_url=body.video_url)
    n = store.experiment_count(_db())
    return {"ok": True, "experiment_id": eid, "experiments_recorded": n,
            "topic": topic, "performance": max(0.0, min(1.0, body.performance))}


@app.get("/insights")
def learning_insights() -> dict[str, Any]:
    """What the system has learned so far — feature-importance across recorded
    experiments plus the per-angle learned bias applied to future builds."""
    from .learning import insights, learned_boost
    exps = store.load_experiments(_db())
    ins = insights(exps)
    scorer = learned_boost(exps)
    ins["learned_angle_bias"] = {v: round((a / (a + b)) - 0.5, 3)
                                 for v, (a, b) in scorer.arms.items()}
    return ins
