"""
Mock YouTube provider — deterministic fixture data with planted signals.

Generates channels and videos whose view time-series mostly follow each
channel's own baseline, PLUS:
  * a clear single-video breakout (one video massively out-performing its
    channel median at the same age), and
  * a genuine topic trend (several independent channels accelerating on the
    same micro-niche) — so the engine can tell a repeatable opportunity from
    one-off viral noise.

Fully seeded, so tests and the E2E demo are reproducible. Pure stdlib.
"""

from __future__ import annotations

import math
from random import Random

from ..models import Channel, Video, VideoSnapshot

# Micro-niches used to tag videos; "ai-agents-security" is the planted trend.
_TOPICS = ["home-cooking", "budget-travel", "retro-gaming", "ai-agents-security",
           "houseplants", "car-detailing"]
_TREND_TOPIC = "ai-agents-security"

# Snapshot cadence (hours since publish) — dense early, sparse later.
_SNAP_HOURS = [1, 3, 6, 12, 24, 48, 72, 120, 168]


def _growth_curve(final_views: int, age: float, at: float) -> int:
    """A saturating growth curve: fast early, tapering — views at time `at`."""
    if age <= 0:
        return final_views
    # logistic-ish fraction of final reached by time `at`
    k = 6.0 / age
    frac = 1 / (1 + math.exp(-k * (at - age * 0.30)))
    frac0 = 1 / (1 + math.exp(-k * (0 - age * 0.30)))
    frac = (frac - frac0) / (1 - frac0)
    return max(0, int(final_views * frac))


class MockYouTubeProvider:
    is_mock = True

    def __init__(self, seed: int = 1337) -> None:
        self.rng = Random(seed)
        self._channels: list[Channel] = []
        self._videos: dict[str, list[Video]] = {}
        self._build()

    # -- fixtures ---------------------------------------------------------
    def _build(self) -> None:
        for ci in range(8):
            subs = self.rng.choice([2_000, 12_000, 45_000, 120_000, 500_000])
            topic = _TOPICS[ci % len(_TOPICS)]
            ch = Channel(f"UC{ci:04d}", f"Channel {ci}", subs,
                         video_count=self.rng.randint(40, 300), topics=(topic,))
            self._channels.append(ch)
            self._videos[ch.channel_id] = self._channel_videos(ch, topic)

        # Plant a genuine trend: 3 extra small channels all accelerating on the
        # trend topic (independent channels → repeatable opportunity, not noise).
        for k in range(3):
            ch = Channel(f"UCTREND{k}", f"Trend Creator {k}",
                         subscriber_count=self.rng.choice([1_500, 6_000, 20_000]),
                         video_count=self.rng.randint(20, 80), topics=(_TREND_TOPIC,))
            self._channels.append(ch)
            self._videos[ch.channel_id] = self._trend_videos(ch)

    def _base_views(self, subs: int) -> int:
        """Typical views for this channel's median video."""
        return max(200, int(subs * self.rng.uniform(0.03, 0.09)))

    def _channel_videos(self, ch: Channel, topic: str) -> list[Video]:
        median = self._base_views(ch.subscriber_count)
        vids: list[Video] = []
        for vi in range(8):
            age = self.rng.choice([60, 110, 160, 220, 300])   # established catalog = mature
            # most videos ~ channel median; one video (vi==2) is a breakout
            if vi == 2:
                final = int(median * self.rng.uniform(9, 16))   # extreme breakout
            else:
                final = int(median * self.rng.uniform(0.5, 1.6))
            vids.append(self._make_video(ch, f"{ch.channel_id}V{vi}",
                                         f"{topic} video {vi}", topic, age, final))
        return vids

    def _trend_videos(self, ch: Channel) -> list[Video]:
        median = self._base_views(ch.subscriber_count)
        vids: list[Video] = []
        for vi in range(4):
            age = self.rng.choice([6, 12, 24, 48])        # young + fast
            final = int(median * self.rng.uniform(3, 7))  # all outperforming
            vids.append(self._make_video(ch, f"{ch.channel_id}V{vi}",
                                         f"securing AI agents part {vi}",
                                         _TREND_TOPIC, age, final))
        return vids

    def _make_video(self, ch: Channel, vid: str, title: str, topic: str,
                    age: float, final: int) -> Video:
        snaps = [VideoSnapshot(at, _growth_curve(final, age, at),
                               like_count=int(_growth_curve(final, age, at) * 0.03),
                               comment_count=int(_growth_curve(final, age, at) * 0.004))
                 for at in _SNAP_HOURS if at <= max(age, _SNAP_HOURS[0])]
        if not snaps:
            snaps = [VideoSnapshot(_SNAP_HOURS[0], final)]
        return Video(vid, ch.channel_id, title, published_hours_ago=age,
                     duration_sec=self.rng.choice([420, 610, 900, 1200]),
                     category="Howto & Style", topics=(topic,), snapshots=snaps)

    # -- provider interface ----------------------------------------------
    def list_channels(self) -> list[Channel]:
        return list(self._channels)

    def list_videos(self, channel_id: str) -> list[Video]:
        return list(self._videos.get(channel_id, []))

    def snapshot_video(self, video_id: str, at_hours: float):
        for vids in self._videos.values():
            for v in vids:
                if v.video_id == video_id:
                    return VideoSnapshot(at_hours, v.views)
        return None
