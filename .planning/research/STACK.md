# Technology Stack

**Project:** World Cup Dynamic Prediction  
**Researched:** 2026-06-13  
**Mode:** Ecosystem research — live football tournament prediction with Elo + Monte Carlo simulation  
**Overall confidence:** HIGH (all recommendations verified against current PyPI releases and official docs)

---

## Executive Stack Summary

```
Python 3.10+  |  requests  |  numpy  |  rich  |  pydantic-settings  |  pytest + hypothesis
    │             │            │          │          │                     │
    │             │            │          │          │                     └── Testing (Phase 2+)
    │             │            │          │          └── Typed config, env vars, API model validation
    │             │            │          └── Console output: tables, progress bars, colors, timestamps
    │             │            └── Vectorized Monte Carlo simulation (50K+ iterations)
    │             └── HTTP client for Football-Data.org API (sync only, rate-limited)
    └── Runtime (CPython, cross-platform)
```

---

## Core Dependencies (MVP)

### 1. `requests` ~= 2.32.x — HTTP Client

| Attribute | Detail |
|-----------|--------|
| **Version** | 2.32.3 (latest stable, March 2026) |
| **Purpose** | Poll Football-Data.org v4 API for live match results |
| **Confidence** | **HIGH** — verified via PyPI |
| **Why this** | The API is rate-limited to **10 requests/minute** on the free tier. There is zero benefit from async I/O here — every minute you make 1 synchronous request and sit idle. `requests` is the simplest, most battle-tested sync HTTP client in Python. The Football-Data.org official docs explicitly use `requests` in their Python examples. |
| **Why NOT httpx** | httpx is the modern async-capable alternative, but async provides no advantage for a single-poll-per-minute loop. httpx adds ~1.5 MB to install size and an extra failure surface (HTTP/2 negotiation, optional dependencies). Use `requests` for MVP. If you later add multi-API polling, migrate to `httpx` then. |
| **Why NOT aiohttp** | Async-only, steeper learning curve, no sync API. Overkill. |

**Usage pattern:**
```python
import requests

API_BASE = "https://api.football-data.org/v4"
HEADERS = {"X-Auth-Token": os.environ["FOOTBALL_API_KEY"]}

response = requests.get(f"{API_BASE}/matches", headers=HEADERS, timeout=30)
response.raise_for_status()
data = response.json()
```

### 2. `numpy` ~= 2.4.x — Vectorized Monte Carlo Engine

| Attribute | Detail |
|-----------|--------|
| **Version** | 2.4.6 (latest stable, May 2026; 2.4.x series recommended) |
| **Purpose** | Run 50,000+ tournament simulations in < 1 second via vectorized array operations |
| **Confidence** | **HIGH** — verified via PyPI (newreleases.io, sourceforge mirror) |
| **Why this** | A knockout tournament with 15 matches simulated 50,000 times = **750,000 individual match simulations**. Pure Python `for` loops with `random.random()` per match take **8–15 seconds**. NumPy generates all random numbers as a single contiguous array and applies vectorized comparisons — **0.1–0.3 seconds**. This is not a nice-to-have; it's the difference between feeling instantaneous and watching a spinner. |
| **Why NOT pure random** | `random.random()` in a loop is 50–100× slower than `numpy.random.uniform(size=N)`. At 50K sims, that's noticeable. At 100K+, it's painful. |
| **Why NOT numba/cupy** | Overkill for 50K sims on a laptop. Numba adds compilation overhead and Windows compatibility issues (MSVC toolchain). CuPy requires an NVIDIA GPU. NumPy is just-right. |

**Core vectorization pattern:**
```python
import numpy as np

def simulate_tournament_bracket(matchups, team_strengths, n_sims=50_000):
    """Vectorized Monte Carlo simulation of a knockout bracket."""
    random_values = np.random.uniform(size=(n_sims, len(matchups)))
    # For each match: team_0_wins = random_value < p_team0 (derived from Elo diff)
    # Propagate winners through bracket rounds
    # Return win counts per team
    ...
```

### 3. `rich` ~= 15.0.x — Console Output

