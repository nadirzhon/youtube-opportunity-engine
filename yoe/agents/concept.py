"""
Concept engine — generates N original concepts per opportunity and ranks the
top 3. Each concept carries a premise, target viewer, promise, unique angle,
hook, story arc, thumbnail concept, title hypotheses and why it's differentiated.

Originality guard (a spec non-negotiable): a concept whose title merely echoes a
breakout video's title is penalized and can be rejected — we don't rewrite
existing titles, we create genuinely different angles.
"""

from __future__ import annotations

import difflib

from .llm import LLMProvider
from .schemas import Concept, ResearchThesis


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _originality(title: str, source_titles: list[str]) -> float:
    """1.0 = fully original; low if it closely mirrors a source/breakout title."""
    if not source_titles:
        return 1.0
    worst = max(_similar(title, s) for s in source_titles)
    return round(1.0 - worst, 2)


def generate(thesis: ResearchThesis, llm: LLMProvider, *, n: int = 10,
             top: int = 3, source_titles: list[str] | None = None) -> list[Concept]:
    source_titles = source_titles or []
    out = llm.generate("concepts", {
        "topic": thesis.topic,
        "recommended_angle": thesis.recommended_angle,
        "n": n,
    })
    concepts: list[Concept] = []
    for c in out.get("concepts", []):
        title = c.get("title", "")
        orig = _originality(title, source_titles)
        title_hyps = [title, f"{title} (I was wrong)", f"What {thesis.topic} really needs"]
        concept = Concept(
            premise=c.get("premise", ""),
            target_viewer=c.get("target_viewer", ""),
            viewer_promise=c.get("viewer_promise", ""),
            unique_angle=c.get("unique_angle", ""),
            hook=c.get("hook", ""),
            story_arc=c.get("story_arc", []),
            thumbnail_concept=c.get("thumbnail_concept", ""),
            title_hypotheses=title_hyps,
            why_differentiated=f"Angle: {c.get('unique_angle','')}. Originality vs breakout titles: {orig}.",
            suggested_duration_sec=int(c.get("duration_sec", 480)),
            originality=orig,
        )
        # rank: originality + promise clarity + confidence of the thesis
        promise_bonus = 0.15 if concept.viewer_promise else 0.0
        concept.rank_score = round(0.6 * orig + 0.25 * thesis.confidence + promise_bonus, 3)
        # drop near-duplicates of a source title outright (spec: don't rewrite titles)
        if orig < 0.35:
            continue
        concepts.append(concept)

    concepts.sort(key=lambda c: c.rank_score, reverse=True)
    return concepts[:top]
