"""
The advisor — turns accumulated signal into concrete advice + a ready brief.

This is the "just tell me what to do and hand me the video" layer. From the
scored opportunities (enriched with monetization economics) and the channels you
already run, it emits ranked ACTION recommendations:

  * launch_channel — a high-profit niche no existing profile covers → start one
  * make_video     — a niche one of your channels owns → make this next
  * double_down    — a proven niche with a fresh opening

Each recommendation carries the *why* (momentum, stage, RPM, evidence) and a
creative brief: the color palette / art direction (from `brand`), with the full
script + hooks + thumbnail directions attached for the top pick (built on demand
by the caller via `build_opportunity`, so routine advice stays cheap).

Pure stdlib here; the heavy generation is opt-in. Deterministic given inputs.
"""

from __future__ import annotations

from . import brand, economics

# Below this profit priority we don't recommend acting yet.
DEFAULT_MIN_PRIORITY = 20.0


def _why(opp: dict, econ: dict, covered: bool) -> list[str]:
    reasons = []
    stage = opp.get("stage", "?")
    reasons.append(f"Momentum: stage '{stage}', score {opp.get('score')}, "
                   f"confidence {opp.get('confidence')}.")
    reasons.append(f"Niche '{econ['niche_bucket']}' pays ~${econ['rpm_mid']} RPM "
                   f"(${econ['rpm_low']}–${econ['rpm_high']}).")
    reasons.append(f"Profit priority {econ['profit_priority']}/100 — {econ['worth_generating']}")
    for ev in (opp.get("evidence") or [])[:2]:
        reasons.append(f"Evidence: {ev}")
    if not covered:
        reasons.append("No channel of yours covers this niche yet — greenfield.")
    return reasons


def _action(covered: bool, econ: dict, stage: str) -> str:
    if not covered:
        return "launch_channel"
    if stage in ("saturated", "mainstream", "declining"):
        return "double_down"          # you own it; press an existing edge
    return "make_video"


def recommend(opportunities: list[dict], *, profiles=None,
              min_priority: float = DEFAULT_MIN_PRIORITY, limit: int = 10) -> list[dict]:
    """Ranked action recommendations with a creative brief each. `opportunities`
    are Opportunity.to_dict() items; `profiles` is a list of ChannelProfile."""
    profiles = profiles or []
    recs = []
    for o in opportunities:
        enriched = economics.enrich(o)
        econ = enriched["economics"]
        if econ["profit_priority"] < min_priority:
            continue
        covered = any(p.matches(o["topic"]) for p in profiles)
        owner = next((p.id for p in profiles if p.matches(o["topic"])), None)
        recs.append({
            "action": _action(covered, econ, o.get("stage", "")),
            "topic": o["topic"],
            "niche_bucket": econ["niche_bucket"],
            "score": o.get("score"),
            "confidence": o.get("confidence"),
            "stage": o.get("stage"),
            "rpm_mid": econ["rpm_mid"],
            "profit_priority": econ["profit_priority"],
            "worth_generating": econ["worth_generating"],
            "covered_by_profile": owner,
            "why": _why(o, econ, covered),
            "brief": brand.style_brief(o["topic"]),   # palette + art direction
        })
    recs.sort(key=lambda r: r["profit_priority"], reverse=True)
    return recs[:limit]


def headline(recs: list[dict]) -> str:
    """One-line 'do this next' summary of the top recommendation."""
    if not recs:
        return "Nothing actionable yet — let the engine accumulate more data."
    r = recs[0]
    verb = {"launch_channel": "Launch a channel for",
            "make_video": "Make your next video on",
            "double_down": "Double down on"}.get(r["action"], "Act on")
    return (f"{verb} '{r['topic']}' ({r['niche_bucket']}, ~${r['rpm_mid']} RPM, "
            f"priority {r['profit_priority']}/100).")
