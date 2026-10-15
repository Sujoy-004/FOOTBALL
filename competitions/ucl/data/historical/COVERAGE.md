# Historical UCL Backfill — Coverage Report

Repo: `competitions/ucl` — Accepted seasons **2011/12 → 2025/26** (15 seasons).
The contract (`historical_backfill/contract.py`) **requests** the full D-01
window 2000/01–2025/26; the keyless openfootball source only serves
**2011/12 onward**, so 2000/01–2010/11 is **excluded-and-reported** (see
below) — never fabricated, never silently dropped.

## Dataset location

- Per-season: `competitions/ucl/data/historical/<season>/{matches.json, elo_ratings.json, PROVENANCE.json}`
  (git-tracked; the approved `data/seasons/` path is the gitignored runtime store — deviation recorded in each `PROVENANCE.json`).
- Merged evaluation replay: `competitions/ucl/data/historical/replay_2011_12_2025_26.json`
  (named for the window it actually CONTAINS — the seasons a keyless results
  source could be acquired for — resolved through `contract.REPLAY_NAME`).

## Sources (all prebuilt, no live scraping)

| Provider | Used for | License |
|---|---|---|
| openfootball/champions-league `cl.txt` | fixtures, results, rounds, true dates | CC0-1.0 |
| v-eatpizzanot/soccer-dataset `odds.parquet` | 1X2 closing market odds (Pinnacle) | CC-BY-4.0 |
| xgabora Club-Football-Match-Data `EloRatings.csv` | ClubElo archive snapshots, strictly pre-season | MIT |

Rejected: Footiqo (JS-only, no bulk export / unclear license), OddsPortal (no live scraping per scope), Bookmaker Brain (paid, redistribution prohibited).

## Coverage

| Season | Matches | With market odds | Odds % | Elo teams / participants | Elo % | Verdict |
|---|---|---|---|---|---|---|
| 2011/12 | 125 | 0 | 0% | 26 / 32 | 81% | PASS |
| 2012/13 | 125 | 0 | 0% | 28 / 32 | 88% | PASS |
| 2013/14 | 125 | 0 | 0% | 28 / 32 | 88% | PASS |
| 2014/15 | 125 | 0 | 0% | 26 / 32 | 81% | PASS |
| 2015/16 | 125 | 0 | 0% | 26 / 32 | 81% | PASS |
| 2016/17 | 125 | 0 | 0% | 27 / 32 | 84% | PASS |
| 2017/18 | 125 | 0 | 0% | 27 / 32 | 84% | PASS |
| 2018/19 | 125 | 0 | 0% | 29 / 32 | 91% | PASS |
| 2019/20 | 119 | 0 | 0% | 28 / 32 | 88% | PASS |
| 2020/21 | 125 | 123 | 98% | 29 / 32 | 91% | PASS |
| 2021/22 | 125 | 108 | 86% | 28 / 32 | 88% | PASS |
| 2022/23 | 125 | 115 | 92% | 28 / 32 | 88% | PASS |
| 2023/24 | 125 | 123 | 98% | 29 / 32 | 91% | PASS |
| 2024/25 | 189 | 178 | 94% | 31 / 36 | 86% | PASS |
| 2025/26 | 189 | 166 | 88% | 31 / 36 | 86% | PASS |
| **Total** | **1997** | **813** | **40%** | — | — | **PASS ×15** |

Every season: chronology `date` (trustworthy), `n_real_signals ≥ 3`
(2011/12–2019/20) / `≥ 4` (2020/21–2025/26), ensemble log-loss beats uniform
AND empirical-frequency baselines.

## Excluded seasons (reported, not skipped)

| Season block | Reason |
|---|---|
| 2000/01–2010/11 (11 seasons) | openfootball/champions-league publishes no `cl.txt` for these seasons (HTTP 404, verified at build time); no other keyless results source covers them. Excluded-and-reported by the build; the merged replay is named for the window actually acquired. |

## Signal availability (honest)

- `refined_elo`, `rolling_form`, `rest_days`: available in all 15 seasons.
- `market_odds`: available 2020/21–2025/26; **unavailable 2011/12–2019/20** — the prebuilt odds dataset only starts UCL closing odds 2020-12. This is a genuine source gap, disclosed, never fabricated.
- `squad_value`: **omitted** — no prebuilt/licensed historical source; never fabricated (approved decision).

## Team mapping

- Canonical keys = `data/team_aliases.json` (long-form 2026/27 key preferred) + stable extras (Red Star Belgrade, Dinamo Zagreb, Zenit Saint Petersburg, Shakhtar… already present, etc.).
- 0 unmapped teams among the 1997 matches; all mapping lives in `competitions/ucl/historical_backfill/team_map.py` (direction-consistent reverse lookup; unit-tested).

## Limitations

1. **Odds coverage is 40% overall and 0% before 2020/21** — a genuine gap in every prebuilt/licensed odds source we could reach (all odds datasets that export UCL start 2020-12). Elo + form + rest-day signals still gate PASS in those seasons; the market-odds signal simply does not participate there.
2. **Elo mirror** (ClubElo archive under MIT) does not index some secondary leagues (UA, CZ, HR, RS, MD, IL, CH, HU) during the backfill window → 3–6 teams/season fall back to `DEFAULT_ELO` (same semantics as production `compute_elo_coverage`).
3. 2022/23 odds: 115 fixtures vs 117 raw single-row counts — a 2-match diff from the odds validity/`>1.0` filter and bookmaker preference (documented).
4. Single snapshot per season (strictly before MD1) — conservative/stale for later rounds by design (harness consumes a static elo map; no post-match leakage).
5. 2019/20 pre-lockdown group/KO results are the actual played fixtures; the COVID final-eight (2020-08) is single-leg with `home_ground="neutral"` and true dates preserved.
6. 2024/25–2025/26 use the 36-team league-phase format (189 matches/season); earlier seasons use the classic group + knockout format (119–125 matches/season). The parser is era-aware; no season was mis-parsed to fit a single format era.

## Provenance

Per season: `data/historical/<season>/PROVENANCE.json` (schema 1) records sources+URLs, licenses, fetch time, snapshot dates, per-season match/odds/elo counts, elo-missing teams, duplicate check, and SHA-256 of both generated files. Reproducible via `python -m competitions.ucl.historical_backfill.build` (idempotent, atomic writes).
