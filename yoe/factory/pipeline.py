"""
Video factory pipeline (Phase 6).

Takes an approved script and produces a review-ready draft: scene segmentation →
shot list → asset spec → voice → images → subtitles → FFmpeg assembly. Runs on
mock providers with no key/cost; swap in real providers for actual media.

Nothing here re-uploads or mirrors third-party video — assets are generated from
the (original) script, honoring the originality non-negotiable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from ..agents.schemas import Script
from .providers import (Asset, MockImage, MockRender, MockTTS,
                        ImageProvider, RenderProvider, TTSProvider)


@dataclass
class Scene:
    index: int
    heading: str
    narration: str
    shot: str            # what's on screen
    image_prompt: str


@dataclass
class VideoProject:
    title: str
    scenes: list[Scene]
    voice: Asset
    images: list[Asset]
    subtitles: Asset
    draft: Asset
    duration_sec: float
    review_ready: bool = True

    def to_dict(self) -> dict:
        return {
            "title": self.title, "scenes": len(self.scenes),
            "duration_sec": self.duration_sec, "review_ready": self.review_ready,
            "voice": self.voice.path, "images": [a.path for a in self.images],
            "subtitles": self.subtitles.path, "draft": self.draft.path,
            "ffmpeg": self.draft.meta.get("ffmpeg", ""),
        }


def segment(script: Script) -> list[Scene]:
    """One scene per script section — narration + a shot + an image prompt."""
    scenes: list[Scene] = []
    for i, s in enumerate(script.sections):
        narration = " ".join(s.get("beats", [])) or s.get("heading", "")
        heading = s.get("heading", f"scene {i}")
        scenes.append(Scene(
            index=i, heading=heading, narration=narration,
            shot=f"on screen: {heading} — supporting visual",
            image_prompt=f"clean, on-brand visual illustrating '{heading}', no text overlay"))
    return scenes


def _srt(scenes: list[Scene], secs_per: list[float], out_dir: str, name: str) -> Asset:
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{name}.srt")
    def stamp(t):
        h, r = divmod(int(t), 3600); m, s = divmod(r, 60)
        return f"{h:02d}:{m:02d}:{s:02d},000"
    t = 0.0
    lines = []
    for i, (sc, dur) in enumerate(zip(scenes, secs_per), 1):
        lines.append(f"{i}\n{stamp(t)} --> {stamp(t+dur)}\n{sc.narration[:120]}\n")
        t += dur
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return Asset("subtitle", path, {"cues": len(scenes)})


def build(script: Script, out_dir: str, *,
          tts: TTSProvider | None = None, image: ImageProvider | None = None,
          render: RenderProvider | None = None) -> VideoProject:
    tts = tts or MockTTS()
    image = image or MockImage()
    render = render or MockRender()
    name = "".join(c if c.isalnum() else "_" for c in script.title)[:40] or "draft"

    scenes = segment(script)
    # voice per scene → concatenated narration; images per scene
    full_narration = script.hook + " " + " ".join(sc.narration for sc in scenes) + " " + script.outro
    voice = tts.synthesize(full_narration, out_dir, name)
    images = [image.image(sc.image_prompt, out_dir, f"{name}_{sc.index}") for sc in scenes]

    total = float(voice.meta.get("seconds", len(scenes) * 4))
    secs_per = [total / max(1, len(scenes))] * len(scenes)
    subtitles = _srt(scenes, secs_per, out_dir, name)

    draft = render.render(images, voice, subtitles, out_dir, name)
    return VideoProject(title=script.title, scenes=scenes, voice=voice, images=images,
                        subtitles=subtitles, draft=draft, duration_sec=round(total, 1))
