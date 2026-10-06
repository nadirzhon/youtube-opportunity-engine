# YouTube Opportunity Engine

**An autonomous intelligence pipeline for discovering emerging YouTube opportunities.**

The engine analyzes abnormal video performance, trend breadth, topic maturity and historical outcomes to rank opportunities with evidence, confidence and reasons against.

## Why it is interesting

This is an example of AI/product engineering beyond a chat interface:

```
data collection
    ↓
statistical baselines
    ↓
anomaly detection
    ↓
trend / niche analysis
    ↓
opportunity scoring
    ↓
research + content build
    ↓
publish / measure
    ↓
feedback
    ↓
learning
    └──────────────→ next opportunity
```

The system is designed as a closed learning loop rather than a one-shot recommendation script.

## What works

- provider abstraction with deterministic mock data
- channel and video baselines
- age-normalized performance expectations
- velocity and acceleration analysis
- robust MAD-based anomaly scoring
- breakout classification
- topic clustering and trend stages
- opportunity scoring with per-dimension explanations
- confidence and reasons-against
- FastAPI API
- persistence with SQLite or PostgreSQL
- Docker deployment
- autonomous worker
- content research/concept/script/thumbnail pipeline
- feedback and learning loop
- Thompson-sampling bandit
- self-calibrating scoring weights
- API-key/RBAC hardening and CI

## Example

```text
ai-agents-security
score: 71.8 / 100
confidence: 1.0
stage: accelerating

drivers:
  trend_velocity       14.98
  anomaly_strength     14.21
  competition_inverse  13.00
```

The output is intentionally explainable: the system should show **why** an opportunity was ranked highly and what evidence argues against it.

## Run locally

The intelligence core can run without external services:

```bash
python -m yoe.demo
```

API:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-api.txt

uvicorn yoe.api:app --reload
```

Docker:

```bash
docker compose up -d --build
```

Tests:

```bash
pytest -q
```

## 24/7 architecture

The API and autonomous worker run as separate long-lived processes.

The worker:

1. discovers/expands the watch set;
2. collects snapshots under quota;
3. updates historical state;
4. detects opportunities;
5. optionally builds the strongest concept;
6. records outcomes;
7. updates the learning model;
8. emits a heartbeat.

Failures are isolated with backoff and graceful shutdown. Without external credentials, the system falls back to mock data so the core remains runnable.

## Architecture

```
yoe/
├── anomaly.py
├── trend.py
├── opportunity.py
├── pipeline.py
├── store.py
├── providers/
├── learning/
├── agents/
├── api.py
└── worker.py

tests/
deploy/
docs/
sample-data/
```

## Engineering highlights

- statistics + ML/learning instead of prompt-only ranking
- explicit provider abstractions
- deterministic core with optional AI components
- explainable scoring
- persistent historical state
- autonomous background processing
- feedback-driven calibration
- API + Docker + systemd deployment
- tests across core, API, persistence, agents and worker

## Honest status

The repository contains a runnable, tested system. Real-scale operation requires external provider credentials and media/LLM services; those dependencies are deliberately kept behind interfaces.

## License

MIT © nadirzhon
