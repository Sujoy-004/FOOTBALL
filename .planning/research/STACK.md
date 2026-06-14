# Stack Research

**Domain:** FIFA World Cup 2026 Monte Carlo simulation (48-team, group stage + 32-team knockout)
**Researched:** 2026-06-14
**Confidence:** HIGH

## Recommended Stack

### Core Technologies (unchanged from v1.0)

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python | 3.10+ | Runtime | Cross-platform, fast enough for 50K×104 simulation iterations, rich stdlib |
| `random` (stdlib) | — | Monte Carlo PRNG | Sufficient for simulation; deterministic via `random.seed()`; no numpy dependency needed for 50K iterations |
| `json` (stdlib) | — | State persistence | Human-readable, no database setup, already proven in v1.0 |
| `requests` | >=2.31 | HTTP client for live match API | Battle-tested, simple API, exponential backoff support |

### New / Modified Components for 48-Team Format

| Component | Version | Purpose | When to Use |
|-----------|---------|---------|-------------|
| `dataclasses` (stdlib) | — | Structured group/team/match models | Replace raw dicts for group standings, team records, simulation state |
| `math` (stdlib) | — | Already used for `expected_score` | No additions needed; draw-probability modelling may extend usage |
| `itertools` (stdlib) | — | Group round-robin pairings | `itertools.combinations(groups, 2)` generates 6 matches-per-group trivially |
| `enum` (stdlib) | — | Round identifiers, group labels | Replace string constants like `"R16"` with proper `Enum` for type safety |
| Annex C JSON file | — | 495-entry third-place routing table | Static data; stored as `data/annex_c.json`, loaded via existing `state.py` pattern |

### Data Files (new/modified JSON schemas)

| File | Size (est.) | Purpose |
|------|-------------|---------|
| `data/groups.json` | NEW ~2 KB | 12 groups, each with 4 team references + initial draw seed info |
| `data/teams.json` | EXTENDED ~8 KB | 48 teams (was 32) — add `group` field per team |
| `data/bracket.json` | REPLACED ~3 KB | Full 104-match bracket (group + knockout), replacing 23-match bracket |
| `data/played.json` | EXTENDED | Same schema; now tracking group results too |
| `data/annex_c.json` | NEW ~50 KB | 495 entries mapping C(12,8) third-place group combinations → R32 matchups |

### Development Tools (unchanged from v1.0)

| Tool | Purpose | Notes |
|------|---------|-------|
| `pytest>=9.0` | Test framework | 98 existing tests; will need ~40 more for group stage + tiebreakers |
| `pytest-cov>=7.1` | Coverage | Target: keep >90% coverage |
| `python-dotenv>=1.0` | Environment config | Already in use for `BSD_API_KEY` |

## Installation

No new dependencies required. The existing `requirements.txt` covers everything:

```bash
# Existing — unchanged for v2.0
pip install -r worldcup_predictor/requirements.txt
```

