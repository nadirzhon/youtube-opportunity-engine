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
                  stage: str | None = None,
                  rank: str = Query("score", pattern="^(score|profit)$")) -> dict[str, Any]:
    """`rank=profit` sorts by profit priority (growth × estimated niche RPM) and
    attaches an `economics` block (RPM estimate + worth-generating verdict)."""
    from . import economics
    r = _report()
    items = [o.to_dict() for o in r.opportunities
             if o.score >= min_score and (stage is None or o.stage.value == stage)]
    if rank == "profit":
        items = economics.rank_by_profit(items)
    else:
        items = [economics.enrich(o) for o in items]
    return {"count": len(items), "ranked_by": rank, "opportunities": items[:limit]}


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
    from .learning import learned_boost, publication_record
    experience = learned_boost(store.load_experiments(_db(), niche=topic))
    pkg = build_opportunity(opp, source_titles=source_titles, experience=experience)
    # Persist THIS built variant so a later /feedback links the outcome to it
    # (by publication_id) instead of regenerating a fresh package.
    pub_id = store.save_publication(_db(), publication_record(pkg, opportunity=opp))
    out = pkg.to_dict()
    out["publication_id"] = pub_id
    return out


class FeedbackBody(BaseModel):
    performance: float          # 0..1 normalized outcome (e.g. views vs expectation)
    publication_id: int | None = None   # link the result to the exact built variant
    publish_hour: int | None = None
    video_url: str | None = None


@app.post("/feedback/{topic}")
def feedback(topic: str, body: FeedbackBody) -> dict[str, Any]:
    """Report a produced asset's measured performance. Pass `publication_id` (from
    /build) so the outcome links to the EXACT variant you published; without it we
    fall back to rebuilding the package for backward compatibility."""
    from .learning import record_publication, record_result_for_publication
    if body.publication_id is not None:
        eid = record_result_for_publication(
            _db(), body.publication_id, performance=body.performance,
            publish_hour=body.publish_hour, video_url=body.video_url)
    else:
        from .agents import build_opportunity
        r = _report()
        opp = next((o for o in r.opportunities if o.topic == topic), None)
        if opp is None:
            raise HTTPException(404, f"no opportunity for topic '{topic}'")
        pkg = build_opportunity(opp, source_titles=[a.video_id for a in r.breakouts])
        eid = record_publication(_db(), pkg, performance=body.performance,
                                 publish_hour=body.publish_hour, video_url=body.video_url,
                                 opportunity=opp)
    n = store.experiment_count(_db())
    return {"ok": True, "experiment_id": eid, "experiments_recorded": n,
            "topic": topic, "performance": max(0.0, min(1.0, body.performance))}


@app.get("/recommendations")
def recommendations(limit: int = Query(8, ge=1, le=50),
                    with_full_brief: bool = Query(True)) -> dict[str, Any]:
    """The advisor: ranked 'what to do next' actions (launch a channel / make a
    video) with the reasoning and a creative brief (palette + art direction). For
    the #1 pick it attaches the full package — script, hooks, thumbnail
    directions — so you get a ready-to-shoot brief, not just a suggestion."""
    from . import advisor, profiles as prof
    r = _report()
    opps = [o.to_dict() for o in r.opportunities]
    recs = advisor.recommend(opps, profiles=prof.list_profiles(_db()), limit=limit)
    if with_full_brief and recs:
        top = next((o for o in r.opportunities if o.topic == recs[0]["topic"]), None)
        if top is not None:
            from .agents import build_opportunity
            from .learning import learned_boost
            exp = learned_boost(store.load_experiments(_db(), niche=top.topic))
            pkg = build_opportunity(top, source_titles=[a.video_id for a in r.breakouts],
                                    experience=exp)
            recs[0]["full_brief"] = {
                "chosen_title": pkg.chosen.title_hypotheses[0] if pkg.chosen.title_hypotheses else None,
                "hook": pkg.chosen.hook,
                "script": pkg.script.to_dict(),
                "thumbnails": [t.to_dict() for t in pkg.thumbnails],
                "quality": pkg.quality.to_dict(),
            }
    return {"headline": advisor.headline(recs), "count": len(recs),
            "recommendations": recs}


class ProfileBody(BaseModel):
    id: str
    name: str
    niche_keywords: list[str] = []
    category_ids: list[str] = []
    region: str = "US"
    min_rpm: float = 0.0
    notes: str = ""


@app.get("/profiles")
def list_channel_profiles() -> dict[str, Any]:
    from . import profiles
    return {"profiles": [p.to_dict() for p in profiles.list_profiles(_db())]}


@app.put("/profiles")
def upsert_channel_profile(body: ProfileBody) -> dict[str, Any]:
    from . import profiles
    p = profiles.ChannelProfile(**body.model_dump())
    profiles.save_profile(_db(), p)
    return {"ok": True, "profile": p.to_dict()}


@app.delete("/profiles/{profile_id}")
def remove_channel_profile(profile_id: str) -> dict[str, Any]:
    from . import profiles
    profiles.delete_profile(_db(), profile_id)
    return {"ok": True, "deleted": profile_id}


@app.get("/profiles/{profile_id}/feed")
def profile_feed(profile_id: str, limit: int = Query(10, ge=1, le=100)) -> dict[str, Any]:
    """The tailored opportunity shortlist for one channel identity: matched to its
    niche, RPM-floored, ranked by profit priority."""
    from . import profiles
    p = next((p for p in profiles.list_profiles(_db()) if p.id == profile_id), None)
    if p is None:
        raise HTTPException(404, f"no profile '{profile_id}'")
    items = [o.to_dict() for o in _report().opportunities]
    feed = profiles.feed_for(p, items)
    return {"profile": p.to_dict(), "count": len(feed), "feed": feed[:limit]}


@app.get("/backtest")
def backtest(cutoff_hours: float = Query(24, ge=1),
             k: int = Query(3, ge=1, le=50)) -> dict[str, Any]:
    """Validate the score against reality: score the stored world as of
    `cutoff_hours` and grade against realized growth after it. Needs accumulated
    snapshot history (let the worker run) — with a single reading there is no
    'future' to measure and it reports inconclusive."""
    from . import backtest as bt
    from .store import load_channels, load_videos
    channels = load_channels(_db())
    videos = load_videos(_db())
    by_ch: dict[str, list] = {}
    for v in videos:
        by_ch.setdefault(v.channel_id, []).append(v)
    if not channels:
        return {"verdict": "no data — run a scan/collect first.", "n_topics_evaluated": 0}
    return bt.run_backtest(channels, by_ch, cutoff_hours=cutoff_hours, k=k)


@app.get("/calibration")
def scoring_calibration() -> dict[str, Any]:
    """How the opportunity scorer has re-weighted itself from real outcomes:
    per-dimension correlation with performance and the weight shift vs the spec
    priors. With few experiments the weights stay near the priors (regularized)."""
    from .learning import calibration_report
    return calibration_report(store.load_experiments(_db()))


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
