"""
Keyphrase / niche extraction from titles and tags (pure stdlib).

YouTube's `topicCategories` are Wikipedia-level buckets ("Technology",
"Knowledge") — far too coarse to be an *opportunity*. The real niche lives in the
words creators actually use: the video's **tags** (creator-labelled topics, the
highest-signal source we were ignoring) and the salient **n-grams of the title**.

This module turns (title, tags) across a corpus into per-video niche labels:

  1. tokenize, drop stopwords + generic YouTube filler ("official", "part 2")
  2. build candidate phrases: cleaned tags + title unigrams/bigrams/trigrams
  3. score each phrase by source weight (tag > trigram > bigram > unigram),
     a length bonus (specific beats generic), and **corpus breadth** — a phrase
     shared across many videos/channels is exactly an emerging niche, so shared
     phrases are favoured (TF-IDF's inverse intuition, flipped for trend-finding)
  4. keep each video's top-k labels

Stateless per phrase, but the corpus pass gives the breadth signal the trend
engine then turns into stages. Deterministic → testable.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

# Generic words that carry no topic signal — English stopwords plus YouTube filler.
_STOP = {
    "the", "a", "an", "and", "or", "but", "if", "then", "of", "to", "in", "on",
    "for", "with", "at", "by", "from", "up", "as", "is", "are", "was", "were",
    "be", "been", "being", "it", "its", "this", "that", "these", "those", "i",
    "you", "he", "she", "we", "they", "my", "your", "our", "their", "how", "why",
    "what", "when", "where", "who", "which", "do", "does", "did", "can", "will",
    "just", "not", "no", "yes", "so", "than", "too", "very", "s", "t", "re",
    # YouTube filler
    "video", "videos", "official", "full", "new", "latest", "watch", "subscribe",
    "channel", "episode", "ep", "part", "vs", "ft", "feat", "live", "trailer",
    "review", "reviews", "best", "top", "vlog", "shorts", "short", "update",
    "tutorial", "guide", "explained", "everything", "need", "know", "get", "got",
    "make", "made", "using", "use", "vs.", "into", "out", "about", "more", "now",
    # generic tutorial-action verbs (the action, not the topic)
    "build", "building", "create", "creating", "made", "makes", "making",
    "learn", "learning", "master", "mastering", "understand", "understanding",
    "try", "trying", "start", "starting", "setup", "set", "add", "adding",
}

_TOKEN = re.compile(r"[a-z0-9][a-z0-9'+.#-]*")


def _tokens(text: str) -> list[str]:
    toks = _TOKEN.findall((text or "").lower())
    out: list[str] = []
    for t in toks:
        t = t.strip("'.-")
        if len(t) < 2:
            continue
        if t in _STOP:
            continue
        if t.isdigit():          # bare years/numbers aren't topics
            continue
        out.append(t)
    return out


def _ngrams(tokens: list[str], n: int) -> list[str]:
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def _norm_tag(tag: str) -> str:
    t = " ".join(_tokens(tag))
    return t.strip()


def candidate_phrases(title: str, tags: list[str] | None = None) -> dict[str, float]:
    """Candidate phrases for one video → base source weight (before corpus/idf).
    Tags outrank title n-grams; longer n-grams outrank shorter (more specific)."""
    tags = tags or []
    cands: dict[str, float] = {}

    def bump(phrase: str, w: float) -> None:
        # 1..4 words: a lone word is generic, a 5+-word "phrase" is usually a junk
        # tag (SEO soup / channel boilerplate), neither is a clean niche label.
        if phrase and phrase not in _STOP and 1 <= phrase.count(" ") + 1 <= 4:
            cands[phrase] = max(cands.get(phrase, 0.0), w)

    for tag in tags[:15]:
        nt = _norm_tag(tag)
        if nt and " " in nt:      # multi-word tags are the richest niche labels
            bump(nt, 3.2)
        elif nt:
            bump(nt, 2.4)

    # Title n-grams: unigrams + bigrams only. Title *trigrams* are almost always
    # fragments of a sentence ("deepseek back silicon"), not a niche — trigrams
    # are trusted only from tags, where they're deliberate labels.
    toks = _tokens(title)
    for p in _ngrams(toks, 2):
        bump(p, 2.0)
    for u in toks:
        bump(u, 1.0)
    return cands


def extract_corpus_topics(docs: list[tuple[str, list[str]]], *, top_per_doc: int = 4,
                          min_phrase_docs: int = 1) -> list[list[str]]:
    """Assign each (title, tags) doc its top-k niche labels.

    Scoring blends the phrase's source weight, a length bonus, and **corpus
    breadth** (how many docs share it) — because a phrase several videos share is
    a candidate niche, while a one-off phrase usually isn't. Returns a list of
    label-lists aligned with `docs`."""
    per_doc_cands = [candidate_phrases(t, tags) for t, tags in docs]

    # document frequency: how many docs contain each phrase (breadth proxy)
    df: dict[str, int] = defaultdict(int)
    for cands in per_doc_cands:
        for phrase in cands:
            df[phrase] += 1

    # Boilerplate/branding filter: within one corpus (here, a channel's uploads) a
    # phrase on most videos is branding ("alex friedman"), not a niche. Drop it.
    n = len(docs)
    boilerplate = {p for p, d in df.items() if n >= 8 and d >= 0.7 * n}

    out: list[list[str]] = []
    for cands in per_doc_cands:
        scored = []
        for phrase, base in cands.items():
            d = df[phrase]
            if d < min_phrase_docs or phrase in boilerplate:
                continue
            length_bonus = 1.0 + 0.25 * (phrase.count(" "))     # bigrams/trigrams win
            breadth = 1.0 + math.log(d)                          # shared phrases win
            scored.append((phrase, base * length_bonus * breadth))
        scored.sort(key=lambda x: x[1], reverse=True)
        out.append([p for p, _ in scored[:top_per_doc]] or ["uncategorized"])
    return out


def extract(title: str, tags: list[str] | None = None, *, top_k: int = 4) -> list[str]:
    """Single-video convenience (no corpus breadth signal)."""
    return extract_corpus_topics([(title, tags or [])], top_per_doc=top_k)[0]
