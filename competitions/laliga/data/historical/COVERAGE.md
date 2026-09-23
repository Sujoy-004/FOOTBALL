# Historical LaLiga Backfill — Coverage Report

Repo: `competitions/laliga` — Seasons **2019/20 → 2023/24** (380 matches per season; a complete 20-team double round-robin, final scores + closing 1X2 odds).

## Dataset location

- Per-season: `competitions/laliga/data/historical/<season>/{matches.json, elo_ratings.json, PROVENANCE.json}`
  (git-tracked; the approved `data/seasons/` path is the gitignored runtime store — deviation recorded in each `PROVENANCE.json`).
- Merged evaluation replay: `competitions/laliga/data/historical/replay_2019_20_2023_24.json` (regenerated after the mojibake-fix rebuild).
- Evaluation: `competitions/laliga/data/historical/evaluation/eval_results.json` (regenerated after the rebuild by `evaluate.py`).

## Sources (all prebuilt, no live scraping)

| Provider | Used for | License |
|---|---|---|
| football-data.co.uk SP1 archive | fixtures, results, rounds, closing 1X2 odds (bookmaker preference Pinnacle → Bet365 → Max → Avg), true dates | free for research use (football-data.co.uk/terms.php) |
| xgabora/Club-Football-Match-Data `EloRatings.csv` | ClubElo archive snapshots, strictly pre-season | MIT |

Rejected: Bookmaker Brain (paid, redistribution prohibited), OddsPortal (no live scraping per scope), api.clubelo.com (unreachable from this environment — archive mirror used instead, see Limitations).

## Coverage

| Season | Matches | Teams | With market odds | Odds % | Elo teams / participants | Elo % | Min date | Max date | Elo snapshot | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|
| 2019/20 | 380 | 20 | 380 | 100% | 20 / 20 | 100% | 2019-08-16 | 2020-07-19 | 2019-08-15 | PASS |
| 2020/21 | 380 | 20 | 380 | 100% | 20 / 20 | 100% | 2020-09-12 | 2021-05-23 | 2020-09-01 | PASS |
| 2021/22 | 380 | 20 | 380 | 100% | 20 / 20 | 100% | 2021-08-13 | 2022-05-22 | 2021-08-01 | PASS |
| 2022/23 | 380 | 20 | 380 | 100% | 20 / 20 | 100% | 2022-08-12 | 2023-06-04 | 2022-08-01 | PASS |
| 2023/24 | 380 | 20 | 380 | 100% | 20 / 20 | 100% | 2023-08-11 | 2024-05-26 | 2023-08-01 | PASS |
| **Total** | **1900** | — | **1900** | **100%** | — | — | — | — | — | **PASS ×5** |

Every match has `event_date` as the sole trustworthy chronology; per-evaluation, the ensemble beats uniform, empirical-frequency, Elo-only, and market-odds-only baselines (see `evaluation/eval_results.json`).

## Signal availability (honest)

- `market_odds`, `refined_elo`, `rolling_form`, `rest_days`: available in **all** 5 seasons.
- `market_odds` (closing line): 1900/1900 matches; `odds_known_at` recorded as `event_date` (closing line knowable at kickoff — documented assumption).
- `squad_value`: **omitted** — no prebuilt/licensed historical source; never fabricated (approved decision).
- Bookmaker distribution across 1900 matches: **Pinnacle 1897, Bet365 3** (fallback), all odds > 0.

## Canonical team keys

- 27 distinct canonical keys across all 5 seasons; 20 per season (includes promoted/relegated editions: Elche, Almería, Las Palmas, etc.).
- Round-trip contract verified for every key in `matches.json` + `elo_ratings.json`: `team_map.canonical(k) == k`; all `team_map.is_known(k)` — **0 unmapped keys, 0 round-trip failures, no mojibake bytes** (`\xc3\x83` / `\xc2\xad` patterns absent at byte level).
- Sample keys: `Athletic Club`, `Club Atlético de Madrid`, `Real Madrid CF`, `Sevilla FC`, `CD Leganés`, `RC Celta de Vigo`, `RCD Espanyol de Barcelona`, `RCD Mallorca`, `Girona FC`, `UD Almería`, `SD Eibar`, `Rayo Vallecano de Madrid`.
- Mapping provenance:
  - Canonical = `data/team_aliases.json` keys; long-form aliases used by the 2026/27 production fixtures preferred where present.
  - Extras via `backfill/team_map.py` for clubs absent from the 2026/27 season but present in 2019/20–2023/24: `UD Almería`, `Cádiz CF`, `SD Eibar`, `Girona FC`, `Granada CF`, `SD Huesca`, `UD Las Palmas`, `CD Leganés`, `RCD Mallorca`, `Real Valladolid CF`.

