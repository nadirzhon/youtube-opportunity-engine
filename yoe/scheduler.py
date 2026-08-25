"""
Scheduler (Phase 2).

Decides *what* to collect and drives the collector under quota control. The
sampling cadence is adaptive (the spec's rule): new videos get high-frequency
snapshots, young videos medium, mature ones low — so history stays dense where
velocity actually changes without burning quota on settled videos.

The actual timer (cron/launchd/asyncio loop) is external; `tick()` is a pure,
testable unit that runs one scheduled pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from .quota import QuotaManager
from .store import collect


def sampling_priority(age_hours: float) -> str:
    if age_hours <= 24:
        return "high"      # new: snapshot often
    if age_hours <= 168:
        return "medium"    # young: a few times a day
    return "low"           # mature: occasionally


def due_for_snapshot(age_hours: float, hours_since_last: float) -> bool:
    interval = {"high": 1.0, "medium": 6.0, "low": 24.0}[sampling_priority(age_hours)]
    return hours_since_last >= interval


@dataclass
class SchedulerResult:
    collected: dict
    quota: dict
    skipped_over_budget: bool = False


def tick(conn, provider, quota: QuotaManager | None = None, *,
         adaptive: bool = False) -> SchedulerResult:
    """Run one scheduled collection pass under quota control. With `adaptive`, the
    collector skips channels not yet due (maturity-based cadence) — so quota is
    charged only for channels actually fetched, not the whole watch set."""
    quota = quota or QuotaManager()
    # Per fetched channel: channels.list contentDetails (1) + playlistItems.list
    # (1) + videos.list (1) = 3 units — the uploads-playlist path, ~30× cheaper
    # than the old search.list (100 units) approach.
    channels = provider.list_channels()
    per_channel = (quota.estimate_quota("channels.list")
                   + quota.estimate_quota("playlistItems.list")
                   + quota.estimate_quota("videos.list"))
    # Skip the cycle if we can't afford even the channel list + one channel fetch.
    if quota.quota_used + quota.estimate_quota("channels.list") + per_channel > quota.daily_quota:
        return SchedulerResult(collected={"channels": 0, "videos": 0, "snapshots": 0},
                               quota=quota.status(), skipped_over_budget=True)

    quota.charge_quota("channels.list")
    result = collect(conn, provider, adaptive=adaptive)
    # Account for what was actually spent (channels fetched × per-channel cost).
    # Set directly rather than charge_quota() so a mid-cycle overrun records the
    # usage instead of raising — the next cycle's pre-check then skips.
    quota.quota_used += result.get("channels", 0) * per_channel

    return SchedulerResult(collected=result, quota=quota.status())
