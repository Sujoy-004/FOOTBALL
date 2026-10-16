# Historical World Cup Backfill — Coverage Report

Repo: `competitions/worldcup` — Accepted tournaments **2002 → 2026** (7 tournaments).
The contract (`historical_backfill/contract.py`) covers every senior men's
World Cup whose dates fall inside the D-01 window (2000-01-01 .. 2026-12-31):
2002, 2006, 2010, 2014, 2018, 2022, 2026. All seven were acquired from the
keyless openfootball source; **none was excluded**. 1998 (June 1998) predates
the window and is deliberately absent — the merged replay is named for the
window actually contained (`replay_2002_2026.json`).

## Dataset location

- Per-season: `competitions/worldcup/data/historical/<season>/{matches.json, elo_ratings.json, PROVENANCE.json}`
  (git-tracked; the approved `data/seasons/` path is the gitignored runtime store — deviation recorded in each `PROVENANCE.json`).
- Merged evaluation replay: `competitions/worldcup/data/historical/replay_2002_2026.json`
  (named for the window it actually CONTAINS — resolved through `contract.REPLAY_NAME`).

## Sources (all prebuilt, no live scraping)

| Provider | Used for | License |
|---|---|---|
| openfootball/world-cup `cup.txt` + `cup_finals.txt` | fixtures, results, rounds, real dates, knockout advancing winners | CC0-1.0 (public domain) |
| eloratings.net `World.tsv` | national-team Elo — **unavailable historically** (see below) | eloratings.net |

## Coverage

| Tournament | Matches | Group | KO | Teams | Dates | Shootouts | Verdict |
|---|---|---|---|---|---|---|---|
| 2002 | 64 | 48 | 16 | 32 | 2002-05-31 .. 2002-06-30 | 2 | PASS |
| 2006 | 64 | 48 | 16 | 32 | 2006-06-09 .. 2006-07-09 | 4 | PASS |
| 2010 | 64 | 48 | 16 | 32 | 2010-06-11 .. 2010-07-11 | 2 | PASS |
| 2014 | 64 | 48 | 16 | 32 | 2014-06-12 .. 2014-07-13 | 4 | PASS |
| 2018 | 64 | 48 | 16 | 32 | 2018-06-14 .. 2018-07-15 | 4 | PASS |
| 2022 | 64 | 48 | 16 | 32 | 2022-11-20 .. 2022-12-18 | 5 | PASS |
| 2026 | 104 | 72 | 32 | 48 | 2026-06-11 .. 2026-07-19 | 4 | PASS |
| **Total** | **488** | **336** | **152** | — | — | **25** | **PASS ×7** |

Every tournament: real national teams, real scores, real `event_date`s
(ISO-8601 UTC), knockout rounds carry an advancing winner (`winner` for
extra-time decisions, `pk_winner` for shootouts) — never a fabricated draw.
Match counts equal the true tournament sizes (64 for the 32-team era,
104 for the 48-team 2026 era).

## Excluded tournaments (reported, not skipped)

None. All 7 contracted tournaments were acquired. Had any been absent, the
build would have excluded-and-reported it by name with the reason
(`source-absent`); if every tournament were absent the build raises
`ValueError` and the World Cup block is honestly `deferred/provider-empty`
(D-04) — the corpus is never padded.

## Signal availability (honest)

- `rolling_form`, `rest_days`: available in all 7 tournaments (real `event_date`s).
- `market_odds`: **unavailable in every tournament** — the openfootball archive
  publishes results only, no odds. Odds fields are omitted entirely (count
  reported as 0, never fabricated).
- `refined_elo`: **unavailable in every tournament** — no date-indexed
  historical national-team Elo feed exists (verified 2026-10-15: eloratings.net
  serves only the current TSV; date-indexed URLs return HTTP 404). Every
  per-season `elo_ratings.json` is empty and the gap is recorded in
  `PROVENANCE.json`; `available_signals` reports `refined_elo` as
  `insufficient_data:no_elo_ratings` and the Elo signal never participates
  (A4/D-03). Using the current TSV as a per-tournament snapshot would leak up
  to 24 years of subsequent results into every prediction — a synthetic
  rating, forbidden.
- `squad_value`: **omitted** — no licensed historical source for national-team
  squad values; never fabricated.

## Team mapping

- Canonical keys = `data/team_aliases.json` (long-form 2026 production keys)
  + stable extras for historical national teams absent from the 2026 aliases
  (Angola, Cameroon, Chile, China, Costa Rica, Denmark, Greece, Honduras,
  Iceland, Ireland, Italy, Nigeria, North Korea, Peru, Poland, Russia,
  Serbia, Serbia and Montenegro, Slovakia, Slovenia, Togo, Trinidad and
  Tobago, Ukraine, Wales) + curated openfootball spellings
  (`Bosnia-Herzegovina` and `Bosnia & Herzegovina` → `Bosnia and Herzegovina`).
- Mapping lives in `competitions/worldcup/historical_backfill/sources/results_intl.py`
  via `football_core.historical_backfill.TeamKeys` (direction-consistent
  reverse lookup). 0 unmapped teams among the 488 matches.
- The committed `data/played.json` bracket-slot labels (`"A-First"`,
  `"B-Second"`) were **never** consumed as team identities: the corpus is
  built solely from the openfootball source (verified: no slot-shaped label
  appears in any `matches.json`).

## Kickoff times

2014/2018/2026 publish kickoff times with a UTC offset and are converted to
UTC (including date rollover). 2002/2006 publish no time and 2010/2022
publish local times without an offset; all use the documented `21:00:00Z`
default on the source date. Day-level chronology — the only thing the D-02
splitter and the form/rest-days signals consume — is unaffected.

## Knockout → 1X2 mapping (D-05/D-06)

Declared once in `competitions/worldcup/src/historical.py`: the knockout
target is the **advancing winner** (`0` home / `2` away, never `1`; a level
score is resolved by the recorded extra-time or penalty-shootout winner) and
the knockout forecast is renormalized two-way
(`p_home/(p_home+p_away)`). The Elo *update* coding `W = 0.75/0.25`
(`football_core/elo.py:37`) is a rating adjustment, not a 1X2 target — the
two are never conflated.

## Provenance

Per season: `data/historical/<season>/PROVENANCE.json` (schema 1) records
sources+URLs, licenses, fetch time, per-season match counts, elo-missing
teams, duplicate check, and SHA-256 of both generated files. Reproducible via
`python -m competitions.worldcup.historical_backfill.build` (idempotent,
atomic writes through `football_core.historical_backfill.write_json`).
