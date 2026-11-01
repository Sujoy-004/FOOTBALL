# FOOTBALL — Production Deployment Runbook & Keep-Awake Guide

Target: **$0/month, zero credit card requirement**, completely free tier architecture.

---

## 1. 3-Tier Cloud Architecture Overview

The system architecture partitions concerns cleanly into three free-tier cloud platforms:

```text
Browser / Client ──► Cloudflare Edge ──► FastAPI on Render ──► Neon Serverless Postgres
                     (Vanilla JS / SPA   (Native Python 3.11   (PostgreSQL 16, pooled,
                      edge cache)         0.1 CPU / 512 MB,     scales to zero,
                                          sleeps after 15m)     EU Frankfurt)
```

| Component | Platform | Resource Plan | Operational Quota | Role / Purpose |
|---|---|---|---|---|
| **Frontend** | Cloudflare Pages / Workers | Free Plan | 100,000 req/day | Edge delivery of static dashboard SPA and client assets. |
| **Backend API** | Render Cloud Application | Free Web Service | 0.1 CPU, 512 MB RAM, 750 free instance-hrs/month | Runs FastAPI ASGI app (`football-api`) in Frankfurt region. |
| **Database** | Neon Serverless Postgres | Free Tier | 1 GB storage, 100 Compute Unit-hours/month | Pooled relational store for historical fixtures and predictions. |

---

## 2. 1-Click Render Blueprint Setup

The deployment is managed declaratively via [`render.yaml`](render.yaml) located at the repository root.