| Attribute | Detail |
|-----------|--------|
| **Version** | 15.0.0 (latest, April 2026) |
| **Purpose** | Formatted probability tables, colored deltas (±1.2%), live-updating output, progress bars |
| **Confidence** | **HIGH** — verified via PyPI (pypistats, pepy.tech, GitHub releases) |
| **Why this** | The MVP spec requires: (a) formatted percentage tables, (b) probability deltas with +/- signs, (c) timestamps, (d) progress indication during simulation. Rich provides all of this out of the box: `Table` for formatted output, `Live` for auto-refreshing displays, `Progress` for simulation progress, and cross-platform ANSI color (including Windows 10+). 56.5k GitHub stars, 150M+ weekly PyPI downloads. It is the **de facto standard** for Python CLI formatting. |
| **Why NOT colorama** | Rich handles Windows ANSI natively (since v13+). No separate colorama needed. |
| **Why NOT tabulate** | `tabulate` is for static table generation only — no colors, no live updates, no progress bars. |
| **Why this shouldn't be post-MVP** | The original plan deferred `rich` to post-MVP. This is **incorrect**. Raw `print()` statements produce unreadable output when displaying 16+ team probabilities with deltas. Rich's `Table` and `Live` are the difference between "this looks like a student project" and "this looks like a real tool." Add it in Phase 1. |

**Usage pattern:**
```python
from rich.console import Console
from rich.table import Table
from rich.live import Live
from rich.progress import track

console = Console()

def display_probabilities(probs, deltas=None):
    table = Table(title="Championship Probabilities")
    table.add_column("Team", style="cyan")
    table.add_column("Probability", justify="right")
    table.add_column("Δ", justify="right")
    # ... populate rows
    console.print(table)
```

### 4. `pydantic` + `pydantic-settings` — Configuration & Data Models

| Attribute | Detail |
|-----------|--------|
| **Version** | pydantic ~= 2.10, pydantic-settings ~= 2.11 |
| **Purpose** | API response validation, typed configuration class, env var loading |
| **Confidence** | **HIGH** — verified via PyPI and pydantic.dev docs |
| **Why this** | The Football-Data.org API returns JSON with nullable fields, nested objects, and type-sensitive values (score is `int`, not `str`). Without validation, a missing `"score"` field or a `None` where you expect an `int` crashes the script at 2 AM. Pydantic v2 (Rust-backed, 5–50× faster than v1) validates API responses at parse time, catches bad data early, and produces clean error messages. `pydantic-settings` reads `FOOTBALL_API_KEY` from the environment with type safety — no manual `os.environ.get()` with fragile defaults. |
| **Why NOT dataclasses** | Python dataclasses provide zero validation. A `str` where an `int` belongs gets passed silently until something breaks. `pydantic.BaseModel` adds coercion + validation — "42" becomes `42`, `None` raises immediately. |
| **Why NOT manual dict parsing** | Spread `if "score" in data and data["score"] is not None` checks throughout the codebase = bug magnet. One schema per API response, validated once. |

**Config pattern:**
```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    football_api_key: str          # reads from FOOTBALL_API_KEY env var
    poll_interval_seconds: int = 60
    elo_k_factor: float = 60.0
    simulation_count: int = 50_000
    starting_elo: int = 1500
    home_advantage_elo: int = 53

    model_config = {"env_prefix": ""}

settings = Settings()  # auto-reads env vars
```

**API response model:**
```python
from pydantic import BaseModel
from typing import Optional

class MatchScore(BaseModel):
    home: Optional[int] = None
    away: Optional[int] = None

class MatchData(BaseModel):
    id: int
    utc_date: str
    status: str          # "FINISHED", "SCHEDULED", etc.
    home_team: str
    away_team: str
    score: MatchScore
```

---

## Development & Testing Dependencies

### `pytest` ~= 8.x — Test Framework

| Attribute | Detail |
|-----------|--------|
| **Version** | 8.3.x (latest stable 2025—2026) |
| **Purpose** | Unit tests, integration tests, fixtures |
| **Confidence** | HIGH |
| **Why this** | The undisputed standard. `unittest` requires boilerplate; pytest uses `assert` and gives you fixture injection, parameterization, and plugins. |
| **Why NOT unittest** | More verbose, less ergonomic fixtures, no automatic test discovery. |

### `hypothesis` ~= 6.x — Property-Based Testing

