"""
Monetization economics — turn "is this growing?" into "is this worth making?".

A fast-growing topic is worthless if it pays nothing. This module attaches an
**estimated RPM** (revenue per 1000 monetized views, USD) to a niche and combines
it with the opportunity score into a **profit priority** — so the engine ranks
what is both rising AND monetizable, not just rising.

Honesty about RPM: YouTube does NOT expose other creators' revenue — real RPM is
private and only known once *you* monetize. These are transparent industry-range
estimates by niche (2024-era public figures), used as a prior. Once your own
channels report real RPM, feed it back and this becomes data, not a guess
(same pattern as the self-calibrating scorer).

Pure stdlib, deterministic.
"""

from __future__ import annotations

# Estimated RPM ranges by niche bucket (USD per 1000 monetized views).
# Conservative public industry ranges; midpoint used for ranking.
RPM_BUCKETS: dict[str, tuple[float, float]] = {
    "personal_finance": (12.0, 40.0),
    "business_make_money": (10.0, 25.0),
    "real_estate": (10.0, 22.0),
    "crypto": (7.0, 20.0),
    "marketing_seo": (8.0, 18.0),
    "insurance_legal": (15.0, 45.0),
    "tech_software": (6.0, 15.0),
    "ai_tools": (7.0, 18.0),
    "education_howto": (4.0, 10.0),
    "health_fitness": (4.0, 9.0),
    "productivity": (5.0, 12.0),
    "travel": (4.0, 8.0),
    "beauty_fashion": (4.0, 9.0),
    "food_cooking": (3.0, 7.0),
    "automotive": (4.0, 9.0),
    "news_politics": (3.0, 6.0),
    "sports": (2.0, 6.0),
    "gaming": (2.0, 5.0),
    "entertainment": (1.5, 4.0),
    "music": (1.0, 3.0),
    "kids": (1.0, 4.0),          # note: COPPA restrictions cut monetization
    "other": (2.0, 6.0),
}

# Keyword → bucket. First match wins; checked against the topic + its words.
_KEYWORDS: list[tuple[str, str]] = [
    ("invest", "personal_finance"), ("stock", "personal_finance"),
    ("money", "business_make_money"), ("finance", "personal_finance"),
    ("dividend", "personal_finance"), ("trading", "personal_finance"),
    ("passive income", "business_make_money"), ("dropship", "business_make_money"),
    ("ecommerce", "business_make_money"), ("business", "business_make_money"),
    ("startup", "business_make_money"), ("freelanc", "business_make_money"),
    ("real estate", "real_estate"), ("mortgage", "real_estate"),
    ("crypto", "crypto"), ("bitcoin", "crypto"), ("ethereum", "crypto"), ("web3", "crypto"),
    ("seo", "marketing_seo"), ("marketing", "marketing_seo"), ("ads", "marketing_seo"),
    ("insurance", "insurance_legal"), ("lawyer", "insurance_legal"), ("legal", "insurance_legal"),
    ("ai ", "ai_tools"), ("ai agent", "ai_tools"), ("llm", "ai_tools"),
    ("chatgpt", "ai_tools"), ("machine learning", "ai_tools"), ("gpt", "ai_tools"),
    ("saas", "tech_software"), ("software", "tech_software"), ("coding", "tech_software"),
    ("programming", "tech_software"), ("developer", "tech_software"), ("python", "tech_software"),
    ("javascript", "tech_software"), ("tech", "tech_software"), ("pc ", "tech_software"),
    ("productivity", "productivity"), ("notion", "productivity"),
    ("workout", "health_fitness"), ("fitness", "health_fitness"), ("diet", "health_fitness"),
    ("nutrition", "health_fitness"), ("weight loss", "health_fitness"),
    ("travel", "travel"), ("flight", "travel"),
    ("makeup", "beauty_fashion"), ("skincare", "beauty_fashion"), ("fashion", "beauty_fashion"),
    ("recipe", "food_cooking"), ("cooking", "food_cooking"), ("food", "food_cooking"),
    ("car", "automotive"), ("tesla", "automotive"), ("ev ", "automotive"),
    ("news", "news_politics"), ("politic", "news_politics"),
    ("football", "sports"), ("nba", "sports"), ("soccer", "sports"), ("ufc", "sports"),
    ("game", "gaming"), ("gaming", "gaming"), ("ps5", "gaming"), ("xbox", "gaming"),
    ("minecraft", "gaming"), ("fortnite", "gaming"), ("roblox", "gaming"),
    ("movie", "entertainment"), ("trailer", "entertainment"), ("reaction", "entertainment"),
    ("disney", "entertainment"), ("marvel", "entertainment"), ("netflix", "entertainment"),
    ("music", "music"), ("song", "music"), ("mv", "music"), ("kpop", "music"),
    ("cartoon", "kids"), ("nursery", "kids"), ("kids", "kids"),
]

_MAX_RPM_MID = max((lo + hi) / 2 for lo, hi in RPM_BUCKETS.values())


def classify_niche(topic: str) -> str:
    t = (topic or "").lower()
    for kw, bucket in _KEYWORDS:
        if kw in t:
            return bucket
    return "other"


def estimate_rpm(topic: str) -> dict:
    bucket = classify_niche(topic)
    lo, hi = RPM_BUCKETS[bucket]
    mid = round((lo + hi) / 2, 1)
    return {"niche_bucket": bucket, "rpm_low": lo, "rpm_high": hi, "rpm_mid": mid}


def profit_priority(opportunity_score: float, rpm_mid: float, confidence: float = 1.0) -> float:
    """A 0..100 priority that rewards opportunity strength AND pay. Score and the
    RPM (normalized against the best-paying niche) are combined, tempered by
    confidence — so a strong, well-paid, well-evidenced topic ranks highest."""
    rpm_norm = min(1.0, rpm_mid / _MAX_RPM_MID)
    return round(opportunity_score * (0.4 + 0.6 * rpm_norm) * (0.5 + 0.5 * confidence), 1)


def enrich(opportunity: dict) -> dict:
    """Attach rpm estimate + profit priority + a go/no-go verdict to an
    opportunity dict (from Opportunity.to_dict())."""
    rpm = estimate_rpm(opportunity["topic"])
    score = float(opportunity.get("score", 0.0))
    conf = float(opportunity.get("confidence", 1.0))
    priority = profit_priority(score, rpm["rpm_mid"], conf)
    out = dict(opportunity)
    out["economics"] = {
        **rpm,
        "profit_priority": priority,
        "worth_generating": _verdict(score, rpm["rpm_mid"], conf),
    }
    return out


def _verdict(score: float, rpm_mid: float, conf: float) -> str:
    if score >= 55 and rpm_mid >= 6 and conf >= 0.5:
        return "yes — rising in a monetizable niche."
    if score >= 55 and rpm_mid < 6:
        return "risky — growing, but the niche pays little (low RPM)."
    if score < 45:
        return "no — not enough momentum yet."
    return "maybe — watch; borderline on growth or pay."


def rank_by_profit(opportunities: list[dict]) -> list[dict]:
    """Enrich and sort opportunities by profit priority (rising × monetizable)."""
    enriched = [enrich(o) for o in opportunities]
    enriched.sort(key=lambda o: o["economics"]["profit_priority"], reverse=True)
    return enriched
