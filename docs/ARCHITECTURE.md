# Architecture

## Status (honest)
- **Built & verified now:** the intelligence core — provider abstraction +
  mock provider with fixtures, anomaly engine, trend/niche engine, opportunity
  scoring, an end-to-end pipeline, a runnable demo and a passing test suite.
- **Not yet built:** FastAPI API + auth, Postgres/SQLAlchemy persistence,
  Next.js dashboard, the video factory (LLM/TTS/image/render), Celery/ARQ
  workers, OAuth for authorized-channel analytics, Docker Compose, CI, deploy.
  These are the remaining phases (see README roadmap).

## Design
A modular monolith with independent workers (the spec permits and prefers this
over premature microservices). Every external integration hides behind a
provider interface (`yoe/providers/base.py`) so no vendor is load-bearing — a
missing key falls back to a mock and the system keeps building.

## Intelligence loop
`collect (provider) → anomaly.score_channel → trend.analyze_topics →
opportunity.rank_opportunities → EngineReport` (see `yoe/pipeline.py`).

- **anomaly.py** — baselines (channel median, age-normalized expectation),
  velocity/acceleration from the snapshot time-series, robust MAD z-score,
  age-adjusted breakout ratio, explainable classification.
- **trend.py** — topic clustering; a trend is separated from one-off noise by
  BREADTH (independent channels) + YOUTH (share of recent videos), not raw views.
- **opportunity.py** — the spec's weighted dimensions with a per-dimension
  breakdown, confidence, evidence and reasons-against (uncertainty never hidden).
