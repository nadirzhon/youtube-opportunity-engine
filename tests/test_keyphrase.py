"""Tests for niche/keyphrase extraction from titles and tags."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from yoe import keyphrase


def test_drops_stopwords_and_filler():
    labels = keyphrase.extract("How to Build a RAG Pipeline (Full Tutorial)",
                               tags=[])
    joined = " ".join(labels)
    # generic filler must not become a topic
    for junk in ("how", "to", "a", "full", "tutorial", "build"):
        assert junk not in labels
    # the actual subject survives
    assert any("rag" in l or "pipeline" in l for l in labels)


def test_tags_outrank_title_noise():
    labels = keyphrase.extract(
        "INSANE new thing you MUST see!!!",
        tags=["ai agents", "autonomous agents"])
    # creator-labelled multi-word tags become the top niche labels
    assert "ai agents" in labels
    assert labels[0] in ("ai agents", "autonomous agents")


def test_bigrams_beat_unigrams_for_specificity():
    labels = keyphrase.extract("Gemini Flash speed test", tags=[])
    # a specific bigram should appear (not just lone words)
    assert any(" " in l for l in labels)


def test_corpus_breadth_favors_shared_phrases():
    # "ai agents" appears across 3 videos → should surface as a shared niche
    docs = [
        ("Building AI agents with tools", ["ai agents"]),
        ("AI agents that browse the web", ["ai agents"]),
        ("Why AI agents fail in production", ["ai agents"]),
        ("A totally unrelated cooking pasta recipe", ["pasta"]),
    ]
    labels = keyphrase.extract_corpus_topics(docs)
    for i in range(3):
        assert "ai agents" in labels[i]
    # the outlier doc doesn't get the shared niche
    assert "ai agents" not in labels[3]


def test_never_empty():
    assert keyphrase.extract("", tags=[]) == ["uncategorized"]
    assert keyphrase.extract("12345 2024", tags=[]) == ["uncategorized"]
