"""
Media provider interfaces + mocks (Phase 6).

Voice, image and render each hide behind an interface so no vendor is
load-bearing (spec rule). The mocks produce real files (silent audio spec,
placeholder image bytes, an ffmpeg command) so the pipeline runs end-to-end and
is testable with no API keys and no paid calls. A real provider (ElevenLabs,
an image model, a cloud renderer) implements the same three methods.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Asset:
    kind: str            # voice | image | subtitle | video
    path: str
    meta: dict


class TTSProvider(Protocol):
    is_mock: bool
    def synthesize(self, text: str, out_dir: str, name: str) -> Asset: ...


class ImageProvider(Protocol):
    is_mock: bool
    def image(self, prompt: str, out_dir: str, name: str) -> Asset: ...


class RenderProvider(Protocol):
    is_mock: bool
    def render(self, images: list[Asset], voice: Asset, subtitles: Asset,
               out_dir: str, name: str) -> Asset: ...


# ---------------------------------------------------------------------------
# Mocks — deterministic, produce inspectable files, zero cost.
# ---------------------------------------------------------------------------
class MockTTS:
    is_mock = True

    def synthesize(self, text: str, out_dir: str, name: str) -> Asset:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{name}.voice.txt")
        words = len(text.split())
        seconds = round(words / 2.6, 1)          # ~156 wpm narration
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return Asset("voice", path, {"seconds": seconds, "words": words, "mock": True})


class MockImage:
    is_mock = True

    def image(self, prompt: str, out_dir: str, name: str) -> Asset:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{name}.img.txt")
        digest = hashlib.sha1(prompt.encode()).hexdigest()[:8]
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"[placeholder image]\nprompt: {prompt}\nseed: {digest}\n")
        return Asset("image", path, {"prompt": prompt, "seed": digest, "mock": True})


class MockRender:
    is_mock = True

    def render(self, images, voice, subtitles, out_dir, name) -> Asset:
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{name}.mp4.plan")
        cmd = build_ffmpeg_command(images, voice, subtitles, os.path.join(out_dir, f"{name}.mp4"))
        with open(path, "w", encoding="utf-8") as f:
            f.write(cmd)
        return Asset("video", path, {"ffmpeg": cmd, "scenes": len(images), "mock": True})


def build_ffmpeg_command(images, voice, subtitles, out_path: str) -> str:
    """The real assembly command — a slideshow of scene images over the
    narration with burned-in subtitles. The real RenderProvider runs this;
    the mock just records it so it can be inspected/tested."""
    per = 4  # seconds per image if we lack precise timing
    inputs = " ".join(f"-loop 1 -t {per} -i {a.path}" for a in images)
    n = len(images)
    concat = "".join(f"[{i}:v]scale=1920:1080,setsar=1[v{i}];" for i in range(n))
    chain = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vid];"
    subs = f"[vid]subtitles={subtitles.path}[out]" if subtitles else "[vid]null[out]"
    return (f"ffmpeg -y {inputs} -i {voice.path} "
            f'-filter_complex "{concat}{chain}{subs}" '
            f'-map "[out]" -map {n}:a -shortest -pix_fmt yuv420p {out_path}')
