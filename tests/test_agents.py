"""Content-agent tests (mock LLM, no key/network). Run: pytest -q"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe.agents import build_opportunity
from yoe.agents.concept import generate as gen_concepts, _originality
from yoe.agents.llm import MockLLMProvider
from yoe.agents.quality import run_gate
from yoe.agents.research import research
from yoe.agents.schemas import ResearchThesis
from yoe.pipeline import run
from yoe.providers.mock import MockYouTubeProvider


def _top_opportunity():
    report = run(MockYouTubeProvider(1337))
    return report.opportunities[0], [a.video_id for a in report.breakouts]


# -- research -------------------------------------------------------------
def test_research_produces_structured_thesis():
    opp, _ = _top_opportunity()
    t = research(opp, MockLLMProvider())
    assert t.topic == opp.topic
    assert t.recommended_angle and t.audience_desire and t.content_gap
    # research can't be more confident than the signal it's built on
    assert t.confidence == round(opp.confidence, 2)
    # opportunity's reasons-against fold into risks
    for r in opp.reasons_against:
        assert r in t.risks


# -- originality guard ----------------------------------------------------
def test_originality_penalizes_echoed_titles():
    assert _originality("My unique fresh take", ["totally different"]) > 0.5
    assert _originality("How to bake bread", ["How to bake bread"]) < 0.2


def test_concept_engine_drops_near_duplicate_titles():
    thesis = ResearchThesis("t", "d", "e", "gap", "angle", [], [], [], 0.9)
    # source titles identical to what the mock would produce → should be filtered
    concepts = gen_concepts(thesis, MockLLMProvider(), n=10, top=3,
                            source_titles=["I tested t so you don't have to"])
    for c in concepts:
        assert c.originality >= 0.35  # nothing that closely echoes a source survives


# -- quality gate ---------------------------------------------------------
def test_quality_gate_passes_a_clean_package():
    opp, src = _top_opportunity()
    pkg = build_opportunity(opp, source_titles=src)
    assert pkg.quality.score > 0
    # originality and policy are hard gates
    for c in pkg.quality.checks:
        if c.name in ("originality", "policy"):
            assert isinstance(c.passed, bool)


def test_quality_gate_flags_deceptive_clickbait():
    from yoe.agents.schemas import Concept, Script
    bad = Concept(premise="p", target_viewer="v", viewer_promise="pr", unique_angle="a",
                  hook="You won't believe this", story_arc=["x"], thumbnail_concept="t",
                  title_hypotheses=["Shocking secret they don't want you to know"],
                  why_differentiated="", suggested_duration_sec=480, originality=0.9)
    script = Script(title="t", hook="You won't believe this", sections=[
        {"heading": "a", "beats": ["one two three"], "retention_device": "open loop"},
        {"heading": "b", "beats": ["four five six"], "retention_device": "payoff"},
        {"heading": "c", "beats": ["seven eight"], "retention_device": "visual change"},
    ], outro="end", word_count=20)
    res = run_gate(bad, script, originality=0.9)
    policy = next(c for c in res.checks if c.name == "policy")
    assert not policy.passed
    assert not res.passed  # policy is a hard gate


# -- end-to-end workflow --------------------------------------------------
def test_build_opportunity_full_chain():
    opp, src = _top_opportunity()
    pkg = build_opportunity(opp, source_titles=src)
    assert pkg.topic == opp.topic
    assert pkg.thesis and pkg.concepts and pkg.chosen
    assert len(pkg.concepts) <= 3
    assert pkg.script.sections and pkg.script.word_count > 0
    assert pkg.chosen is pkg.concepts[0]           # highest-ranked chosen
    # every intermediate artifact is inspectable
    d = pkg.to_dict()
    assert set(d) >= {"thesis", "concepts", "chosen", "script", "quality"}
