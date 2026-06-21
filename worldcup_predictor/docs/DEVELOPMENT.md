<!-- generated-by: gsd-doc-writer -->
# Development — World Cup Dynamic Predictor

## Local Setup

```bash
git clone <repo-url>
cd worldcup_predictor
pip install -r requirements.txt
cp .env.example .env   # set BSD_API_KEY
```

**Dev dependencies (from `requirements.txt`):**
- `pytest>=9.0` — test runner
- `pytest-cov>=7.1` — coverage reporting
- `python-dotenv>=1.0` — `.env` loader

No build step — Python runs source directly.

---

## Project Structure

```
worldcup_predictor/
├── main.py              — entry point (argparse, polling loop)
├── src/
│   ├── constants.py     — all config values (no magic numbers)
│   ├── elo.py           — expected_score, update_ratings
│   ├── elo_sync.py      — eloratings.net sync (24h interval)
│   ├── state.py         — JSON persistence (atomic writes)
│   ├── fetcher.py       — BSD API fetch + match processing
│   ├── groups.py        — Poisson group sim, standings, Annex C
│   ├── knockout.py      — full tournament sim (groups→knockout)
│   ├── simulation.py    — legacy knockout-only Monte Carlo
│   ├── output.py        — ANSI console display
│   ├── evaluation.py    — Brier, log loss, calibration
│   └── predictors/      — prediction signal ingestion (Phase 13)
│       ├── __init__.py  — package marker
│       ├── odds.py      — market odds: vig removal, parse, cache (12h TTL)
│       └── catboost.py  — BSD CatBoost ML: 3-attempt retry, parse, cache (24h TTL)
├── tests/               — 18 files, 387 passed, 1 skipped (pytest)
├── data/                — JSON state (static + runtime)
├── scripts/
│   └── benchmark_simulation.py
└── benchmarks/
    └── benchmark_groups.py
```

---

## Architecture Patterns

**Pure functions preferred** — no side effects:
```
src/simulation.py   — Monte Carlo (50K iterations, no I/O)
src/elo.py          — rating math, no file/network calls
```

**I/O isolated to one module:**
```
src/state.py    ← all file reads/writes
src/fetcher.py  ← all HTTP calls
src/output.py   ← all console output (no print() elsewhere)
```

**Signal cache helpers** in `src/state.py` (Phase 13):
```
load_signal_cache(cache_filename)   → dict     # state.py:699
save_signal_cache(cache, filename)  → None     # state.py:720 (atomic write)
is_cache_valid(cache, ttl_hours)    → bool     # state.py:734 (UTC-aware TTL check)
```

Used by `src/predictors/odds.py` and `src/predictors/catboost.py` for persistent, TTL-expiring signal caches in `data/odds_cache.json` and `data/catboost_cache.json`.

**Seeded RNG (not global):**
```
good:   rng = random.Random(seed)   # knockout.py:251
        rng.random()                 # explicit instance
bad:    random.seed(seed)           # global state — simulation.py:64 (legacy)
```

**Atomic JSON writes:**
```
tempfile.mkstemp() → json.dump → os.replace()   # state.py:115-125
```

Prevents corruption if process is killed mid-write.

---

## Running Tests

**Available Commands:**
- `pytest` — All 387 tests (1 skipped)
- `pytest -v` — Verbose per-test output
- `pytest tests/test_elo.py` — Single module
- `pytest tests/test_elo.py::TestExpectedScore::test_equal_ratings` — Single test
- `pytest -k "integration"` — Match pattern
- `pytest --cov=src --cov-report=term-missing` — With coverage

18 test modules cover: Elo, Elo sync, groups, knockout, simulation, fetcher, state (2 files), state load, output, CLI, evaluation, group integration, main loop, live smoke, scaffold, odds, catboost.

---

## Code Conventions

- **Type hints** on every function signature (Python 3.10+)
- **Google-style docstrings** with Args / Returns / Raises
- **Constants** in `src/constants.py` — no magic numbers anywhere
- **ANSI codes only** — no `colorama`, `rich`, or other display libs
- **`print()` isolated in `src/output.py`** — main.py has limited `print()` for startup/shutdown banners; all module logic output goes through `output.py`

---

## Adding a New Signal

Phase 13 established a reusable pattern for prediction signal ingestion:

