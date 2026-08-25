"""
Multi-channel profiles — run several channel identities from one engine.

The plan is several accounts, each owning a niche. A ChannelProfile is that
identity: a name, the niche it hunts (keywords + YouTube categories + region),
and a minimum RPM it bothers with. Each profile gets its OWN tailored feed of
opportunities (filtered to its niche, ranked by profit) and its OWN learning
namespace (experiments are keyed by niche/topic already), so what one channel
learns doesn't blur another.

This is the seam for autonomy-at-scale: define N profiles and the engine hunts N
niches in parallel. Publishing to the actual accounts is a separate, consented
step (OAuth per account) — this module decides *what each channel should make*,
not the upload.

Persistence rides on the store's kv table (no new schema). Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

from . import economics


@dataclass
class ChannelProfile:
    id: str
    name: str
    niche_keywords: list[str] = field(default_factory=list)   # match against topics
    category_ids: list[str] = field(default_factory=list)     # discovery bias
    region: str = "US"
    min_rpm: float = 0.0                                       # ignore niches paying less
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def matches(self, topic: str) -> bool:
        if not self.niche_keywords:
            return True                     # a catch-all profile
        t = (topic or "").lower()
        return any(kw.lower() in t for kw in self.niche_keywords)


def feed_for(profile: ChannelProfile, opportunities: list[dict]) -> list[dict]:
    """This profile's tailored shortlist: opportunities whose topic matches the
    niche and whose estimated RPM clears the floor, enriched + ranked by profit."""
    picked = []
    for o in opportunities:
        if not profile.matches(o["topic"]):
            continue
        e = economics.enrich(o)
        if e["economics"]["rpm_mid"] < profile.min_rpm:
            continue
        picked.append(e)
    picked.sort(key=lambda o: o["economics"]["profit_priority"], reverse=True)
    return picked


# ---------------------------------------------------------------------------
# Persistence on the kv store (a list of profile dicts under one key).
# ---------------------------------------------------------------------------
_KEY = "channel_profiles"


def list_profiles(conn) -> list[ChannelProfile]:
    from . import store
    raw = store.get_state(conn, _KEY, []) or []
    return [ChannelProfile(**p) for p in raw]


def save_profile(conn, profile: ChannelProfile) -> None:
    from . import store
    profiles = {p.id: p for p in list_profiles(conn)}
    profiles[profile.id] = profile
    store.set_state(conn, _KEY, [p.to_dict() for p in profiles.values()])


def delete_profile(conn, profile_id: str) -> bool:
    from . import store
    profiles = [p for p in list_profiles(conn) if p.id != profile_id]
    store.set_state(conn, _KEY, [p.to_dict() for p in profiles])
    return True


def all_categories(profiles: list[ChannelProfile]) -> tuple:
    """Union of the category filters across profiles (for shared discovery). Empty
    → the default spread."""
    cats: list[str] = []
    for p in profiles:
        for c in p.category_ids:
            if c not in cats:
                cats.append(c)
    return tuple(cats)
