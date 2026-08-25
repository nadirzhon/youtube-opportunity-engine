"""Tests for multi-channel profiles."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import profiles, store
from yoe.profiles import ChannelProfile


_OPPS = [
    {"topic": "stock investing 2025", "score": 60.0, "confidence": 0.9},
    {"topic": "ai agents for coding", "score": 66.0, "confidence": 0.9},
    {"topic": "ps5 gaming setup", "score": 80.0, "confidence": 1.0},
    {"topic": "cat compilation", "score": 75.0, "confidence": 1.0},
]


def test_profile_matches_its_niche():
    p = ChannelProfile("finance", "Money Channel", niche_keywords=["invest", "stock", "money"])
    assert p.matches("stock investing 2025")
    assert not p.matches("ps5 gaming setup")
    # catch-all profile matches anything
    assert ChannelProfile("all", "All").matches("anything")


def test_feed_filters_to_niche_and_rpm_floor():
    p = ChannelProfile("finance", "Money", niche_keywords=["invest", "stock"], min_rpm=6.0)
    feed = profiles.feed_for(p, _OPPS)
    topics = [o["topic"] for o in feed]
    assert topics == ["stock investing 2025"]          # only the matching, well-paid niche
    assert feed[0]["economics"]["profit_priority"] > 0


def test_feed_rpm_floor_excludes_low_pay():
    p = ChannelProfile("gaming", "Gamer", niche_keywords=["ps5", "gaming"], min_rpm=6.0)
    # gaming RPM (~3.5) is below the 6.0 floor → nothing survives
    assert profiles.feed_for(p, _OPPS) == []


def test_feed_ranks_by_profit_priority():
    p = ChannelProfile("broad", "Broad")   # catch-all
    feed = profiles.feed_for(p, _OPPS)
    prios = [o["economics"]["profit_priority"] for o in feed]
    assert prios == sorted(prios, reverse=True)


def test_profile_persistence_roundtrip():
    conn = store.connect(":memory:")
    profiles.save_profile(conn, ChannelProfile("a", "Alpha", niche_keywords=["ai"]))
    profiles.save_profile(conn, ChannelProfile("b", "Beta", category_ids=["28"]))
    got = {p.id: p for p in profiles.list_profiles(conn)}
    assert set(got) == {"a", "b"} and got["a"].niche_keywords == ["ai"]
    # upsert overwrites, delete removes
    profiles.save_profile(conn, ChannelProfile("a", "Alpha2"))
    assert next(p for p in profiles.list_profiles(conn) if p.id == "a").name == "Alpha2"
    profiles.delete_profile(conn, "a")
    assert {p.id for p in profiles.list_profiles(conn)} == {"b"}
    conn.close()


def test_all_categories_union():
    ps = [ChannelProfile("a", "A", category_ids=["28", "27"]),
          ChannelProfile("b", "B", category_ids=["27", "20"])]
    assert profiles.all_categories(ps) == ("28", "27", "20")