| Attribute | Detail |
|-----------|--------|
| **Version** | 6.120+ |
| **Purpose** | Generate random Elo update scenarios to verify mathematical invariants |
| **Confidence** | MEDIUM (useful but not critical for MVP) |
| **Why this** | The Elo formula has mathematical invariants: (a) total rating change = 0 across both teams, (b) expected score for A + expected score for B = 1.0. Hypothesis generates thousands of (rating_a, rating_b, actual_score) tuples and asserts these invariants hold. Catches edge cases that manual test cases miss. |
| **Why NOT random manual tests** | Manual tests cover what you think of. Hypothesis covers what you didn't think of (division by zero at extremes, floating point drift at 5000+ iterations, etc.) |

---

## Elo Rating — Custom Implementation (NOT a Library)

| Approach | Recommendation |
|----------|---------------|
| **Custom function** | ✅ **USE THIS** — ~15 lines, zero dependencies, fully transparent |
| **`openskill`** | ❌ — Designed for multiplayer games (N-player free-for-all), not 1v1 sports. Incorrect priors |
| **`elo`** | ❌ — Abandoned package, last updated 2017, incompatible with Python 3.12+ |
| **`player_ratings`** | ❌ — Focused on chess time controls, not football parameters |

**The entire Elo system is two formulas:**

```
Expected score: E_A = 1 / (1 + 10 ^ ((R_B - R_A + HFA) / 400))
Rating update:  R_new = R_old + K * (actual - expected) * margin_of_victory_mult
```

**HIGH confidence** — Wikipedia Elo formula × World Football Elo Ratings modifications (goal difference multiplier, K adjusted by tournament importance, home advantage = 53 Elo points per eloratings.net).

---

## What NOT to Use

| Library | Reason to Avoid | Confidence |
|---------|----------------|------------|
| **`flask` / `fastapi`** | Out of scope — no web UI for MVP | HIGH (per PROJECT.md) |
| **`sqlalchemy` / any ORM** | JSON files are the persistence layer; DB adds setup complexity | HIGH (per PROJECT.md) |
| **`pandas`** | Overkill for 16 team records. `numpy` arrays + dicts are sufficient | HIGH |
| **`tqdm`** | **Rich's `Progress`** replaces this completely with better formatting | HIGH |
| **`colorama`** | **Rich handles Windows ANSI natively** since v13. Zero need | HIGH (verified via Rich compatibility docs) |
| **`click`** | `typer` is strictly better — same author (tiangolo), less boilerplate | MEDIUM |
| **`argparse`** | Adequate but verbose. `typer` generates --help and type coercion automatically | MEDIUM |
| **`asyncio` + `aiohttp`** | No benefit for 1 request/60s. Adds cognitive overhead | HIGH |
| **`xlrd` / `openpyxl`** | No spreadsheet I/O required | HIGH |
| **`plotly` / `matplotlib`** | Console-only output; no charts for MVP | HIGH |

---

## Dependency Installation

```bash
# Core — install these in Phase 1
pip install requests~=2.32 numpy~=2.4 rich~=15.0 pydantic~=2.10 pydantic-settings~=2.11

# Development — Phase 2+
pip install pytest~=8.0 hypothesis~=6.120

# Freeze after testing
pip freeze > requirements.txt
```

---

## Version Summary Table (Current as of June 2026)

| Package | Version | Published | Python Support | Notes |
|---------|---------|-----------|----------------|-------|
| `requests` | 2.32.3 | Mar 2026 | 3.8+ | Final state; maintenance-only mode |
| `numpy` | **2.4.6** | May 2026 | 3.11–3.14 | Pin `~=2.4` to avoid 2.5 breaking changes initially |
| `rich` | **15.0.0** | Apr 2026 | 3.8+ | "The So Long 3.8 Release" |
| `pydantic` | 2.10.x | 2026 | 3.8+ | Rust-backed (pydantic-core) |
| `pydantic-settings` | 2.11.x | 2026 | 3.9+ | Separate package since v2 |
| `pytest` | 8.3.x | 2026 | 3.8+ | — |
| `hypothesis` | 6.120+ | 2026 | 3.9+ | — |

---

## Dependency Size Budget

| Dependency | Install Size | Key Files |
|------------|-------------|-----------|
| `requests` | ~1.1 MB | urllib3, certifi, charset-normalizer, idna |
| `numpy` | ~20–40 MB | Compiled C extensions (largest dep by far) |
| `rich` | ~1.5 MB | pygments, markdown-it-py |
| `pydantic` | ~6 MB | pydantic-core (Rust binary) |
| `pydantic-settings` | ~100 KB | Thin wrapper |
| **Total** | **~30–50 MB** | Acceptable for a CLI tool |

