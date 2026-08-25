"""Tests for autonomous discovery (parsing + watch-set growth, no network)."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import discovery


class _FakeVideos:
    def __init__(self, by_call):
        self._by_call = by_call
        self._i = 0

    def list(self, **params):
        payload = self._by_call[self._i]
        self._i += 1
        class _R:
            def execute(_self):
                return payload
        return _R()


class _FakeService:
    def __init__(self, by_call):
        self._videos = _FakeVideos(by_call)

    def videos(self):
        return self._videos


def _item(ch, vid="v"):
    return {"id": vid, "snippet": {"channelId": ch, "title": f"{vid} by {ch}"}}


def test_channel_ids_dedup_and_order():
    items = [_item("A"), _item("B"), _item("A"), _item("C")]
    assert discovery.channel_ids_from_items(items) == ["A", "B", "C"]


def test_fetch_trending_spans_categories():
    # two categories → two calls, channels harvested from both
    svc = _FakeService([
        {"items": [_item("A", "1"), _item("B", "2")]},
        {"items": [_item("C", "3"), _item("A", "4")]},
    ])
    items = discovery.fetch_trending(svc, category_ids=(None, "28"), per_category=5)
    assert len(items) == 4
    assert discovery.channel_ids_from_items(items) == ["A", "B", "C"]


def test_fetch_trending_survives_a_bad_category():
    class _Boom(_FakeService):
        def videos(self):
            class _V:
                def list(_s, **k):
                    class _R:
                        def execute(__s):
                            raise RuntimeError("bad category")
                    return _R()
            return _V()
    # a failing category must not sink the whole discovery pass
    assert discovery.fetch_trending(_Boom([]), category_ids=(None,)) == []


def test_discover_channels_uses_injected_service_and_caps():
    svc = _FakeService([{"items": [_item(f"C{i}") for i in range(10)]}])
    chans = discovery.discover_channels("key", category_ids=(None,), max_channels=4, service=svc)
    assert chans == ["C0", "C1", "C2", "C3"]


def test_merge_watch_set_unions_and_caps():
    merged = discovery.merge_watch_set(["A", "B"], ["B", "C", "D"], cap=3)
    assert merged == ["A", "B", "C"]          # order-stable union, capped
    assert discovery.merge_watch_set([], ["X"]) == ["X"]


def _vitem(ch, views, published):
    return {"snippet": {"channelId": ch, "publishedAt": published},
            "statistics": {"viewCount": str(views)}}


def test_velocity_ranks_fast_gainers_over_big_slow_ones():
    import datetime as dt
    now = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
    items = [
        # SMALL fast: 100k views in ~1h → very high velocity
        _vitem("small", 100_000, "2026-01-02T23:00:00+00:00".replace("2026-01-02T23", "2026-01-01T23")),
        # BIG slow: 1M views but over ~24h → lower velocity
        _vitem("big", 1_000_000, "2026-01-01T02:00:00+00:00"),
    ]
    ranked = discovery.channel_ids_by_velocity(items, now)
    assert ranked[0] == "small"               # speed beats size


def test_discover_channels_velocity_first_uses_injected_now():
    import datetime as dt
    now = dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
    svc = _FakeService([{"items": [
        _vitem("A", 10_000, "2026-01-01T22:00:00+00:00"),     # ~28h → slow
        _vitem("B", 50_000, "2026-01-02T00:00:00+00:00"),     # ~26h but more → faster
    ]}])
    chans = discovery.discover_channels("k", category_ids=(None,), service=svc,
                                        velocity_first=True, now=now)
    assert chans[0] == "B"
