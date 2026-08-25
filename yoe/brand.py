"""
Visual style / brand brief — the "color palette" half of "make me everything".

A ready-to-shoot brief needs a look, not just words. This maps a topic's niche to
a coherent visual system: a color palette (primary / secondary / accent /
background / text as hex), a mood, a font style and an energy level — the things
a thumbnail and video need to feel like a real channel, not a template.

Deterministic (niche → palette), pure stdlib. It's a strong opinionated starting
point a human or an image model can run with; not a replacement for a designer.
"""

from __future__ import annotations

from . import economics

# One curated palette per niche bucket. Hexes chosen for contrast + on-brand mood.
_PALETTES: dict[str, dict] = {
    "personal_finance": {"mood": "trust · wealth · calm authority", "energy": "medium",
                         "font_style": "clean geometric sans (Inter/Poppins)",
                         "primary": "#0B6E4F", "secondary": "#0A2540", "accent": "#F2C94C",
                         "background": "#0A1F1A", "text": "#F5F7F5"},
    "business_make_money": {"mood": "ambition · momentum · bold", "energy": "high",
                            "font_style": "heavy grotesk (Archivo/Montserrat Black)",
                            "primary": "#1B9AAA", "secondary": "#0B132B", "accent": "#FFC42E",
                            "background": "#0B132B", "text": "#FFFFFF"},
    "crypto": {"mood": "electric · futuristic · risk", "energy": "high",
               "font_style": "techno mono-accent (Space Grotesk)",
               "primary": "#F7931A", "secondary": "#111827", "accent": "#00E0FF",
               "background": "#0A0A0F", "text": "#EDEDED"},
    "ai_tools": {"mood": "cutting-edge · clean · a little uncanny", "energy": "high",
                 "font_style": "modern sans + mono accents",
                 "primary": "#6C5CE7", "secondary": "#00D1FF", "accent": "#00FFA3",
                 "background": "#0B0B14", "text": "#F2F2F7"},
    "tech_software": {"mood": "precise · developer · dark-mode native", "energy": "medium",
                      "font_style": "mono + neutral sans",
                      "primary": "#2F80ED", "secondary": "#1A1B26", "accent": "#56D364",
                      "background": "#0D1117", "text": "#E6EDF3"},
    "education_howto": {"mood": "friendly · clear · trustworthy", "energy": "medium",
                        "font_style": "rounded humanist sans (Nunito)",
                        "primary": "#2D9CDB", "secondary": "#2F3640", "accent": "#F2994A",
                        "background": "#FAFAFA", "text": "#22252A"},
    "health_fitness": {"mood": "fresh · energetic · clean", "energy": "high",
                       "font_style": "bold condensed sans",
                       "primary": "#27AE60", "secondary": "#145A32", "accent": "#F2C94C",
                       "background": "#F4FBF6", "text": "#12261B"},
    "gaming": {"mood": "neon · adrenaline · night", "energy": "very high",
               "font_style": "aggressive display (Rajdhani)",
               "primary": "#B026FF", "secondary": "#0A0A12", "accent": "#00FFD1",
               "background": "#08080F", "text": "#F0F0FF"},
    "entertainment": {"mood": "vibrant · playful · pop", "energy": "very high",
                      "font_style": "chunky rounded display",
                      "primary": "#FF4D6D", "secondary": "#22162B", "accent": "#FFD93D",
                      "background": "#160E1E", "text": "#FFFFFF"},
    "food_cooking": {"mood": "warm · appetizing · homey", "energy": "medium",
                     "font_style": "friendly serif + sans",
                     "primary": "#E2711D", "secondary": "#4A2500", "accent": "#F6C453",
                     "background": "#FFF8F0", "text": "#2B1C10"},
    "travel": {"mood": "wanderlust · airy · golden-hour", "energy": "medium",
               "font_style": "elegant sans + script accent",
               "primary": "#2A9D8F", "secondary": "#264653", "accent": "#E9C46A",
               "background": "#F7FBFB", "text": "#1B2B2A"},
    "other": {"mood": "clean · versatile · modern", "energy": "medium",
              "font_style": "neutral geometric sans",
              "primary": "#3E7CB1", "secondary": "#1D2A35", "accent": "#F4A259",
              "background": "#0F1620", "text": "#EEF2F6"},
}


def palette_for(topic: str) -> dict:
    """The visual system for a topic, derived from its monetization niche."""
    bucket = economics.classify_niche(topic)
    p = _PALETTES.get(bucket, _PALETTES["other"])
    return {"niche_bucket": bucket, **p,
            "swatches": [p["primary"], p["secondary"], p["accent"],
                         p["background"], p["text"]]}


def style_brief(topic: str) -> dict:
    """A compact art-direction brief a thumbnail/video can be built from."""
    pal = palette_for(topic)
    return {
        "palette": pal,
        "art_direction": (f"{pal['mood']} · {pal['energy']} energy · {pal['font_style']}. "
                          f"Lead with {pal['primary']} on {pal['background']}, "
                          f"pop key elements in {pal['accent']}."),
    }
