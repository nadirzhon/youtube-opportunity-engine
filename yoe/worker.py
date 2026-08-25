"""
Autonomous 24/7 worker.

The long-running process that makes the engine *run itself*. Each cycle:

  1. collect a snapshot pass under quota control (adaptive cadence)   → history
  2. re-run the engine on accumulated history                        → opportunities
  3. (optional) auto-build the top opportunity into a content package → asset
  4. write a heartbeat + counters to the store                       → observability
  5. sleep for the configured interval, then repeat

Design goals for real 24/7 operation:
- **Never dies on a bad cycle.** Any exception in a cycle is caught, logged, and
  the loop backs off exponentially (capped) instead of crashing the process.
- **Graceful shutdown.** SIGTERM/SIGINT stop the loop cleanly between cycles, so
  `docker stop` / `systemctl stop` don't corrupt a write.
- **Degrades safely.** No YouTube key → mock provider (spec rule). Over budget →
  the cycle skips collection and logs it, rather than erroring.
- **Observable.** Heartbeat, last error, cycle count and last opportunities go to
  the `kv` store; the API's `/status` reads them. No extra infra required.

Run:  python -m yoe.worker
Stop: Ctrl-C  (or SIGTERM from the process manager)
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import signal
import time

from . import config, store
from .pipeline import run_from_store
from .providers.factory import get_provider
from .quota import QuotaManager
from .scheduler import tick

log = logging.getLogger("yoe.worker")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


class Worker:
    """A restartable 24/7 loop. `run_forever()` blocks; `run_cycle()` is one pass
    (pure and testable — the daemon just calls it on a timer)."""

    def __init__(self, settings: config.Settings | None = None, *, conn=None):
        self.settings = settings or config.load()
        self.conn = conn or store.connect(self.settings.database_url or None)
        self.quota = QuotaManager(
            daily_quota=self.settings.youtube_daily_quota,
            daily_budget_usd=self.settings.daily_budget_usd,
            monthly_budget_usd=self.settings.monthly_budget_usd)
        self._stop = False
        self._cycles = 0
        self._errors = 0
        self._quota_day = dt.datetime.now(dt.timezone.utc).date()

    # -- lifecycle --------------------------------------------------------
    def request_stop(self, *_a) -> None:
        """Signal handler: finish the current cycle, then exit the loop."""
        log.info("shutdown requested — will stop after this cycle")
        self._stop = True

    def install_signals(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, self.request_stop)
            except ValueError:
                pass  # not in main thread (e.g. tests) — caller drives the loop

    # -- one pass ---------------------------------------------------------
    def _maybe_roll_quota_day(self) -> None:
        """Reset the daily YouTube quota + $ spend when the UTC date rolls over —
        without this a long-lived worker exhausts day 1's quota and then skips
        collection forever. (Observed live: 40 cycles of `skipped(budget)`.)"""
        today = dt.datetime.now(dt.timezone.utc).date()
        if today != self._quota_day:
            self.quota.reset_day()
            self._quota_day = today
            log.info("new UTC day %s — daily quota/budget reset", today)

    def _provider_for_cycle(self):
        """Build this cycle's provider. With a real key + auto-discovery on, the
        watch set is grown autonomously from live trending and persisted — no
        hand-fed channel list required (YOUTUBE_CHANNEL_IDS just seeds it)."""
        import os
        s = self.settings
        if not s.has_youtube:
            return get_provider(s), 0            # mock

        from . import discovery
        from .providers.youtube import YouTubeDataProvider
        watch = store.get_state(self.conn, "watch_channels", []) or []
        seed = [c for c in os.environ.get("YOUTUBE_CHANNEL_IDS", "").split(",") if c]
        watch = discovery.merge_watch_set(seed, watch, cap=s.watch_set_cap)

        # (re)discover on the first cycle, when empty, or every N cycles
        due = s.youtube_auto_discover and (
            not watch or self._cycles % max(1, s.discovery_every_cycles) == 0)
        if due:
            cats = (tuple(c.strip() or None for c in s.youtube_categories.split(","))
                    if s.youtube_categories else discovery.DEFAULT_CATEGORIES)
            found = discovery.discover_channels(
                s.youtube_api_key, region=s.youtube_region, category_ids=cats,
                max_channels=s.discovery_max_channels)
            watch = discovery.merge_watch_set(watch, found, cap=s.watch_set_cap)
            log.info("discovery: watch set now %d channels (+%d newly found)",
                     len(watch), len(found))

        store.set_state(self.conn, "watch_channels", watch)
        return YouTubeDataProvider(s.youtube_api_key, watch), len(watch)

    def run_cycle(self) -> dict:
        """One discover→collect→analyze→(build)→record pass. Returns a summary.
        Raises nothing that run_forever can't absorb; still, callers get truth."""
        self._maybe_roll_quota_day()
        provider, watching = self._provider_for_cycle()
        prov = "mock" if getattr(provider, "is_mock", False) else "youtube"

        sched = tick(self.conn, provider, self.quota)
        report = run_from_store(self.conn)
        opps = [o for o in report.opportunities
                if o.score >= self.settings.worker_min_opp_score]

        built = None
        if self.settings.worker_auto_build and opps:
            built = self._auto_build(opps[0], report)

        self._cycles += 1
        summary = {
            "cycle": self._cycles,
            "at": _now(),
            "provider": prov,
            "watching_channels": watching,
            "collected": sched.collected,
            "skipped_over_budget": sched.skipped_over_budget,
            "opportunities": [{"topic": o.topic, "score": round(o.score, 1),
                               "stage": o.stage.value} for o in opps[:10]],
            "auto_built": built,
            "quota": sched.quota,
            "errors_total": self._errors,
        }
        self._heartbeat(summary, healthy=True)
        top = opps[0].topic if opps else "—"
        log.info("cycle %d ok · provider=%s · %d opps · top=%s%s",
                 self._cycles, prov, len(opps), top,
                 " · skipped(budget)" if sched.skipped_over_budget else "")
        return summary

    def _auto_build(self, opp, report) -> dict | None:
        """Turn the top opportunity into a content package and learn from history.
        Kept best-effort: a build failure must not sink the whole cycle."""
        try:
            from .agents import build_opportunity
            from .learning import learned_boost
            experience = learned_boost(store.load_experiments(self.conn, niche=opp.topic))
            source_titles = [a.video_id for a in report.breakouts]
            pkg = build_opportunity(opp, source_titles=source_titles, experience=experience)
            return {"topic": opp.topic, "quality_passed": pkg.quality.passed,
                    "quality_score": pkg.quality.score,
                    "thumbnail": pkg.thumbnails[0].direction if pkg.thumbnails else None}
        except Exception as e:  # noqa: BLE001 — best-effort stage
            log.warning("auto-build failed for %s: %s", opp.topic, e)
            return {"topic": opp.topic, "error": str(e)}

    # -- observability ----------------------------------------------------
    def _heartbeat(self, summary: dict, *, healthy: bool, error: str | None = None) -> None:
        store.set_state(self.conn, "worker", {
            "healthy": healthy,
            "last_beat": _now(),
            "cycles": self._cycles,
            "errors": self._errors,
            "interval_sec": self.settings.worker_interval_sec,
            "auto_build": self.settings.worker_auto_build,
            "last_error": error,
            "last_summary": summary,
        })

    # -- the loop ---------------------------------------------------------
    def run_forever(self, *, install_signals: bool = True, max_cycles: int | None = None) -> None:
        if install_signals:
            self.install_signals()
        interval = max(5, self.settings.worker_interval_sec)
        backoff = 0
        log.info("worker starting · interval=%ss · auto_build=%s · db=%s",
                 interval, self.settings.worker_auto_build,
                 self.settings.database_url or "sqlite:///yoe.db")
        while not self._stop:
            try:
                self.run_cycle()
                backoff = 0
            except Exception as e:  # noqa: BLE001 — the loop must survive anything
                self._errors += 1
                backoff = min(self.settings.worker_max_backoff_sec,
                              (backoff or 15) * 2)
                log.exception("cycle failed (error #%d) — backing off %ss", self._errors, backoff)
                self._heartbeat({"at": _now()}, healthy=False, error=str(e))
            if max_cycles is not None and self._cycles >= max_cycles:
                break
            self._sleep(backoff or interval)
        log.info("worker stopped after %d cycles (%d errors)", self._cycles, self._errors)

    def _sleep(self, seconds: float) -> None:
        """Interruptible sleep — checks the stop flag once a second so shutdown
        is prompt even with a long interval."""
        end = seconds
        step = 1.0
        elapsed = 0.0
        while elapsed < end and not self._stop:
            time.sleep(min(step, end - elapsed))
            elapsed += step


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # WORKER_MAX_CYCLES lets a scheduler (cron / GitHub Actions) run exactly one
    # cycle and exit — the loop persists to the DB, so state carries across runs.
    max_cycles = os.environ.get("WORKER_MAX_CYCLES")
    w = Worker()
    if max_cycles:
        w._sleep = lambda s: None       # no waiting when we run a fixed count
        w.run_forever(install_signals=False, max_cycles=int(max_cycles))
    else:
        w.run_forever()


if __name__ == "__main__":
    main()
