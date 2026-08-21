"""
FastAPI layer over the intelligence core.

Exposes the engine as an HTTP API: health, scan, opportunities, breakouts,
topics. The heavy work is `pipeline.run(provider)`; results are cached in memory
and refreshed on demand (a later phase moves this to Postgres + a scheduler).

Run:  uvicorn yoe.api:app --reload
Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from . import config
from .pipeline import EngineReport, run
from .providers.factory import get_provider

app = FastAPI(title="YouTube Opportunity Engine", version="0.2.0")

# In-memory cache of the last engine run (swapped for Postgres in a later phase).
_state: dict[str, Any] = {"report": None, "ran_at": 0.0, "provider": None}


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
    pkg = build_opportunity(opp, source_titles=source_titles)
    return pkg.to_dict()
