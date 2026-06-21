<!-- generated-by: gsd-doc-writer -->
# Getting Started — World Cup Dynamic Predictor

## Prerequisites

- **Python 3.10+**
- **Internet connection** — live match data from BSD API, Elo sync from eloratings.net
- **BSD API key** — free at `https://sports.bzzoiro.com/register/`

## Installation

```bash
git clone <repo-url>
cd worldcup_predictor
pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` — replace `your_api_key_here` with your BSD API key.

## First Run

```bash
python main.py
```

**Startup Process:**

```
          ┌─────────────────────┐
          │   python main.py    │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  load state         │
          │  (data/*.json)      │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  historical         │──── BSD API
          │  catch-up           │◄──── (all matches
          │  + draw backfill    │      since Jun 11)
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  eval baseline      │
          │  (Brier/log-loss)   │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  prediction history │
          │  migration (v1→v2)  │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  seed signal caches │──── CatBoost API
          │  + merge into       │  (dedicated call)
          │  prediction_history │
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  Elo sync           │──── eloratings.net
          └──────────┬──────────┘
                     │
                     ▼
          ┌─────────────────────┐
          │  60s poll loop      │──── Ctrl+C to exit
          └─────────────────────┘
```

**Continuous Loop (each 60s):**

1. **Fetches new matches** from BSD API
2. **Refreshes signal caches** if TTL has expired:
   - Market odds extracted from BSD events (12h TTL — no extra API call)
   - CatBoost ML predictions fetched from `/api/predictions/` (24h TTL, 3-retry backoff)
3. **Merges** fresh signal data into `prediction_history.json` entries via `_merge_signals_into_history()`
4. **Checks 24h Elo sync** window — fetches `World.tsv` from eloratings.net if overdue
5. **Aggregates signal warnings** — prints unavailable market odds / CatBoost per match count
6. **Re-simulates** 50,000 tournament iterations
7. **Prints** updated probabilities with delta, optional group standings (on new matches or hourly refresh)

## CLI Examples

**Available Commands:**
- `python main.py` — Continuous polling (default)
- `python main.py --once` — Single cycle, then exit
- `python main.py --no-color` — Plain text (no ANSI)
- `python main.py --seed 42` — Reproducible simulation
- `python main.py --help` — All options

## What You'll See

**Normal heartbeat (no new matches):**
```
[2026-06-16 10:00:01] Polling... no new matches.
```

**New match detected:**
```
[2026-06-16 10:02:01] NEW MATCH DETECTED! Argentina 2-1 Nigeria
[2026-06-16 10:02:02] Re-simulating (50000 runs)... done in 1.3s
  1. Argentina  0.343  ▲ (+0.017)
  2. France     0.273  ▼ (-0.008)
```

**Shutdown:**
```
Shutdown requested — finishing current iteration...
=== FINAL PROBABILITIES ===
  1. Brazil    0.287
  2. Argentina 0.241
```

**Signal heartbeat (signal data available):**
```
[2026-06-16 10:03:01] Warning: CatBoost fetch failed: HTTP 500
```

```
[2026-06-16 10:04:01] ⚠ Market odds unavailable for 3 match(es)
```

```
[2026-06-16 10:05:01] ⚠ CatBoost predictions unavailable for 2 match(es)
```

**Startup migration message (one-shot, first run after upgrade):**
```
Prediction history migrated: 127 entries to compound format
```

## Common Setup Issues

**Missing or invalid API key:**
```
BSD_API_KEY not set. Get a free key at https://sports.bzzoiro.com/register/
```
→ Add your key to `.env`. The tool validates the key on startup (HTTP 401 = invalid).

**Corrupt JSON in `data/`:**
```
Corrupt JSON file: {filename}. Check data/ directory.
```
→ Ensure all `data/*.json` files are valid JSON. Re-clone if needed.

**Windows ANSI display issues:**
- On Windows Console Host, ANSI color codes may render as garbage
- Use `python main.py --no-color` to disable ANSI

## Next Steps

| Doc | What it covers |
|-----|---------------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, components, data flow, signal ingestion pipeline |
| [CONFIGURATION.md](CONFIGURATION.md) | Environment variables, settings reference |
| [README.md](../README.md) | Project overview, usage, project structure |

**Signal Architecture:**

The predictor supports **three prediction signals** evaluated independently and stored in `prediction_history.json`:

| Signal | Source | Cache TTL | Update Trigger |
|--------|--------|-----------|----------------|
| **Elo** | Internal Elo rating engine | N/A | On each new match detected |
| **Market Odds** | BSD API events response | 12h (`ODDS_CACHE_TTL_HOURS`) | Per-poll-cycle (extracted from existing events) |
| **CatBoost ML** | BSD `/api/predictions/` endpoint | 24h (`CATBOOST_CACHE_TTL_HOURS`) | Per-poll-cycle (dedicated API call) |

Caches are persisted in `data/odds_cache.json` and `data/catboost_cache.json`. Each cycle, stale caches are refreshed and merged into `prediction_history.json` entries via `_merge_signals_into_history()`. Aggregated warnings (`⚠ Market odds unavailable for N match(es)`) are printed when signals are missing for upcoming matches.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full data-flow diagram and module documentation.