1. **Create `src/predictors/<signal>.py`** — follow the package convention in `src/predictors/__init__.py`.
   - Use `load_signal_cache` / `save_signal_cache` / `is_cache_valid` from `src/state.py` for persistent TTL caching.
   - Follow `fetch_and_cache_*` pattern: accept `api_key`, return cache dict with `fetched_at`, `expires_at`, `matches`.
   - Degrade gracefully on network errors (return empty `matches` — never crash the polling loop).
2. **Register cache constants** in `src/constants.py` — add `*_CACHE_FILE` and `*_CACHE_TTL_HOURS`.
3. **Wire into main loop** in `main.py`:
   - Import `fetch_and_cache_<signal>` from `src.predictors.<signal>`.
   - Call it during each polling iteration.
   - Add signal injection via `_merge_signals_into_history()` (reads signal caches and writes into `prediction_history` compound entries).
4. **Integrate evaluation** in `src/evaluation.py` — pass `signal_name="<signal>"` to `evaluate_all_matches()` for per-signal Brier, log loss, and calibration reports.
5. **Add tests** in `tests/test_<signal>.py` — model after `test_odds.py` (455 lines) or `test_catboost.py` (550 lines) covering parse, cache I/O, and edge cases.
6. **Measure baseline** before → after via `eval_baseline_report.json`. Signal must justify itself through Brier/log-loss improvement.

---

## Signal Infrastructure (Phase 13)

### Per-Signal Evaluation

The `evaluate_all_matches()` function in `src/evaluation.py` supports evaluating individual prediction signals by passing a `signal_name` parameter:

```python
# Multi-signal report (all available signals)
evaluate_all_matches(teams, played, played_groups)                     # signal_name=None

# Single signal from prediction_history compound entries
evaluate_all_matches(teams, played, played_groups, signal_name="market_odds")
evaluate_all_matches(teams, played, played_groups, signal_name="catboost")
evaluate_all_matches(teams, played, played_groups, signal_name="blended")
evaluate_all_matches(teams, played, played_groups, signal_name="elo")  # replayed through Elo pipeline
```

- `signal_name=None` (default): Scans all signal keys in compound `prediction_history` entries and produces a multi-signal report.
- `signal_name="elo"`: Replays through the Elo pipeline (existing behavior), produces compound entries.
- `signal_name="market_odds"|"catboost"|"blended"`: Reads from compound `prediction_history` entries, filtering by the named signal key.

### Prediction History Schema Migration

Phase 13 introduced a **compound format** for `prediction_history.json`. Legacy flat entries (with top-level `signal` and `prediction` keys) are migrated when the predictor starts.

**Flat format (Phase 12b):**
```json
{
  "match_id": "ARG-vs-BRA",
  "prediction": 0.62,
  "signal": "elo",
  "team_a_elo": 1800,
  "team_b_elo": 1750
}
```

**Compound format (Phase 13+):**
```json
{
  "match_id": "ARG-vs-BRA",
  "signals": {
    "elo": {
      "probability": 0.62,
      "version": "v1",
      "timestamp": "2026-06-10T12:00:00",
      "available": true,
      "team_a_elo": 1800,
      "team_b_elo": 1750
    },
    "market_odds": {
      "probability": 0.55,
      "timestamp": "2026-06-10T12:30:00",
      "available": true
    },
    "catboost": {
      "probability": 0.58,
      "confidence": 0.85,
      "model_version": "catboost-v5.0",
      "timestamp": "2026-06-10T11:00:00",
      "available": true
    }
  },
  "actual": 1
}
```

Migration is handled by `state.migrate_prediction_history()` — idempotent, detects flat vs compound entries, converts in-place, and writes atomically. Signal injection from caches happens via `main._merge_signals_into_history()`.

---

## Benchmarks

```
python scripts/benchmark_simulation.py
python benchmarks/benchmark_groups.py
```

Measure simulation throughput and group-stage performance.

---

## Branching & PRs

No formal conventions documented. This is a personal CLI tool — no CI/CD, no PR template. Work directly on `main`.

---

## Related Docs

| Doc | What it covers |
|-----|---------------|
| [GETTING-STARTED.md](GETTING-STARTED.md) | First run, prerequisites |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System design, data flow |
| [CONFIGURATION.md](CONFIGURATION.md) | Env vars, CLI flags, constants |
