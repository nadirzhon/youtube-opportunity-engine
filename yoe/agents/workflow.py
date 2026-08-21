"""
Build Opportunity — the one-click workflow.

One call orchestrates the whole discover→create chain for a chosen opportunity:
research → concepts → rank → script → quality gate → package. Every intermediate
artifact is kept on the package for inspection (per the spec). Runs on the mock
LLM with no key; swap in a real provider for model-quality prose.
"""

from __future__ import annotations

from ..models import AnomalyResult, Opportunity
from .llm import LLMProvider, MockLLMProvider
from . import concept as concept_engine
from . import quality as quality_gate
from . import research as research_agent
from . import script as script_engine
from .schemas import OpportunityPackage


def build_opportunity(opportunity: Opportunity, llm: LLMProvider | None = None,
                      *, source_titles: list[str] | None = None) -> OpportunityPackage:
    llm = llm or MockLLMProvider()

    thesis = research_agent.research(opportunity, llm)
    concepts = concept_engine.generate(thesis, llm, n=10, top=3,
                                       source_titles=source_titles or [])
    if not concepts:
        raise ValueError("no original concepts survived the originality filter")
    chosen = concepts[0]
    script = script_engine.write(chosen, llm)
    quality = quality_gate.run_gate(chosen, script, originality=chosen.originality)

    return OpportunityPackage(topic=opportunity.topic, thesis=thesis,
                              concepts=concepts, chosen=chosen, script=script,
                              quality=quality)
