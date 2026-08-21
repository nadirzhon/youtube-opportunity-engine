"""
Provider interface — every network integration hides behind an abstraction so
the engine never couples to one vendor (a hard rule in the spec). A real
YouTubeDataProvider (google-api-python-client) and this mock both implement it.
"""

from __future__ import annotations

from typing import Protocol

from ..models import Channel, Video


class YouTubeProvider(Protocol):
    """Read-only access to public YouTube data plus time-series snapshots."""

    def list_channels(self) -> list[Channel]: ...

    def list_videos(self, channel_id: str) -> list[Video]: ...

    def snapshot_video(self, video_id: str, at_hours: float): ...
