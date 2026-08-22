"""
Quota & cost manager (Phase 2).

Guards the two scarce resources: the YouTube API daily quota and money spent on
paid providers (LLM/TTS/image/render). Estimates a job's cost before running it,
enforces daily/monthly/per-channel budgets with a hard stop, caches and dedupes
reusable requests, and backs off on demand. Pure stdlib; deterministic.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

# YouTube Data API v3 unit costs (documented quota units per call).
YT_UNIT_COST = {
    "channels.list": 1, "videos.list": 1, "search.list": 100,
    "playlistItems.list": 1, "commentThreads.list": 1,
}

# Provider $ costs (indicative; override per deployment).
PROVIDER_USD = {
    "llm_request": 0.01, "voice_generation": 0.05, "image": 0.04,
    "video_generation": 0.30, "render": 0.02,
}


class BudgetExceeded(RuntimeError):
    pass


@dataclass
class QuotaManager:
    daily_quota: int = 10_000
    daily_budget_usd: float = 10.0
    monthly_budget_usd: float = 200.0
    per_channel_budget_usd: float = 5.0
    hard_stop: bool = True

    quota_used: int = 0
    day_spend: float = 0.0
    month_spend: float = 0.0
    channel_spend: dict[str, float] = field(default_factory=dict)
    _cache: dict[str, object] = field(default_factory=dict)
    cache_hits: int = 0

    # -- YouTube quota ----------------------------------------------------
    def estimate_quota(self, call: str, n: int = 1) -> int:
        return YT_UNIT_COST.get(call, 1) * n

    def can_afford_quota(self, call: str, n: int = 1) -> bool:
        return self.quota_used + self.estimate_quota(call, n) <= self.daily_quota

    def charge_quota(self, call: str, n: int = 1) -> int:
        cost = self.estimate_quota(call, n)
        if not self.can_afford_quota(call, n):
            if self.hard_stop:
                raise BudgetExceeded(
                    f"YouTube quota would exceed daily {self.daily_quota} "
                    f"(used {self.quota_used}, +{cost})")
        self.quota_used += cost
        return cost

    # -- money ------------------------------------------------------------
    def estimate_cost(self, op: str, n: int = 1) -> float:
        return round(PROVIDER_USD.get(op, 0.0) * n, 4)

    def can_afford(self, op: str, n: int = 1, *, channel: str | None = None) -> bool:
        c = self.estimate_cost(op, n)
        # round the sums so float noise (0.01+0.05=0.06000…1) doesn't false-trip a budget
        if round(self.day_spend + c, 4) > self.daily_budget_usd:
            return False
        if round(self.month_spend + c, 4) > self.monthly_budget_usd:
            return False
        if channel and round(self.channel_spend.get(channel, 0.0) + c, 4) > self.per_channel_budget_usd:
            return False
        return True

    def charge(self, op: str, n: int = 1, *, channel: str | None = None) -> float:
        c = self.estimate_cost(op, n)
        if not self.can_afford(op, n, channel=channel) and self.hard_stop:
            raise BudgetExceeded(f"'{op}' (${c}) would exceed a budget "
                                 f"(day {self.day_spend}/{self.daily_budget_usd})")
        self.day_spend = round(self.day_spend + c, 4)
        self.month_spend = round(self.month_spend + c, 4)
        if channel:
            self.channel_spend[channel] = round(self.channel_spend.get(channel, 0.0) + c, 4)
        return c

    # -- cache / dedup ----------------------------------------------------
    def cached(self, key: str, produce):
        """Return a cached value or produce (and cache) it — dedupes calls."""
        if key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        val = produce()
        self._cache[key] = val
        return val

    def reset_day(self) -> None:
        self.quota_used = 0
        self.day_spend = 0.0
        self.channel_spend.clear()

    def status(self) -> dict:
        return {
            "quota_used": self.quota_used, "daily_quota": self.daily_quota,
            "day_spend": self.day_spend, "daily_budget_usd": self.daily_budget_usd,
            "month_spend": self.month_spend, "monthly_budget_usd": self.monthly_budget_usd,
            "cache_hits": self.cache_hits,
        }


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """Exponential backoff (deterministic; jitter added by the caller if wanted)."""
    return min(cap, base * (2 ** max(0, attempt)))
