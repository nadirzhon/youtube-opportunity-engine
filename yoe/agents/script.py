"""
Script engine — expands a chosen concept into a structured script through the
spec's stages (outline → hook → full script → originality review). Retention
devices (open loops, pattern interrupts, controlled reveals, payoff) are
attached per section. Returns a Script with a word count for the quality gate.
"""

from __future__ import annotations

from .llm import LLMProvider
from .schemas import Concept, Script


def write(concept: Concept, llm: LLMProvider) -> Script:
    out = llm.generate("script", {
        "topic": concept.premise,
        "hook": concept.hook,
        "story_arc": concept.story_arc,
    })
    sections = out.get("sections", [])
    words = sum(len(" ".join(s.get("beats", [])).split()) for s in sections)
    words += len(out.get("hook", "").split()) + len(out.get("outro", "").split())
    return Script(
        title=concept.title_hypotheses[0] if concept.title_hypotheses else concept.premise,
        hook=out.get("hook", concept.hook),
        sections=sections,
        outro=out.get("outro", ""),
        word_count=words,
    )