Contents:
```
pytest>=9.0
pytest-cov>=7.1
python-dotenv>=1.0
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| stdlib `random` | `numpy.random` | If simulation scales to 500K+ iterations where vectorisation matters (see v2.0 feature V2-07) |
| stdlib `json` | `pickle`, `sqlite3` | If speed of load/save becomes a bottleneck (>200ms), or if relational queries needed |
| Hardcoded Annex C table | Code-generated lookup | If you want compile-time verification of all 495 combinations (trade-off: bloats source) |
| stdlib `dataclasses` | `pydantic`, `attrs` | If input validation/coercion becomes non-trivial (overkill for CLI tool) |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `numpy` for 50K iterations | Overkill; import overhead ~200ms for ~0.5s speed gain at current scale; adds build complexity | Pure Python `random` + `math` |
| Database (SQLite, PostgreSQL) | Adds setup burden, cross-platform issues, migration overhead; data fits in memory | JSON files + atomic writes |
| `pandas` for standings | Massive dependency for simple sort/groupby operations | Python `sorted()` + `itertools.groupby()` |
| ORM or data validation lib | CLI tool with ~2200 LOC doesn't need heavy abstractions | `dataclasses` + simple validation methods |
| `cachetools` or external caching | No external caching needed; JSON files load in <10ms | Already done: in-memory dicts |

## Stack Patterns by Variant

**If target iteration count exceeds 200K per cycle:**
- Consider `numpy.random` for vectorised Monte Carlo (~10× speedup)
- Cost: adds numpy as a dependency (~40MB), complicates CI
- Trade-off: not needed for 50K iterations; current impl runs ~1.3s for 23 matches, projected ~6s for 104 matches

**If adding web dashboard (feature V2-04):**
- Flask + Chart.js as stack additions
- These are additive, not replacements — core simulator stays dependency-free

**If adding what-if mode (feature V2-05):**
- No new dependencies needed
- Only needs modified state input + re-run simulation

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| Python 3.10+ | all deps | `dataclasses` built-in since 3.7; `enum` since 3.4; fine |
| `requests>=2.31` | Python 3.10+ | Last version supporting Python 3.10; newer requires 3.11+ |
| `pytest>=9.0` | Python 3.10+ | All good |
| Windows + ANSI | Python 3.10+ | Current `os.system("")` workaround for Windows Console Host works |

## Sources

- **FIFA.com** — Official 2026 format: 12 groups of 4, 48 teams, 104 matches total, top 2 + 8 best 3rd places advance
  - https://www.fifa.com/en/tournaments/mens/worldcup/canadamexicousa2026/articles/groups-how-teams-qualify-tie-breakers — [HIGH confidence]
- **FIFA Regulations PDF** — Page 26: tiebreaker order; Page 80+: Annex C with 495 combinations
  - https://digitalhub.fifa.com/m/636f5c9c6f29771f/original/FWC2026_regulations_EN.pdf — [HIGH confidence]
- **Wikipedia** — 2026 FIFA World Cup knockout stage (match schedule 73-88 confirmed)
  - https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_knockout_stage — [MEDIUM confidence; confirmed against multiple sources]
- **DEV article by Mark** — Practical implementation of Annex C lookup as JSON mapping with `C(12,8)=495` combinations keyed by sorted group string
  - https://dev.to/mark_b5f4ffdd8e7cd58/encoding-fifas-495-third-place-scenarios-for-the-2026-world-cup-4814 — [HIGH confidence; matches FIFA regulations]
- **Sporting News** — Tiebreaker order confirmed: head-to-head points → head-to-head GD → head-to-head goals → overall GD → overall goals → fair play → FIFA ranking
  - https://www.sportingnews.com/us/soccer/news/world-cup-group-tiebreakers-2026-teams-tied-points-goal-differential/606ca25a20c6167ef229d31c — [MEDIUM confidence; cites official PDF]
- **Goal.com** — Same tiebreaker order confirmed, plus third-place ranking criteria
  - https://www.goal.com/en-us/news/fifa-world-cup-group-stage-rules-explained/blt39e14c7602e0afb7 — [MEDIUM confidence; cross-referenced with Sporting News]
- **Project codebase** — v1.0 analysis: 32 teams, 23 bracket matches, pure-Python simulation runs ~1.3s for 50K iterations
  - `worldcup_predictor/src/simulation.py` — confirmation of existing architecture
  - `worldcup_predictor/data/bracket.json` — current 23-match bracket structure
  - `worldcup_predictor/src/state.py` — JSON load/save pattern with atomic writes

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack sufficiency | HIGH | Pure Python stdlib fully sufficient for group stage + 104-match simulation |
| Tiebreaker rules | HIGH | Confirmed via 3 independent sources citing official FIFA PDF; 7-step order cross-verified |
| Annex C structure | HIGH | C(12,8) = 495 combinations confirmed; lookup table approach validated by multiple implementations |
| Performance estimate | MEDIUM | ~4.5× slowdown projected (23→104 matches); actual depends on draw-model complexity for group stage |
| No new dependencies | HIGH | `dataclasses`, `enum`, `itertools` are all stdlib; no pip installs needed |

---

*Stack research for: FIFA World Cup 2026 48-team format migration*
*Researched: 2026-06-14*