## Checksums

Verified: every on-disk file's SHA-256 equals the hash recorded in its `PROVENANCE.json` (which is the `provenance_hashes` the build prints), and a fresh read-only rebuild serializes byte-identical content (all 10 season files).

| File | SHA-256 |
|---|---|
| 2019_20/matches.json | `40d76ecb4caf2c66a6e1395e185a512176a86e36de8c08efba2fc3831542c5bf` |
| 2019_20/elo_ratings.json | `cbc6e6fd418351f51953d473d3b04595ad88c7ddb8b264031391207b85c03138` |
| 2020_21/matches.json | `98cf4aaceba8b56a47ff6acac8e0ac234853dae4557d24859289081f429b854d` |
| 2020_21/elo_ratings.json | `2865e5e2a50cbddcddb19fcead137aec197b7000280582fb398069b8814215ff` |
| 2021_22/matches.json | `0975edc8a1d4ce4e4da46f5ffdadb785b0dc6c1fda8c031fbcc6447053197fa3` |
| 2021_22/elo_ratings.json | `b03868486ee728e00239a832d7eec2c28afdac4b99efc4084d067e3b54638ac2` |
| 2022_23/matches.json | `8af96220cf0b8e7017705b641679d9af7e8663c4c30905a55dc7782a54f4debd` |
| 2022_23/elo_ratings.json | `5eadaf5bd3092c7d8a466d887fb0bc48420185984d3f2272e2be0b9177f1107a` |
| 2023_24/matches.json | `5f315b75690b6b8021f577ed4b63335869114131df5dc1de627c93477fc1319c` |
| 2023_24/elo_ratings.json | `3fc488e34d00c183642e7ff2c596459beadd51d926effd9fb04a4698478c74e1` |
| replay_2019_20_2023_24.json | `90fe5481ebe18a93b4a2eec24b3f86c51c100c8e5e449195c59cce5de28f6260` |
| evaluation/eval_results.json | `8cdbd4f5f60295488dbde303e5cd1447a6b7cd26e05b2fc23ad3c3b6cdbb42f0` |

**Reproducibility**: `python competitions/laliga/historical_backfill/build.py` is idempotent and produces byte-identical `matches.json` / `elo_ratings.json` (atomic writes). Verified `--verify-only`: 380 matches/season, 20 teams/season, 0 duplicate match ids, 380 odds/season (1900 total, 100%), full Elo coverage (0 missing teams/season). Note: file hashes are recorded with Windows text-mode line endings (`\r\n`); byte identity holds on the same platform/`write_json` path.

## Limitations

1. **Closing-line-odds-at-kickoff**: football-data.co.uk publishes no intraday odds timestamps; `odds_known_at` is set to the match `event_date` (documented assumption). No odds are ever used to predict their own fixture.
2. **Elo snapshot mirror**: live api.clubelo.com unreachable here; uses the MIT-licensed ClubElo archive mirror. One snapshot per season, strictly before MD1 (e.g. 2019/20 first match 2019-08-16 vs snapshot 2019-08-15) — conservative/stale for later rounds by design (no post-match leakage).
3. **Timezone conversion**: football-data local CET/CEST times are converted to UTC via Europe/Madrid zoneinfo; ordering is true chronological order.
4. **Single-season elo state**: each season's match set is evaluated against its own pre-season Elo snapshot; no inter-season elo carry-forward in the stored files.

## Provenance

Per season: `data/historical/<season>/PROVENANCE.json` (schema 1) records sources+URLs, licenses, fetch time, snapshot dates, per-season match/odds/elo counts, elo-missing teams, duplicate check, and SHA-256 of both generated files. Reproducible via `python competitions/laliga/historical_backfill/build.py` (idempotent, atomic writes). `replay_2019_20_2023_24.json` and `evaluation/eval_results.json` were regenerated after the mojibake-fix rebuild (eval `generated_at` 2026-09-22T04:37:24Z, ~4.5 min after the build's PROVENANCE).