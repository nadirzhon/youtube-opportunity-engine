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


def tick(conn, provider, quota: QuotaManager | None = None) -> SchedulerResult:
    """Run one scheduled collection pass under quota control."""
    quota = quota or QuotaManager()
    # Estimate: channels.list (1) + search.list per channel (100) + videos.list (1)
    channels = provider.list_channels()
    est = quota.estimate_quota("channels.list") + \
        len(channels) * (quota.estimate_quota("search.list") + quota.estimate_quota("videos.list"))
    if quota.quota_used + est > quota.daily_quota:
        return SchedulerResult(collected={"channels": 0, "videos": 0, "snapshots": 0},
                               quota=quota.status(), skipped_over_budget=True)

    quota.charge_quota("channels.list")
    for _ in channels:
        quota.charge_quota("search.list")
        quota.charge_quota("videos.list")

    result = collect(conn, provider)
    return SchedulerResult(collected=result, quota=quota.status())
