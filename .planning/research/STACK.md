# Technology Stack: UCL & League Prediction Modules

**Project:** Football Prediction Engine  
**Researched:** 2026-06-27  
**Overall assessment:** No new runtime dependencies required. Stack is proven by WC and Euro.

## Recommended Stack

### Core Framework (unchanged)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Python | 3.11+ | Runtime | Existing constraint; 3.10-3.12 target |
| `football_core` | current | Shared engine | Reuses Poisson scoring, Elo, state, fetcher, predictors, constants, math_utils |

### Database (unchanged)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| JSON files | n/a | State persistence | Existing pattern; atomic writes via tempfile+os.replace |

### Infrastructure (unchanged)

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| CLI (argparse) | n/a | Entry point | Existing pattern; no UI layer |
| python-dotenv | latest | Env var loading | Existing dependency for API keys |

### Supporting Libraries (unchanged)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| requests | latest | HTTP API calls | BSD API, eloratings.net |
| catboost | latest | ML signal ingestion | BSD CatBoost predictions |

## New Logic Required (in competition modules, not core)

| Module | Location | Purpose | Reuses? |
|--------|----------|---------|---------|
| `league_table.py` | `competitions/ucl/src/` | 36-team Swiss league table engine | New |
| `tiebreakers.py` | `competitions/ucl/src/` | UCL-specific tiebreaker chain (no H2H) | New (separate from `football_core.groups._tiebreak_group`) |
| `playoffs.py` | `competitions/ucl/src/` | Two-legged knockout playoff simulation | New (wraps `football_core.knockout` + aggregate) |
| `bracket_setup.py` | `competitions/ucl/src/` | Seeded bracket construction from league position | New |
| `et_penalties.py` | `competitions/ucl/src/` | Extra time + penalty shootout simulation | New (or `football_core` if dual-proven) |
| `standings.py` | `competitions/league/src/` | Double round-robin table computation | New |
| `promotion.py` | `competitions/league/src/` | Promotion/relegation/play-off logic | New |
| `euro_qual.py` | `competitions/league/src/` | European qualification mapping | New |

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Tiebreaker logic | Separate module per competition | Extract generic chain to `football_core` | Premature — UCL and league chains differ fundamentally (no H2H vs H2H); Rule of Two not satisfied |
| ET/penalties | `football_core` addition | Keep in competition module | Likely needed by any two-legged knockout; if UCL proves it, extract |
| Bracket construction | Competition module | `football_core` | Bracket rules are competition-specific (seeding, protection); keep at competition level |
| League schedule | Competition module | `football_core` | Schedule generation/iteration is league-specific; core should remain tournament-agnostic |

## Installation (unchanged)

```bash
# Core (already installed)
pip install requests catboost python-dotenv

# No new dependencies required
```

## Sources

- PROJECT.md (.planning/PROJECT.md) — HIGH confidence
- Constraints (.planning/intel/constraints.md) — HIGH confidence  
- Existing codebase (football_core/*.py) — HIGH confidence