---

## Architecture Diagram (Data Flow × Stack Layer)

```
┌──────────────────────────────────────────────────────┐
│                    main.py (loop)                     │
│                                                        │
│  ┌──────────┐    ┌──────────┐    ┌───────────────────┐ │
│  │ fetcher   │───▶│ elo      │───▶│ simulator (numpy) │ │
│  │ (requests)│    │ (custom) │    │ (vectorized MC)   │ │
│  └─────┬────┘    └────┬─────┘    └─────────┬─────────┘ │
│        │              │                    │           │
│        ▼              ▼                    ▼           │
│  ┌────────────────────────────────────────────────┐    │
│  │           state.py (JSON persistence)          │    │
│  │  teams.json │ bracket.json │ played.json       │    │
│  └────────────────────────────────────────────────┘    │
│        │              │                    │           │
│        ▼              ▼                    ▼           │
│  ┌────────────────────────────────────────────────┐    │
│  │          output.py (rich)                      │    │
│  │  Tables │ Live refresh │ Progress │ Colors     │    │
│  └────────────────────────────────────────────────┘    │
│                                                        │
│  ┌────────────────────────────────────────────────┐    │
│  │     constants.py (pydantic-settings)            │    │
│  │  Type-safe config from env vars                 │    │
│  └────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────┘

External API:  api.football-data.org/v4  (10 req/min)
```

---

## Sources

| Source | What It Told Us | Confidence |
|--------|----------------|------------|
| [football-data.org Python docs](https://docs.football-data.org/general/v4/coding/python.html) | API v4 uses `requests` in official examples | HIGH |
| [football-data.org policies](https://docs.football-data.org/general/v4/policies.html) | Free tier: 10 req/min | HIGH |
| [PyPI — numpy 2.4.6](https://newreleases.io/project/pypi/numpy/release/2.4.6) | Current stable version | HIGH |
| [PyPI — rich 15.0.0](https://pypi.org/project/rich/) | Latest version, cross-platform ANSI | HIGH |
| [Rich compatibility](https://rich.readthedocs.io/en/stable/) | Native Windows support, no colorama needed | HIGH |
| [PyPI — requests 2.32.3](https://pypi.org/project/requests/) | Current version | HIGH |
| [PyPI — pydantic-settings 2.11](https://generalistprogrammer.com/tutorials/pydantic-settings-python-package-guide) | Version and usage guide | MEDIUM |
| [Pydantic v2 docs](https://pydantic.dev/docs/validation/latest/) | Rust-backed validation, config patterns | HIGH |
| [World Football Elo Ratings](https://www.eloratings.net/about) | K-factor by tournament, goal-difference multiplier, HFA value | HIGH |
| [Wikipedia — World Football Elo Ratings](https://en.wikipedia.org/wiki/World_Football_Elo_Ratings) | Academic verification of Elo modifications | HIGH |
| [HTTPX vs Requests comparison (2026)](https://decodo.com/blog/httpx-vs-requests-vs-aiohttp) | Sync vs async benchmarks, confirms no benefit for rate-limited polling | MEDIUM |
| [GitHub — tiangolo/typer](https://github.com/fastapi/typer) | CLI library, 19.5k stars | HIGH |
| [PyPI — football-api client](https://pypi.org/project/football-api/) | Third-party Python wrapper for football-data.org (alternative to raw requests) | MEDIUM |

---

## Open Questions / Phase-Specific Research

1. **football-api PyPI wrapper** (v0.1.1, Feb 2026): Exists as a Pydantic-typed client for football-data.org v4. Evaluate in Phase 1 as a potential replacement for raw `requests` + manual Pydantic models. Risk: newly published, may have incomplete endpoint coverage.

2. **NumPy version strategy**: 2.5.0rc1 drops Python 3.11 support. Pin `numpy~=2.4` in requirements, plan migration when 2.5 stable is assessed.

3. **Typer integration**: If CLI arguments are needed (e.g., `--sim-count`, `--poll-interval`, `--competition-id`), add Typer as a Phase 1 enhancement. Skip if all config stays in constants.

4. **Parallel simulation**: For >500K sims, investigate `multiprocessing` with NumPy (splitting sims across cores). Not needed for 50K, but flagged for post-MVP scaling.
