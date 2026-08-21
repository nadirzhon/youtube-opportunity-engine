"""Provider factory — pick the real YouTube provider when a key is configured,
otherwise the deterministic mock. The rest of the system is provider-agnostic."""

from __future__ import annotations

from .. import config
from .mock import MockYouTubeProvider


def get_provider(settings: config.Settings | None = None, *, force_mock: bool = False):
    settings = settings or config.load()
    if force_mock or not settings.has_youtube:
        return MockYouTubeProvider(seed=settings.mock_seed)
    from .youtube import YouTubeDataProvider  # lazy: only when a real key exists
    import os
    channel_ids = [c for c in os.environ.get("YOUTUBE_CHANNEL_IDS", "").split(",") if c]
    return YouTubeDataProvider(settings.youtube_api_key, channel_ids)
