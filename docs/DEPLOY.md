# Deploying for 24/7 operation

The engine runs as **two long-lived processes** that share one sqlite time-series
store:

- **api** — FastAPI dashboard + endpoints (`uvicorn yoe.api:app`)
- **worker** — the autonomous loop (`python -m yoe.worker`): every
  `WORKER_INTERVAL_SEC` it collects a snapshot pass under quota, re-runs the
  engine on accumulated history, optionally builds the top opportunity, learns
  from results, and writes a heartbeat the API exposes at `GET /status`.

With **no API keys set, both run on the built-in mock provider** — so you can
stand the whole thing up and watch it work before wiring real data.

---

## Option A — Docker Compose (recommended)

```bash
cp .env.example .env          # edit budgets / keys / cadence as needed
docker compose up -d --build  # starts api (:8000) + worker, both restart:unless-stopped
```

- Dashboard: http://SERVER:8000  · Health: `/health` · Worker liveness: `/status`
- Data persists in the named volume `yoe-data` (the sqlite file at `/data/yoe.db`),
  so restarts keep all accumulated history and learning.
- Logs: `docker compose logs -f worker`
- Update: `git pull && docker compose up -d --build`
- Stop: `docker compose down` (add `-v` to also wipe the data volume)

Turn on autonomous content building:

```bash
WORKER_AUTO_BUILD=true docker compose up -d
```

## Option B — systemd on a bare host

```bash
sudo useradd -r -m -d /opt/yoe yoe
sudo git clone https://github.com/nadirzhon/youtube-opportunity-engine /opt/yoe
cd /opt/yoe
python3 -m venv .venv && .venv/bin/pip install -r requirements-api.txt
mkdir -p /opt/yoe/data
cp .env.example .env          # edit it

sudo cp deploy/yoe-api.service deploy/yoe-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yoe-api yoe-worker
```

- Status: `systemctl status yoe-worker` · Logs: `journalctl -u yoe-worker -f`
- Both units use `Restart=always`; the worker stops gracefully on `SIGTERM`
  (finishes the running cycle first, `TimeoutStopSec=120`).

---

## Going from mock to real data

1. **YouTube** — set `YOUTUBE_API_KEY` and `YOUTUBE_CHANNEL_IDS` (comma-separated).
   The provider factory switches off the mock automatically. Mind the daily quota
   (`YOUTUBE_DAILY_QUOTA`); the scheduler samples adaptively and hard-stops before
   overrun.
2. **Content agents** — set `LLM_API_KEY` for real research/concept/script prose
   (mock LLM until then). `TTS_API_KEY` / `IMAGE_API_KEY` enable real media in the
   video factory.
3. **Budgets** — `DAILY_BUDGET_USD` / `MONTHLY_BUDGET_USD` are hard ceilings across
   all paid providers; a cycle that would exceed them skips rather than spends.

## Monitoring

`GET /status` returns worker health, cycle count, last error, heartbeat age and
data freshness. `worker_stale` flips true if no heartbeat has landed in ~3×
the interval — wire that into any uptime check (e.g. a cron `curl` + alert).

## Scaling later (external, not required for 24/7)

sqlite handles a single-host worker + API comfortably (WAL mode, busy timeout).
For multi-host or high write concurrency, swap `DATABASE_URL` to Postgres once the
adapter phase lands — the store interface is the seam.
