"""
Research agent — turns a scored opportunity into a structured thesis: audience
desire, emotional trigger, content gap, recommended angle, risks, evidence,
confidence. Uses the opportunity's own evidence (breakout videos, breadth) as
grounding, plus the LLM for the qualitative reasoning.
"""

from __future__ import annotations

from ..models import Opportunity
from .llm import LLMProvider
from .schemas import ResearchThesis


def research(opportunity: Opportunity, llm: LLMProvider) -> ResearchThesis:
    out = llm.generate("research", {
        "topic": opportunity.topic,
        "stage": opportunity.stage.value,
        "evidence": opportunity.evidence,
    })
    # Confidence inherits the opportunity's — research can't be more certain than
    # the signal it's built on. Risks fold in the opportunity's reasons-against.
    risks = list(dict.fromkeys(out.get("risks", []) + opportunity.reasons_against))
    return ResearchThesis(
        topic=opportunity.topic,
        audience_desire=out.get("audience_desire", ""),
        emotional_trigger=out.get("emotional_trigger", ""),
        content_gap=out.get("content_gap", ""),
        recommended_angle=out.get("recommended_angle", ""),
        oversupplied_angles=out.get("oversupplied_angles", []),
        risks=risks,
        evidence=opportunity.evidence,
        confidence=round(opportunity.confidence, 2),
    )
