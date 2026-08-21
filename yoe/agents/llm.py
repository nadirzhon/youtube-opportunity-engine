"""
LLM provider abstraction — the content agents never couple to a vendor.

`generate(task, context)` returns a structured dict. The MockLLMProvider builds
deterministic, context-derived output so the whole content pipeline runs, is
testable, and reflects the actual opportunity — with no API key. The real
provider (Anthropic/OpenAI) is a thin adapter that asks the model for JSON.

Mock output is structurally correct placeholder content, not model-quality
prose — swap in a real key for that. The architecture and the flow are real.
"""

from __future__ import annotations

from typing import Any, Protocol


class LLMProvider(Protocol):
    is_mock: bool
    def generate(self, task: str, context: dict[str, Any]) -> dict[str, Any]: ...


class MockLLMProvider:
    is_mock = True

    def generate(self, task: str, context: dict[str, Any]) -> dict[str, Any]:
        fn = getattr(self, f"_{task}", None)
        if fn is None:
            return {"error": f"unknown task {task}"}
        return fn(context)

    # -- research ---------------------------------------------------------
    def _research(self, ctx: dict[str, Any]) -> dict[str, Any]:
        topic = ctx.get("topic", "the topic")
        return {
            "audience_desire": f"Viewers interested in {topic} want a clear, practical answer they can act on today.",
            "emotional_trigger": "fear of falling behind + curiosity about a fast-moving space",
            "content_gap": f"Most {topic} videos over-explain the basics; few show a concrete, tested walkthrough.",
            "recommended_angle": f"A hands-on '{topic} in practice' walkthrough with a real example and the mistakes to avoid.",
            "oversupplied_angles": ["generic explainer", "news reaction", "top-10 list"],
            "risks": ["topic may be near saturation", "requires a credible concrete example"],
        }

    # -- concepts ---------------------------------------------------------
    def _concepts(self, ctx: dict[str, Any]) -> dict[str, Any]:
        topic = ctx.get("topic", "the topic")
        angle = ctx.get("recommended_angle", "")
        n = int(ctx.get("n", 10))
        base = [
            ("I tested {t} so you don't have to", "curious beginners",
             "you'll know if {t} is worth your time in 8 minutes"),
            ("The one mistake everyone makes with {t}", "practitioners",
             "you'll avoid the failure that wastes weeks"),
            ("{t}, explained with a real example (not theory)", "hands-on learners",
             "you'll follow along and build it yourself"),
            ("Why {t} breaks in production — and the fix", "professionals",
             "you'll ship it without the silent failure"),
            ("{t} from zero to working in one video", "newcomers",
             "you'll have a working result by the end"),
        ]
        concepts = []
        for i in range(n):
            tmpl = base[i % len(base)]
            concepts.append({
                "premise": f"A concrete, tested take on {topic} for {tmpl[1]}.",
                "title": tmpl[0].format(t=topic),
                "target_viewer": tmpl[1],
                "viewer_promise": tmpl[2].format(t=topic),
                "unique_angle": angle or f"a concrete, tested take on {topic}",
                "hook": f"Everyone talks about {topic}. Almost no one shows it actually working.",
                "story_arc": ["hook + promise", "the common approach and why it falls short",
                              "the concrete example", "the pitfall + fix", "payoff + recap"],
                "thumbnail_concept": f"a real screen of {topic} working, one bold 3-word overlay",
                "duration_sec": 480 + (i % 3) * 120,
            })
        return {"concepts": concepts}

    # -- script -----------------------------------------------------------
    def _script(self, ctx: dict[str, Any]) -> dict[str, Any]:
        topic = ctx.get("topic", "the topic")
        hook = ctx.get("hook", f"Here's what nobody shows you about {topic}.")
        arc = ctx.get("story_arc", ["hook", "context", "example", "pitfall", "payoff"])
        sections = []
        for i, beat in enumerate(arc):
            sections.append({
                "heading": beat,
                "beats": [f"{beat}: set up the point about {topic} concretely.",
                          "give the specific detail / example.",
                          "land the takeaway before moving on."],
                "retention_device": ["open loop", "pattern interrupt", "visual change",
                                      "controlled reveal", "payoff"][i % 5],
            })
        return {
            "hook": hook,
            "sections": sections,
            "outro": "Recap the one thing to remember, then a genuine question to drive comments.",
        }
