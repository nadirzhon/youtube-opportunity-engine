"""
Autonomous discovery — the system finds *what to watch* by itself.

The whole point: you connect an API key and the engine populates its own universe
— no hand-fed channel list. It pulls YouTube's live "most popular" charts (which
need no seed and cost 1 quota unit), harvests the channels behind those videos,
and can expand outward from there. The worker persists the growing watch set, so
each day it monitors more of the landscape on its own.

Two discovery modes:
  * trending  — `videos.list(chart=mostPopular)`, optionally per category/region.
                Zero seed, cheap, always available.
  * search    — `search.list(q=…, order=viewCount, publishedAfter=…)` to expand
                into a niche once one is found (100 units/call — used sparingly).

Parsing is split from fetching so the logic is unit-testable without a network.
"""

from __future__ import annotations

import datetime as dt

# A spread of categories worth scanning for opportunities (YouTube category IDs).
# None = overall trending. Tech/Science, Education, Howto, Gaming, Entertainment.
DEFAULT_CATEGORIES: tuple[str | None, ...] = (None, "28", "27", "26", "20", "24")


def _service(api_key: str):
    from googleapiclient.discovery import build  # lazy import
    return build("youtube", "v3", developerKey=api_key, cache_discovery=False)


def channel_ids_from_items(items: list[dict]) -> list[str]:
    """Ordered, de-duplicated channel ids behind a set of video items."""
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        ch = (it.get("snippet") or {}).get("channelId")
        if ch and ch not in seen:
            seen.add(ch)
            out.append(ch)
    return out


def _age_hours(iso: str, now: dt.datetime) -> float:
    if not iso:
        return 1e9
    try:
        published = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 1e9
    return max(1.0, (now - published).total_seconds() / 3600.0)


def video_velocity(item: dict, now: dt.datetime) -> float:
    """Views gained per hour since publish — speed, not size. This is the signal
    the user wants: who racked up views fastest, regardless of subscriber count."""
    stats = item.get("statistics") or {}
    views = int(stats.get("viewCount", 0) or 0)
    age = _age_hours((item.get("snippet") or {}).get("publishedAt", ""), now)
    return views / age


def channel_ids_by_velocity(items: list[dict], now: dt.datetime) -> list[str]:
    """Channel ids ranked by the fastest-accelerating video they own — so small
    channels with a video exploding right now outrank big channels coasting."""
    best: dict[str, float] = {}
    for it in items:
        ch = (it.get("snippet") or {}).get("channelId")
        if not ch:
            continue
        best[ch] = max(best.get(ch, 0.0), video_velocity(it, now))
    return [ch for ch, _ in sorted(best.items(), key=lambda kv: kv[1], reverse=True)]


def fetch_trending(service, *, region: str = "US",
                   category_ids=DEFAULT_CATEGORIES, per_category: int = 30) -> list[dict]:
    """Raw trending video items across the given categories (1 unit per call)."""
    items: list[dict] = []
    for cat in category_ids:
        params = dict(part="snippet,statistics", chart="mostPopular",
                      regionCode=region, maxResults=per_category)
        if cat:
            params["videoCategoryId"] = str(cat)
        try:
            resp = service.videos().list(**params).execute()
        except Exception:  # noqa: BLE001 — a bad category shouldn't sink discovery
            continue
        items.extend(resp.get("items", []))
    return items


def fetch_search(service, query: str, *, days: int = 7, order: str = "viewCount",
                 max_results: int = 25, now: dt.datetime | None = None) -> list[dict]:
    """Recent videos matching a niche query (100 units — used to expand a found
    niche, not for routine discovery)."""
    now = now or dt.datetime.now(dt.timezone.utc)
    published_after = (now - dt.timedelta(days=days)).isoformat()
    resp = service.search().list(
        part="snippet", q=query, type="video", order=order,
        publishedAfter=published_after, maxResults=max_results).execute()
    # normalize search items (channelId lives under snippet) to the shared shape
    return resp.get("items", [])


def discover_channels(api_key: str, *, region: str = "US",
                      category_ids=DEFAULT_CATEGORIES, per_category: int = 30,
                      max_channels: int = 40, service=None,
                      velocity_first: bool = True, now: dt.datetime | None = None) -> list[str]:
    """Autonomously discover channels to watch from live trending. By default
    ranks by video view-*velocity* (fastest gainers), not popularity/size, so
    small channels with an exploding video are surfaced. `service`/`now` are
    injectable for tests."""
    svc = service or _service(api_key)
    items = fetch_trending(svc, region=region, category_ids=category_ids,
                           per_category=per_category)
    if velocity_first:
        now = now or dt.datetime.now(dt.timezone.utc)
        return channel_ids_by_velocity(items, now)[:max_channels]
    return channel_ids_from_items(items)[:max_channels]


def merge_watch_set(existing: list[str], discovered: list[str], *, cap: int = 200) -> list[str]:
    """Union of the current watch set and newly discovered channels, order-stable,
    capped so the universe grows but stays bounded."""
    out = list(dict.fromkeys([*existing, *discovered]))
    return out[:cap]
