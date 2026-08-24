# YouTube Opportunity Engine

**Finds emerging YouTube opportunities before they saturate — and explains why.**

Detects statistically abnormal video performance against proper baselines,
separates repeatable topic trends from one-off viral noise, and produces
ranked, explainable opportunities with evidence and reasons against.

> **Honest status.** This repo contains a **built, tested, runnable intelligence
> core** — the part that actually decides *what's an opportunity and why*. The
> full production platform (API, dashboard, video factory, workers, deploy) is a
> multi-phase build; the roadmap below marks what's done vs remaining. Nothing
> here is faked — run the demo and the tests and see for yourself.

## What works right now (verified)

```
collect (provider) → anomaly engine → trend/niche engine → opportunity scoring → report
```

- **Provider abstraction** + a **mock provider** with deterministic fixtures
  (channels, videos, time-series snapshots, a planted breakout and a planted
  multi-channel trend) — per the spec's "no key → mock and continue" rule.
- **Anomaly engine** — channel baselines, age-normalized expectation,
  velocity/acceleration from the snapshot series, robust MAD z-score,
  age-adjusted breakout ratio, explainable classification
  (normal / interesting / breakout / extreme_breakout).
- **Trend & niche engine** — topic clustering; a real trend is separated from
  noise by **breadth** (independent channels) + **youth** (recent-video share),
  mapped to a stage (latent → emerging → accelerating → mainstream → saturated → declining).
- **Opportunity scoring** — the spec's exact weighted dimensions with a
  per-dimension breakdown, confidence, evidence and **reasons against**.
- **End-to-end pipeline + demo + test suite** (9 tests, incl. the acceptance
  scenario), pure standard library — runs anywhere, no services needed.

## Run it

```bash
# 1) The intelligence core, standalone (zero deps):
python -m yoe.demo         # end-to-end on mock data → ranked opportunities

# 2) The HTTP API (Phase 1):
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-api.txt
uvicorn yoe.api:app --reload        # http://localhost:8000/docs
curl -X POST "http://localhost:8000/scan?mock=true"
curl "http://localhost:8000/opportunities?limit=5"

# Or in Docker:
docker compose up            # API on :8000 (mock provider until YOUTUBE_API_KEY is set)

# 3) Tests (core + API):
pip install pytest httpx
pytest -q                    # 15 tests incl. acceptance scenario + API
```

### API endpoints
`GET /health` · `GET /status` (worker liveness) · `POST /scan?mock=true` · `GET /opportunities?limit=&min_score=&stage=`
· `GET /opportunities/{topic}` · `GET /breakouts` · `GET /topics`
· `POST /build/{topic}` (research→concept→thumbnails→script→quality)
· `POST /feedback/{topic}` (report measured performance — **closes the learning loop**)
· `GET /insights` (feature-importance + learned per-angle bias) · interactive docs at `/docs`.

**The learning loop, end to end:** `/build` picks the concept, biased by history;
you publish and observe views/retention; `POST /feedback/{topic}` stores the
outcome as an experiment; `GET /insights` shows what's working; and the *next*
`/build` re-ranks concepts toward angles that have actually performed. The system
compounds — the spec's stated ultimate goal.

