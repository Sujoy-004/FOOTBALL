# GETTING-STARTED

## 1. Install

Python 3.10–3.12.

```bash
pip install -r requirements.txt
```

## 2. Optional: live data keys

Copy `.env.example` to `.env` and fill in:

- `FOOTBALL_DATA_ORG_KEY` — free key from football-data.org (recommended)
- `BSD_API_KEY` — optional alternative provider
- `DATA_PROVIDER` — `bsd` or `football-data` to pin the provider (auto-detects when unset)

Without keys, the dashboard uses the last validated local data; every external dependency degrades gracefully and the UI shows the acquisition/freshness state. Use `python -m web.server --offline` for an explicitly network-free session.

`.env.example` also documents the optional tuning knobs: `FOOTBALL_PRELOAD_ALL=1` (eager preload at boot instead of lazy on first request), `POLL_INTERVAL` (World Cup live-ingestion poll interval, default 60s), and `FOOTBALL_LIVE=1` (admit intentional live UCL CLI ingestion into the real data dir).

## 3. Run the dashboard

```bash
python -m web.server          # http://127.0.0.1:8080
```

- `/worldcup` — WC 2026 dashboard (overview, standings, bracket, match insight,
  what-if, seeded simulation)
- `/ucl` — UCL 2026/27 dashboard (future fixtures, standings when available, bracket, what-if) with 2025/26 selectable as historical data
- `POST /worldcup/api/simulate` / `POST /ucl/api/simulate` — seeded Monte Carlo
  runs (async task + progress polling)

## 4. What-if

Structured only: choose a match and an Elo delta for the home side; the server
re-runs the seeded simulation and reports baseline vs adjusted championship
probabilities for both teams.

## 5. Calibration (when you have labeled results)

```bash
curl -X POST http://127.0.0.1:8080/worldcup/api/calibrate
curl -X POST http://127.0.0.1:8080/ucl/api/calibrate
```

Both fit ensemble weights by inverse log-loss on recorded outcomes and refuse
to run below the per-signal sample threshold. UCL fits against the current
active season's result ledger. Until then the runtime uses the documented
uniform fallback.

## 6. Benchmark

```bash
python -m competitions.worldcup.benchmarks.benchmark_simulation
```

Reports wall-clock time of the full production path (ensemble + simulation) at
1K/10K/50K/100K iterations, best-of-3.


## Tests and local match data

`python -m pytest` runs the full suite. A minority of integration tests
additionally assert served payloads against real match-result files
(`results.json`, `played.json`, `played_groups.json`, signal caches) that
are intentionally not committed — they are produced by a live refresh or
copied from an existing checkout. On a pristine clone those specific tests
fail with missing-file errors while everything else passes; boot and
simulation still work out of the box in snapshot mode (verified: both
competitions render, simulations run, zero provider calls).
