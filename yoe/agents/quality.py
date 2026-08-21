"""
Quality gate — automated QC before anything is shown for human review.

Checks originality, structure, retention coverage, thumbnail/title consistency,
repetition and policy risk. Minimum passing score is 80; on failure it returns
explicit reasons so the relevant stage can regenerate (per the spec). Nothing
auto-publishes — publishing is a separate, disabled-by-default step.
"""

from __future__ import annotations

import re

from .schemas import Concept, QualityCheck, QualityResult, Script

MIN_SCORE = 80.0

# Words that read as deceptive clickbait vs truthful curiosity.
_DECEPTIVE = re.compile(r"\b(you won'?t believe|shocking|gone wrong|100% guaranteed|"
                        r"doctors hate|secret they don'?t want)\b", re.IGNORECASE)


def _repetition_score(script: Script) -> float:
    text = " ".join(b for s in script.sections for b in s.get("beats", [])).lower()
    words = re.findall(r"[a-z']+", text)
    if not words:
        return 0.0
    unique_ratio = len(set(words)) / len(words)
    return round(min(100.0, unique_ratio * 120), 1)  # high variety → high score


def run_gate(concept: Concept, script: Script, originality: float) -> QualityResult:
    checks: list[QualityCheck] = []

    # 1. Originality (0..1 from the concept engine → 0..100)
    checks.append(QualityCheck("originality", originality >= 0.5, round(originality * 100, 1),
                               f"originality vs source titles = {originality}"))

    # 2. Structure: has a hook, multiple sections, an outro
    structured = bool(script.hook) and len(script.sections) >= 3 and bool(script.outro)
    checks.append(QualityCheck("structure", structured, 100.0 if structured else 40.0,
                               f"{len(script.sections)} sections, hook={bool(script.hook)}"))

    # 3. Retention coverage: distinct retention devices used
    devices = {s.get("retention_device") for s in script.sections if s.get("retention_device")}
    ret_ok = len(devices) >= 3
    checks.append(QualityCheck("retention", ret_ok, min(100.0, len(devices) * 25),
                               f"{len(devices)} distinct retention devices"))

    # 4. Thumbnail/title consistency: concept carries both, non-empty
    tt_ok = bool(concept.thumbnail_concept) and bool(concept.title_hypotheses)
    checks.append(QualityCheck("thumbnail_title", tt_ok, 100.0 if tt_ok else 50.0,
                               "thumbnail concept and title hypotheses present"))

    # 5. Repetition / filler
    rep = _repetition_score(script)
    checks.append(QualityCheck("repetition", rep >= 60, rep, f"lexical variety score {rep}"))

    # 6. Policy / deceptive-clickbait risk
    blob = " ".join([concept.hook, script.hook] + concept.title_hypotheses)
    deceptive = bool(_DECEPTIVE.search(blob))
    checks.append(QualityCheck("policy", not deceptive, 100.0 if not deceptive else 30.0,
                               "deceptive-clickbait phrasing" if deceptive else "no deceptive phrasing"))

    score = round(sum(c.score for c in checks) / len(checks), 1)
    reasons = [f"{c.name}: {c.note}" for c in checks if not c.passed]
    passed = score >= MIN_SCORE and all(c.passed for c in checks
                                        if c.name in ("originality", "policy"))
    return QualityResult(passed=passed, score=score, checks=checks, reasons=reasons)
