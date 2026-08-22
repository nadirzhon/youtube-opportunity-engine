"""
Thumbnail engine (Phase 5 extension).

The thumbnail is the single biggest lever on click-through, so the spec asks for
*several* hypotheses and a reasoned pick — not one guess. This engine turns a
chosen concept into 5 distinct thumbnail directions and scores each on the axes
that actually predict clicks while staying honest:

  clarity        — one readable idea, not a collage
  curiosity      — an open loop the title can't fully close
  mobile_legible — big subject + ≤3 words, survives a phone-sized thumbnail
  uniqueness     — doesn't look like the breakout it competes with
  honesty        — the image matches the video (anti-clickbait; low = misleading)

overall = weighted blend, with honesty as a hard gate: a misleading thumbnail is
rejected no matter how clicky, because deceptive metadata is a spec non-negotiable.

Pure stdlib and deterministic — no image generation here; it designs the *brief*
that the video factory's image provider renders.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

# Five archetypal directions, each a genuinely different visual bet.
_DIRECTIONS = [
    ("face_reaction", "Close-up human face mid-reaction, bold 2-3 word overlay",
     {"clarity": 0.9, "curiosity": 0.8, "mobile_legible": 0.95, "uniqueness": 0.5}),
    ("before_after", "Split-screen before→after contrast, arrow between",
     {"clarity": 0.85, "curiosity": 0.75, "mobile_legible": 0.8, "uniqueness": 0.7}),
    ("single_object", "One hero object on clean high-contrast background",
     {"clarity": 0.95, "curiosity": 0.6, "mobile_legible": 0.9, "uniqueness": 0.75}),
    ("number_stat", "One big number/stat as the subject, minimal text",
     {"clarity": 0.9, "curiosity": 0.7, "mobile_legible": 0.85, "uniqueness": 0.65}),
    ("open_loop", "A framed question or redacted element that opens a loop",
     {"clarity": 0.7, "curiosity": 0.95, "mobile_legible": 0.7, "uniqueness": 0.8}),
]

_WEIGHTS = {"clarity": 0.22, "curiosity": 0.26, "mobile_legible": 0.24,
            "uniqueness": 0.18, "honesty": 0.10}
MIN_HONESTY = 0.5   # hard gate — below this the thumbnail misleads and is rejected


@dataclass
class Thumbnail:
    direction: str
    brief: str                 # what the image provider should render
    overlay_text: str          # ≤3 words on the image
    scores: dict               # per-axis 0..1
    overall: float             # 0..100
    accepted: bool             # passed the honesty gate
    rationale: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _overlay(concept, direction: str) -> str:
    """Pick ≤3 punchy words that reflect the concept's promise, not the title."""
    promise = (concept.viewer_promise or concept.unique_angle or concept.premise or "").strip()
    words = [w for w in promise.replace(",", " ").split() if w.isalpha()]
    if not words:
        return "WATCH THIS"
    if direction == "number_stat":
        return " ".join(words[:2]).upper()
    return " ".join(words[:3]).upper()


def _honesty(concept, direction: str) -> float:
    """How well the direction can truthfully represent the video. Open-loop and
    number directions carry more misleading risk if the payload is thin, so they
    require a concrete promise to score high."""
    has_concrete = bool((concept.viewer_promise or "").strip())
    base = {"face_reaction": 0.8, "before_after": 0.85, "single_object": 0.9,
            "number_stat": 0.75, "open_loop": 0.6}.get(direction, 0.8)
    return round(min(1.0, base + (0.1 if has_concrete else -0.15)), 2)


def generate(concept, *, source_titles: list[str] | None = None) -> list[Thumbnail]:
    """Produce 5 scored thumbnail options, best first; misleading ones rejected."""
    source_titles = source_titles or []
    out: list[Thumbnail] = []
    for direction, brief_tmpl, base in _DIRECTIONS:
        scores = dict(base)
        scores["honesty"] = _honesty(concept, direction)
        # a concept that's more original earns a small uniqueness bump
        scores["uniqueness"] = round(min(1.0, scores["uniqueness"]
                                         + 0.1 * (getattr(concept, "originality", 1.0) - 0.5)), 3)
        overall = round(100 * sum(_WEIGHTS[k] * scores[k] for k in _WEIGHTS), 1)
        accepted = scores["honesty"] >= MIN_HONESTY
        overlay = _overlay(concept, direction)
        weakest = min(scores, key=scores.get)
        rationale = (f"{brief_tmpl}. Strong on "
                     f"{max(scores, key=scores.get)}; watch {weakest}."
                     + ("" if accepted else " REJECTED: honesty below gate (misleading)."))
        out.append(Thumbnail(
            direction=direction,
            brief=f"{brief_tmpl}. Subject reflects: {concept.unique_angle or concept.premise}.",
            overlay_text=overlay, scores=scores, overall=overall,
            accepted=accepted, rationale=rationale))
    # accepted first, then by overall
    out.sort(key=lambda t: (t.accepted, t.overall), reverse=True)
    return out


def best(concept, **kw) -> Thumbnail:
    return generate(concept, **kw)[0]
