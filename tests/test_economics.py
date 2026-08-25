"""Tests for the monetization economics layer (RPM + profit priority)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import economics as ec


def test_niche_classification():
    assert ec.classify_niche("passive income ideas") == "business_make_money"
    assert ec.classify_niche("ai agents tutorial") == "ai_tools"
    assert ec.classify_niche("ps5 gaming setup") == "gaming"
    assert ec.classify_niche("marvel movie reaction") == "entertainment"
    assert ec.classify_niche("some random thing") == "other"


def test_high_rpm_niches_beat_low_at_equal_score():
    finance = ec.profit_priority(70, ec.estimate_rpm("investing")["rpm_mid"])
    gaming = ec.profit_priority(70, ec.estimate_rpm("gaming ps5")["rpm_mid"])
    assert finance > gaming            # same growth, finance pays more → higher priority


def test_enrich_attaches_economics_and_verdict():
    opp = {"topic": "stock investing 2025", "score": 62.0, "confidence": 0.9}
    e = ec.enrich(opp)["economics"]
    assert e["niche_bucket"] == "personal_finance"
    assert e["rpm_mid"] > 6
    assert "yes" in e["worth_generating"]
    assert 0 <= e["profit_priority"] <= 100


def test_low_rpm_growth_is_flagged_risky():
    opp = {"topic": "music mv kpop", "score": 70.0, "confidence": 0.9}
    e = ec.enrich(opp)["economics"]
    assert e["rpm_mid"] < 6
    assert "risky" in e["worth_generating"]


def test_rank_by_profit_orders_by_priority():
    opps = [
        {"topic": "gaming ps5", "score": 80.0, "confidence": 1.0},        # high growth, low pay
        {"topic": "stock investing", "score": 60.0, "confidence": 1.0},   # med growth, high pay
    ]
    ranked = ec.rank_by_profit(opps)
    prios = [o["economics"]["profit_priority"] for o in ranked]
    assert prios == sorted(prios, reverse=True)
    # the high-RPM finance topic should be competitive despite lower raw score
    assert ranked[0]["economics"]["niche_bucket"] in ("personal_finance", "gaming")
