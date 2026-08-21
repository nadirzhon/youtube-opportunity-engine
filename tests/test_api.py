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