Example output (the planted trend surfaces as the #1 opportunity):

```
▶ ai-agents-security  score 71.8/100  conf 1.0  stage accelerating
   action: Pursue now — strong, open, well-supported.
   evidence: 4 independent channels active, 20 videos.
   top drivers: trend_velocity=14.98, anomaly_strength=14.21, competition_inverse=13.0
```

## Roadmap (what this becomes)

| Phase | Scope | Status |
|---|---|---|
| Core intelligence | anomaly → trend → opportunity, mocks, tests, E2E | ✅ **done** |
| 1 · API | FastAPI over the core, real YouTube provider (mock fallback), Docker | ✅ **done** |
| 3 · Persistence | sqlite3 time-series store, collector, history-backed engine | ✅ **done** |
| 5 · AI content | research → concept → **thumbnail engine (5 scored directions, honesty gate)** → script → quality gate ("Build Opportunity"), pluggable LLM + mock | ✅ **done** |
| 2 · Scheduler + quota | adaptive sampling, quota/cost manager, budgets, backoff, cache | ✅ **done** |
| 4 · Dashboard | self-contained analytics dashboard served by the API | ✅ **done** |
| 6 · Video factory | script → scenes → voice/image/subtitle → FFmpeg draft (pluggable + mocks) | ✅ **done** |
| 7 · Learning loop | Thompson-sampling bandit, insights/feature-importance, niche priors, **closed feedback loop** (publish→measure→remember→bias next `/build`) | ✅ **done** |
| 8 · Hardening | API-key auth + RBAC, CI workflow, cost budgets | ✅ **done** |
| 9 · 24/7 runtime | autonomous worker (collect→analyze→build→learn loop), heartbeat + `/status`, graceful shutdown, error-isolated backoff, Docker/systemd deploy | ✅ **done** |
| 10 · Self-calibrating scoring | scoring weights learn from real outcomes (dimension↔performance correlation, regularized toward spec priors), `GET /calibration` | ✅ **done** |
| 11 · Postgres | same store on sqlite **or** Postgres (verified against postgres:16), compose `postgres` profile | ✅ **done** |
| — remaining | real YouTube run at scale · real media providers (TTS/image) · real LLM prose | ▫ external (needs keys) |

Each phase is a self-contained turn — the core here is the foundation
everything else calls into (`yoe/pipeline.py`).

## Run it 24/7

Two long-lived processes share one sqlite time-series store — the **api**
(dashboard + endpoints) and the **worker** (autonomous loop). Both fall back to
the mock provider with no keys, so the whole thing runs before you wire real data.

```bash
cp .env.example .env
docker compose up -d --build     # api on :8000 + worker, both restart:unless-stopped
curl localhost:8000/status       # worker heartbeat, cycles, last error, data freshness
```

The worker each cycle: collects a snapshot pass under quota → re-runs the engine on
accumulated history → (optionally) builds the top opportunity → learns from results
→ writes a heartbeat. It **never dies on a bad cycle** (error-isolated, exponential
backoff), **shuts down gracefully** on SIGTERM, and **degrades safely** (no key →
mock, over budget → skip). systemd units in `deploy/`; full guide in
[docs/DEPLOY.md](docs/DEPLOY.md).

## Non-negotiables (from the spec, honored)
- Originality only — no re-upload/mirror/copyright-evasion workflows.
- Platform compliance — official APIs, quotas, no fake engagement, no deceptive metadata.
- No hardcoded secrets (`.env.example`), provider interfaces + mocks, tests on every core subsystem.

## Layout
```
yoe/
  models.py            domain dataclasses
  providers/           base interface + mock (real YouTube provider = phase 2)
  anomaly.py           baselines, velocity/acceleration, robust scoring
  trend.py             topic clustering + trend stages
  opportunity.py       weighted scoring, breakdown, confidence, reasons-against
  pipeline.py          end-to-end orchestrator (run · run_from_store)
  store.py             time-series persistence — sqlite3 or Postgres (same API)
  keyphrase.py         niche extraction from titles + creator tags
  learning/calibration.py  self-calibrating scoring weights from real outcomes
  api.py               FastAPI app
  config.py            env settings, mock fallback
  demo.py              runnable E2E
agents/               research · concept · thumbnail engine · script · quality gate · Build Opportunity
learning/             bandit · insights · feedback loop (publish→measure→bias next build)
worker.py             24/7 autonomous loop (collect→analyze→build→learn, heartbeat, backoff)
tests/                 pytest (55 tests: core + API + persistence + agents + learning + worker)
deploy/               systemd units (yoe-api, yoe-worker)
docs/DEPLOY.md         Docker Compose + systemd 24/7 deployment guide
docs/ARCHITECTURE.md   design + honest status
sample-data/           example engine output
```

## License
MIT © nadirzhon
