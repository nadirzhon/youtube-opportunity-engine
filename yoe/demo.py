"""End-to-end demo: run the full loop on mock fixtures and print a report.

    python -m yoe.demo
"""
from __future__ import annotations

from .pipeline import run
from .providers.mock import MockYouTubeProvider


def main() -> int:
    report = run(MockYouTubeProvider(seed=1337))

    print("\n=== YouTube Opportunity Engine — E2E (mock data) ===")
    print(f"channels: {len(report.channels)}  videos: {len(report.videos)}  "
          f"breakouts: {len(report.breakouts)}  topics: {len(report.topics)}\n")

    print("— Top breakout videos —")
    for a in report.breakouts[:5]:
        print(f"  [{a.classification.value:16}] {a.video_id}  score {a.score}")
        print(f"      {a.explanation[0]}")

    print("\n— Top opportunities —")
    for o in report.opportunities[:3]:
        print(f"  ▶ {o.topic}  score {o.score}/100  conf {o.confidence}  stage {o.stage.value}")
        print(f"     action: {o.recommended_action}")
        print(f"     evidence: {o.evidence[0]}")
        if o.reasons_against:
            print(f"     against: {o.reasons_against[0]}")
        top3 = sorted(o.breakdown.items(), key=lambda kv: kv[1], reverse=True)[:3]
        print("     top drivers: " + ", ".join(f"{k}={v}" for k, v in top3))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
