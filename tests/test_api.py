"""API tests via FastAPI TestClient (in-process, no network). Run: pytest -q"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from yoe.api import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # no key configured in tests → mock mode
    assert body["mode"] == "mock"


def test_scan_returns_counts():
    r = client.post("/scan?mock=true")
    assert r.status_code == 200
    b = r.json()
    assert b["ok"] and b["provider"] == "mock"
    assert b["channels"] > 0 and b["videos"] > 0
    assert b["breakouts"] > 0 and b["opportunities"] > 0


def test_opportunities_endpoint_and_planted_trend_on_top():
    client.post("/scan?mock=true")
    r = client.get("/opportunities?limit=5")
    assert r.status_code == 200
    items = r.json()["opportunities"]
    assert items, "should return opportunities"
    top = items[0]
    assert top["topic"] == "ai-agents-security"
    assert top["stage"] == "accelerating"
    assert 0 <= top["score"] <= 100
    assert "breakdown" in top and "reasons_against" in top


def test_opportunities_filtering():
    client.post("/scan?mock=true")
    r = client.get("/opportunities?min_score=70")
    assert r.status_code == 200
    for o in r.json()["opportunities"]:
        assert o["score"] >= 70


def test_opportunity_detail_and_404():
    client.post("/scan?mock=true")
    ok = client.get("/opportunities/ai-agents-security")
    assert ok.status_code == 200
    assert ok.json()["topic"] == "ai-agents-security"
    missing = client.get("/opportunities/does-not-exist")
    assert missing.status_code == 404


def test_breakouts_and_topics():
    client.post("/scan?mock=true")
    b = client.get("/breakouts")
    assert b.status_code == 200 and b.json()["count"] > 0
    t = client.get("/topics")
    assert t.status_code == 200 and t.json()["count"] > 0


def test_build_returns_thumbnails():
    client.post("/scan?mock=true")
    r = client.post("/build/ai-agents-security")
    assert r.status_code == 200
    b = r.json()
    assert len(b["thumbnails"]) == 5
    assert b["thumbnails"][0]["accepted"]           # best pick is honest
    assert "overlay_text" in b["thumbnails"][0]


def test_status_reports_worker_and_counts():
    client.post("/scan?mock=true")
    r = client.get("/status")
    assert r.status_code == 200
    s = r.json()
    assert s["status"] == "ok" and "worker" in s
    assert set(s["counts"]) >= {"channels", "videos", "snapshots", "experiments"}


def test_feedback_and_insights_loop():
    client.post("/scan?mock=true")
    before = client.get("/insights").json()["n"]
    fb = client.post("/feedback/ai-agents-security",
                     json={"performance": 0.8, "publish_hour": 9})
    assert fb.status_code == 200 and fb.json()["ok"]
    after = client.get("/insights").json()
    assert after["n"] == before + 1                 # experiment was remembered
    assert "learned_angle_bias" in after
    # unknown topic → 404
    assert client.post("/feedback/nope", json={"performance": 0.5}).status_code == 404
