# Stack Research

**Domain:** FIFA World Cup 2026 Monte Carlo simulation (48-team, group stage + 32-team knockout)
**Researched:** 2026-06-14
**Confidence:** HIGH

> **Post-research note:** The recommended stack was adopted with minor deviations. Python stdlib-only
> approach confirmed as sufficient. No numpy, no database, no new dependencies added.

## Recommended Stack (Implemented)

### Core Technologies
- **Python 3.10+** — Runtime. Cross-platform, fast enough for 50K×104 simulation iterations. ✅ Implemented
- **`random` (stdlib)** — Monte Carlo PRNG via `random.seed()` for reproducibility. ✅ Implemented
- **`json` (stdlib)** — State persistence. Human-readable, no database. ✅ Implemented
- **`requests`** — HTTP client for BSD API. ✅ Implemented

### New / Modified Components for 48-Team Format
- **`math` (stdlib)** — Extended for Poisson goal model (expected_goals). ✅ Implemented
- **`itertools`** — Group round-robin pairings via `itertools.combinations`. ✅ Implemented
- **`collections`** — `defaultdict` for match result aggregation. ✅ Implemented
- **Annex C JSON file** — 495-entry table as `data/annex_c.json`. ✅ Implemented

### Not Used (Deviations from Research)
- `dataclasses` — **Not used.** Raw dicts kept for simplicity (research recommended for structured models)
- `enum` — **Not used.** String constants kept (research recommended for type safety)
- All stdlib — no new pip packages needed beyond existing ✅ Confirmed

### Data Files (As Implemented)

| File | Size (est.) | Purpose | Status |
|---|---|---|---|
| `data/groups.json` | ~2 KB | 12 groups, 4 teams each | ✅ Created |
| `data/teams.json` | ~8 KB | 48 teams with Elo | ✅ Extended to 48 |
| `data/bracket.json` | ~3 KB | 40-match knockout bracket | ✅ Replaced with 40 matches |
| `data/played.json` | Runtime | Knockout match results | ✅ Extended schema |
| `data/annex_c.json` | ~50 KB | 495-entry Annex C table | ✅ Created |
| `data/team_aliases.json` | ~3 KB | BSD name variations | ✅ Extended to 48 teams |

## Alternative Decisions Made

| Recommended | Alternative | What Was Chosen |
|---|---|---|
| stdlib `random` | `numpy.random` | stdlib random (sufficient) |
| stdlib `json` | `sqlite3` | stdlib json (proven) |
| Hardcoded Annex C table | Generated lookup | JSON file (data-driven) |
| stdlib `dataclasses` | `pydantic` | Raw dicts (simpler) |

## Dependencies (Actual requirements.txt)
```
pytest>=9.0
pytest-cov>=7.1
python-dotenv>=1.0
```

Note: `requests` is not in requirements.txt but is imported by fetcher.py and elo_sync.py.

## What NOT to Use (Confirmed)

| Avoid | Why | Status |
|---|---|---|
| `numpy` for 50K iterations | Overkill; adds build complexity | ✅ Not used |
| Database (SQLite, PostgreSQL) | Adds setup burden | ✅ Not used |
| `pandas` for standings | Massive dependency | ✅ Not used |
| ORM or data validation lib | CLI tool doesn't need it | ✅ Not used |
| `cachetools` | JSON loads in <10ms | ✅ Not used |

---

*Stack research for: FIFA World Cup 2026 48-team format migration*
*Researched: 2026-06-14 | Updated: 2026-06-16*
