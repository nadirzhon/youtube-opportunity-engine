"""
Real YouTube Data API provider.

Implements the same interface as the mock, so the engine doesn't change. Uses
the official YouTube Data API v3 via google-api-python-client. Imported lazily —
the dependency is only needed when a real key is configured, so tests and the
mock path never require it.

Note on snapshots: the Data API returns *current* counters only. Real velocity
comes from persisting repeated reads over time (the collector/scheduler in a
later phase). This provider therefore returns each video with a single current
snapshot; the historical series is built by the collector across runs.
"""

from __future__ import annotations

from ..models import Channel, Video, VideoSnapshot


class YouTubeDataProvider:
    is_mock = False

    def __init__(self, api_key: str, channel_ids: list[str] | None = None) -> None:
        if not api_key:
            raise ValueError("YouTubeDataProvider requires an API key")
        self.api_key = api_key
        self.channel_ids = channel_ids or []
        self._svc = None

    def _service(self):
        if self._svc is None:
            try:
                from googleapiclient.discovery import build  # lazy import
            except ImportError as e:  # pragma: no cover
                raise RuntimeError(
                    "google-api-python-client not installed. "
                    "pip install google-api-python-client") from e
            self._svc = build("youtube", "v3", developerKey=self.api_key,
                              cache_discovery=False)
        return self._svc

    def list_channels(self) -> list[Channel]:
        if not self.channel_ids:
            return []
        resp = self._service().channels().list(
            part="snippet,statistics,topicDetails",
            id=",".join(self.channel_ids[:50]), maxResults=50).execute()
        out: list[Channel] = []
        for it in resp.get("items", []):
            stats = it.get("statistics", {})
            topics = tuple(t.split("/")[-1] for t in
                           it.get("topicDetails", {}).get("topicCategories", []))
            out.append(Channel(
                channel_id=it["id"],
                title=it["snippet"]["title"],
                subscriber_count=int(stats.get("subscriberCount", 0) or 0),
                video_count=int(stats.get("videoCount", 0) or 0),
                topics=topics))
        return out

    def _uploads_playlist(self, channel_id: str) -> str | None:
        resp = self._service().channels().list(
            part="contentDetails", id=channel_id, maxResults=1).execute()
        items = resp.get("items", [])
        if not items:
            return None
        return items[0]["contentDetails"]["relatedPlaylists"].get("uploads")

    def list_videos(self, channel_id: str) -> list[Video]:
        # Recent uploads via the channel's uploads playlist (1 quota unit) rather
        # than search.list (100 units, and unreliable — it returns 0 for many
        # channels). Then hydrate stats via videos.list.
        uploads = self._uploads_playlist(channel_id)
        if not uploads:
            return []
        pl = self._service().playlistItems().list(
            part="contentDetails", playlistId=uploads, maxResults=25).execute()
        ids = [it["contentDetails"]["videoId"] for it in pl.get("items", [])
               if it.get("contentDetails", {}).get("videoId")]
        if not ids:
            return []
        vresp = self._service().videos().list(
            part="snippet,statistics,contentDetails,topicDetails",
            id=",".join(ids), maxResults=50).execute()
        out: list[Video] = []
        for it in vresp.get("items", []):
            stats = it.get("statistics", {})
            snip = it["snippet"]
            age = _age_hours(snip.get("publishedAt", ""))
            topics = tuple(t.split("/")[-1] for t in
                           it.get("topicDetails", {}).get("topicCategories", []))
            out.append(Video(
                video_id=it["id"], channel_id=channel_id, title=snip.get("title", ""),
                published_hours_ago=age,
                duration_sec=_iso8601_seconds(it.get("contentDetails", {}).get("duration", "PT0S")),
                category=snip.get("categoryId", ""), topics=topics or ("uncategorized",),
                snapshots=[VideoSnapshot(
                    at_hours=age,
                    view_count=int(stats.get("viewCount", 0) or 0),
                    like_count=int(stats.get("likeCount", 0) or 0),
                    comment_count=int(stats.get("commentCount", 0) or 0))]))
        return out

    def snapshot_video(self, video_id: str, at_hours: float):
        vresp = self._service().videos().list(part="statistics", id=video_id).execute()
        items = vresp.get("items", [])
        if not items:
            return None
        s = items[0]["statistics"]
        return VideoSnapshot(at_hours, int(s.get("viewCount", 0) or 0),
                             int(s.get("likeCount", 0) or 0),
                             int(s.get("commentCount", 0) or 0))


def _age_hours(iso: str) -> float:
    import datetime as dt
    if not iso:
        return 0.0
    try:
        published = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    delta = dt.datetime.now(dt.timezone.utc) - published
    return max(0.0, delta.total_seconds() / 3600.0)


def _iso8601_seconds(dur: str) -> int:
    """Parse an ISO-8601 duration like PT1H2M3S into seconds."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur or "")
    if not m:
        return 0
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s
