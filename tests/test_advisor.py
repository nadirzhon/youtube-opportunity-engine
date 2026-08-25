"""Tests for the advisor (action recommendations) and brand (visual style)."""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import advisor, brand
from yoe.profiles import ChannelProfile


_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")


# -- brand / palette ------------------------------------------------------
def test_palette_is_niche_specific_and_valid_hex():
    fin = brand.palette_for("stock investing")
    game = brand.palette_for("ps5 gaming setup")
    assert fin["niche_bucket"] == "personal_finance"
    assert game["niche_bucket"] == "gaming"
    assert fin != game                                  # different niches → different look
    for key in ("primary", "secondary", "accent", "background", "text"):
        assert _HEX.match(fin[key]), f"{key} not a hex color"
    assert len(fin["swatches"]) == 5


def test_style_brief_has_palette_and_direction():
    b = brand.style_brief("ai agents tutorial")
    assert "palette" in b and b["art_direction"]
    assert b["palette"]["niche_bucket"] == "ai_tools"


# -- advisor --------------------------------------------------------------
_OPPS = [
    {"topic": "stock investing 2025", "score": 62.0, "confidence": 0.9,
     "stage": "accelerating", "evidence": ["4 channels active"]},
    {"topic": "ps5 gaming setup", "score": 82.0, "confidence": 1.0,
     "stage": "emerging", "evidence": []},
    {"topic": "random tiny thing", "score": 20.0, "confidence": 0.3, "stage": "latent"},
]


def test_recommends_launch_channel_for_uncovered_niche():
    recs = advisor.recommend(_OPPS, profiles=[])
    top = recs[0]
    assert top["action"] == "launch_channel"           # no profiles yet → greenfield
    assert top["brief"]["palette"]["niche_bucket"] == top["niche_bucket"]
    assert any("RPM" in w for w in top["why"])


def test_make_video_when_a_profile_covers_the_niche():
    finance = ChannelProfile("fin", "Money", niche_keywords=["invest", "stock"])
    recs = advisor.recommend(_OPPS, profiles=[finance])
    fin_rec = next(r for r in recs if "investing" in r["topic"])
    assert fin_rec["action"] == "make_video"
    assert fin_rec["covered_by_profile"] == "fin"


def test_low_priority_items_are_dropped():
    recs = advisor.recommend(_OPPS, profiles=[], min_priority=20.0)
    assert all(r["profit_priority"] >= 20.0 for r in recs)
    assert not any(r["topic"] == "random tiny thing" for r in recs)


def test_headline_is_actionable():
    recs = advisor.recommend(_OPPS, profiles=[])
    h = advisor.headline(recs)
    assert any(v in h for v in ("Launch", "Make", "Double"))
    assert advisor.headline([]).startswith("Nothing actionable")
