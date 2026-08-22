"""
Feedback loop (Phase 7 — closure).

This is the join that makes the system *compound*: it turns a produced package
plus its measured performance into a stored experiment, and turns the stored
experiments back into a bias on the next creative choice. Without this file the
bandit and insights are islands; with it, every publish makes the next concept
selection a little smarter.

Flow:
    build_opportunity → package
    (publish, then observe views/retention) → performance in 0..1
    record_publication(conn, package, performance)         # remember
    learned_boost(load_experiments(conn, niche)) → scorer  # recall
    build_opportunity(..., experience=scorer)              # apply

Pure stdlib. `performance` is a caller-normalized 0..1 outcome (e.g. views vs the
channel's age-normalized expectation, clipped) so niches stay comparable.
"""

from __future__ import annotations

from collections import defaultdict

from .bandit import Bandit
from .insights import niche_priors


# ---------------------------------------------------------------------------
# Characterize a concept the same way experiments are keyed, so what we store
# lines up with what insights()/niche_priors() read back.
# ---------------------------------------------------------------------------
def classify_hook(hook: str) -> str:
    h = (hook or "").lower()
    if "?" in h:
        return "question"
    if any(w in h for w in ("i ", "my ", "we ", "story", "when ")):
        return "story"
    if any(w in h for w in ("never", "everyone", "nobody", "stop", "the truth")):
        return "bold_claim"
    return "direct"


def classify_title(title: str) -> str:
    t = (title or "").lower()
    if "?" in t:
        return "question"
    if any(w in t for w in ("how ", "how to", "guide", "explained")):
        return "howto"
    if any(ch.isdigit() for ch in t) or t.startswith(("top ", "the ")):
        return "list"
    return "statement"


def package_to_experiment(package, performance: float, *,
                          publish_hour: int | None = None,
                          video_url: str | None = None) -> dict:
    """Derive the experiment row from a built OpportunityPackage."""
    c = package.chosen
    title = c.title_hypotheses[0] if c.title_hypotheses else package.topic
    return {
        "topic": package.topic,
        "niche": package.topic,                       # topic is the niche key here
        "angle": c.unique_angle or "unspecified",
        "hook_style": classify_hook(c.hook),
        "title_structure": classify_title(title),
        "title": title,
        "duration_sec": int(c.suggested_duration_sec or 0),
        "publish_hour": publish_hour,
        "performance": max(0.0, min(1.0, float(performance))),
        "video_url": video_url,
    }


def record_publication(conn, package, performance: float, *,
                       publish_hour: int | None = None,
                       video_url: str | None = None) -> int:
    """Persist one produced-and-measured asset as an experiment. Returns its id."""
    from .. import store  # local import avoids a cycle at module load
    exp = package_to_experiment(package, performance,
                                publish_hour=publish_hour, video_url=video_url)
    return store.save_experiment(conn, exp)


# ---------------------------------------------------------------------------
# Recall: turn accumulated experiments into a scorer that biases concept choice.
# ---------------------------------------------------------------------------
def learned_boost(experiments: list[dict], *, attr: str = "angle", seed: int = 7):
    """Return a scorer f(angle_value) -> boost in ~[-0.5, 0.5], learned from
    history. Priors from niche_priors() are aggregated across niches into a Beta
    arm per attribute value; the scorer uses the posterior *mean* (exploitation).
    A warm-started Thompson-sampling bandit is attached as ``scorer.bandit`` for
    callers that want to explore (sample) rather than exploit."""
    priors = niche_priors(experiments, attr)
    # flatten priors across niches into per-value Beta arms
    agg: dict[str, list[float]] = defaultdict(lambda: [1.0, 1.0])
    for _niche, vals in priors.items():
        for val, (a, b) in vals.items():
            agg[val][0] += a - 1.0          # accumulate successes above the 1.0 prior
            agg[val][1] += b - 1.0          # accumulate failures above the 1.0 prior
    arms: dict[str, tuple[float, float]] = {v: (a, b) for v, (a, b) in agg.items()}

    bandit = Bandit(seed=seed)
    for val, (a, b) in arms.items():
        bandit.set_prior(val, a, b)

    def scorer(angle_value: str) -> float:
        if angle_value not in arms:
            return 0.0                      # unseen angle → neutral (explore)
        a, b = arms[angle_value]
        mean = a / (a + b)                  # expected performance for this angle
        return round((mean - 0.5), 3)       # >0 if historically above average

    scorer.arms = dict(arms)                # exposed for inspection/tests
    scorer.bandit = bandit                  # exposed for Thompson-sampling exploration
    return scorer


def rerank_with_experience(concepts: list, scorer) -> list:
    """Re-rank concepts in place using a learned angle scorer, then re-sort.
    The learned signal nudges rank_score but never overrides originality gating
    (already applied upstream)."""
    for c in concepts:
        boost = scorer(c.unique_angle or "unspecified")
        c.rank_score = round(c.rank_score + 0.3 * boost, 3)
    concepts.sort(key=lambda c: c.rank_score, reverse=True)
    return concepts
