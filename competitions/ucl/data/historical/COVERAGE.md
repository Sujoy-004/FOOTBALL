# Historical UCL Backfill — Coverage Report

Repo: `competitions/ucl` — Seasons **2019/20 → 2023/24** (excludes 2024/25 per approved scope).

## Dataset location

- Per-season: `competitions/ucl/data/historical/<season>/{matches.json, elo_ratings.json, PROVENANCE.json}`
  (git-tracked; the approved `data/seasons/` path is the gitignored runtime store — deviation recorded in each `PROVENANCE.json`).
- Merged evaluation replay: `competitions/ucl/data/historical/replay_2019_20_2023_24.json`

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
| 2019/20 | 119 | 0 | 0% | 28 / 32 | 88% | PASS |
| 2020/21 | 125 | 123 | 98% | 29 / 32 | 91% | PASS |
| 2021/22 | 125 | 108 | 86% | 28 / 32 | 88% | PASS |
| 2022/23 | 125 | 115 | 92% | 28 / 32 | 88% | PASS |
| 2023/24 | 125 | 123 | 98% | 29 / 32 | 91% | PASS |
| **Total** | **619** | **469** | **76%** | — | — | **PASS ×5** |

Every season: chronology `date` (trustworthy), `n_real_signals ≥ 3` (2019/20) / `≥ 4` (2020/21–2023/24), ensemble log-loss beats uniform AND empirical-frequency baselines.

## Signal availability (honest)

- `refined_elo`, `rolling_form`, `rest_days`: available in all 5 seasons.
- `market_odds`: available 2020/21–2023/24; **unavailable 2019/20** (the prebuilt odds dataset only starts closing odds 2020-12).
- `squad_value`: **omitted** — no prebuilt/licensed historical source; never fabricated (approved decision).

## Team mapping

- Canonical keys = `data/team_aliases.json` (long-form 2026/27 key preferred) + stable extras (Red Star Belgrade, Dinamo Zagreb, Zenit Saint Petersburg, Shakhtar… already present, etc.).
- 0 unmapped teams among the 619 matches; all mapping lives in `competitions/ucl/backfill/team_map.py` (direction-consistent reverse lookup; unit-tested).

## Limitations

1. **2019/20 has no market odds** — genuine gap in every prebuilt/licensed source we could reach (all odds datasets that export UCL start 2020). Elo + form + rest-day signals still gate PASS.
2. **Elo mirror** (ClubElo archive under MIT) does not index some secondary leagues (UA, CZ, HR, RS, MD, IL, CH, HU) during the backfill window → 3–4 teams/season fall back to `DEFAULT_ELO` (same semantics as production `compute_elo_coverage`).
3. 2022/23 odds: 115 fixtures vs 117 raw single-row counts — a 2-match diff from the odds validity/`>1.0` filter and bookmaker preference (documented).
4. Single snapshot per season (strictly before MD1) — conservative/stale for later rounds by design (harness consumes a static elo map; no post-match leakage).
5. 2019/20 pre-lockdown group/KO results are the actual played fixtures; the COVID final-eight (2020-08) is single-leg with `home_ground="neutral"` and true dates preserved.

## Provenance

Per season: `data/historical/<season>/PROVENANCE.json` (schema 1) records sources+URLs, licenses, fetch time, snapshot dates, per-season match/odds/elo counts, elo-missing teams, duplicate check, and SHA-256 of both generated files. Reproducible via `python -m competitions.ucl.historical_backfill.build` (idempotent, atomic writes).