### Deployment Steps:
1. Sign up or log into [Render Dashboard](https://dashboard.render.com). (No credit card required for free tier).
2. Click **New +** in the navigation header and select **Blueprint**.
3. Connect your GitHub account and select the `FOOTBALL` repository.
4. Select the target deployment branch (`main`).
5. Render detects [`render.yaml`](render.yaml) and displays the service declaration:
   - **Service Name:** `football-api`
   - **Runtime:** `Python 3.11.8` (via native `runtime: python` and `.python-version`)
   - **Region:** `Frankfurt (EU Central)`
   - **Plan:** `Free`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn web.server:asgi_app --host 0.0.0.0 --port $PORT`
   - **Health Check Path:** `/health`
6. Render prompts for un-synced environment variables declared with `sync: false`:
   - Enter your `DATABASE_URL` (from Neon console; connection pooler endpoint).
   - Enter your API keys (`FOOTBALL_DATA_ORG_KEY`, `THE_ODDS_API_KEY`, `ADMIN_KEY`).
7. Click **Apply**.
8. Render initiates the build, installs dependencies using precompiled wheels, binds to dynamic `$PORT`, verifies the `/health` probe, and marks the service **Live**.

---

## 3. Environment Variable Reference

All sensitive secrets are marked `sync: false` in [`render.yaml`](render.yaml), ensuring zero credentials ever enter git history.

| Environment Variable | Required | Purpose | Sensitivity | Example Value |
|---|---|---|---|---|
| `PYTHON_VERSION` | Yes | Specifies Python runtime for Render native buildpack | Public | `3.11.8` |
| `PORT` | Auto | Injected dynamically by Render edge container environment | Runtime | `10000` |
| `DATABASE_URL` | Optional | Neon PostgreSQL pooled connection string for persistence | Critical Secret | `postgresql://user:pass@ep-xyz-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require` |
| `FOOTBALL_DATA_ORG_KEY` | Optional | API token for football-data.org match and fixture ingestion | Secret | `a1b2c3d4e5f6...` |
| `THE_ODDS_API_KEY` | Optional | API token for live bookmaker match odds | Secret | `f6e5d4c3b2a1...` |
| `ADMIN_KEY` | Optional | Authentication key for administrative maintenance triggers | Critical Secret | `sk_live_admin_987...` |
| `ALLOWED_ORIGINS` | Yes | Comma-separated CORS allowed origins for browser clients | Config | `http://localhost:8080,http://localhost:3000,https://football.pages.dev` |

> **Note on DATABASE_URL:** When `DATABASE_URL` is omitted or unset, the service automatically boots into resilient `fallback_json` mode, serving verified snapshot datasets without failing health readiness.

---

## 4. Keep-Awake Monitoring Setup

Render free-tier instances automatically spin down (sleep) after **15 minutes** of HTTP inactivity. Subsequent requests experience a cold start latency of ~45–60 seconds.

To maintain warm in-memory states and ensure zero cold starts, configure an external keep-awake pinger targeting `/health` on a **12-minute cadence**.

### Option A: UptimeRobot (Recommended)
1. Sign up at [UptimeRobot.com](https://uptimerobot.com) (free plan includes 50 monitors at 5-minute intervals).
2. Click **Add New Monitor**:
   - **Monitor Type:** `HTTP(s)`
   - **Friendly Name:** `FOOTBALL API Keep-Awake`
   - **URL (or IP):** `https://football-api.onrender.com/health`
   - **Monitoring Interval:** Every `10` or `12` minutes.
3. Save the monitor. UptimeRobot will ping the lightweight in-memory probe continuously, keeping the instance warm.

### Option B: cron-job.org
1. Sign up at [cron-job.org](https://cron-job.org).
2. Create a Cronjob:
   - **URL:** `https://football-api.onrender.com/health`
   - **Schedule:** User-defined, every 12 minutes (`*/12 * * * *`).
   - **Request Method:** `GET`.

### Option C: GitHub Actions Cron
Create a repository workflow (`.github/workflows/keep-awake.yml`):
```yaml
name: Keep Awake Ping
on:
  schedule:
    - cron: '*/12 * * * *'
  workflow_dispatch:

jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: Ping Health Endpoint
        run: curl -sSf https://football-api.onrender.com/health || exit 1
```

The `/health` endpoint is serviced entirely from memory (`web.derived.holder`) and responds in under 15ms with zero disk I/O, generating negligible compute load.

---

## 5. Local vs Production Runtime Commands

| Environment | Command | Socket Binding | Notes |
|---|---|---|---|
| **Local Development** | `python -m web.server` | `127.0.0.1:8080` (or via `--port` / `--host`) | Full CLI parser with `--offline` and `--no-preload` flags. |
| **Cloud Production (Render)** | `uvicorn web.server:asgi_app --host 0.0.0.0 --port $PORT` | `0.0.0.0:$PORT` (Render dynamically assigns `$PORT`) | Decoupled direct ASGI invocation; clean lifespan event management. |

To test production container behavior locally on Windows:
```powershell
$env:PORT="9000"
$env:HOST="0.0.0.0"
python -m web.server
```
Or directly via Uvicorn:
```powershell
uvicorn web.server:asgi_app --host 0.0.0.0 --port 9000
```

---

## 6. Operational Cost & Resource Quota Verification

The entire deployment infrastructure is designed for **$0.00/month** ongoing cost without hidden fees:

```text
Tier Budget Breakdown:
├── Render Web Service (Free Tier):       $0.00 / month (750 free instance-hours, single service)
├── Neon Serverless Postgres (Free Tier): $0.00 / month (1 GB storage, 100 CU-hours, scale-to-zero)
└── Cloudflare Edge (Free Tier):          $0.00 / month (100,000 requests/day, zero egress fee)
-------------------------------------------------------------------------------------------------
Total Monthly Operational Expense:        $0.00 USD
```

### Resource Margin Guardrails:
- **Render Instance Hours:** 1 web service running 24/7 uses 720–744 hours per month, comfortably within Render's 750 free monthly hours.
- **Neon Storage & Compute:** Initial dataset footprint is under 50 MB (out of 1,000 MB available).
- **Health Check Overhead:** At 12-minute intervals, the health probe consumes ~3,600 lightweight requests/month, well within free network bandwidth limits.
