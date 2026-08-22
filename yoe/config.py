"""Runtime configuration — read from environment, with safe defaults.

No hard-coded secrets. Missing provider keys make the engine fall back to the
built-in mock, so the whole system runs end-to-end with zero external setup.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    youtube_api_key: str = ""
    llm_api_key: str = ""
    tts_api_key: str = ""
    image_api_key: str = ""
    database_url: str = os.environ.get("DATABASE_URL", "")
    redis_url: str = os.environ.get("REDIS_URL", "")
    daily_budget_usd: float = float(os.environ.get("DAILY_BUDGET_USD", "10") or 10)
    monthly_budget_usd: float = float(os.environ.get("MONTHLY_BUDGET_USD", "200") or 200)
    youtube_daily_quota: int = int(os.environ.get("YOUTUBE_DAILY_QUOTA", "10000") or 10000)
    mock_seed: int = int(os.environ.get("MOCK_SEED", "1337") or 1337)

    # -- 24/7 worker knobs ------------------------------------------------
    worker_interval_sec: int = int(os.environ.get("WORKER_INTERVAL_SEC", "1800") or 1800)
    worker_auto_build: bool = (os.environ.get("WORKER_AUTO_BUILD", "false").lower()
                               in ("1", "true", "yes"))
    worker_min_opp_score: float = float(os.environ.get("WORKER_MIN_OPP_SCORE", "65") or 65)
    worker_max_backoff_sec: int = int(os.environ.get("WORKER_MAX_BACKOFF_SEC", "900") or 900)

    @property
    def has_youtube(self) -> bool:
        return bool(self.youtube_api_key)


def load() -> Settings:
    return Settings(
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY", ""),
        llm_api_key=os.environ.get("LLM_API_KEY", ""),
        tts_api_key=os.environ.get("TTS_API_KEY", ""),
        image_api_key=os.environ.get("IMAGE_API_KEY", ""),
    )
