# Phase 12 — Independent Audit: Market_Only Strategy Evidence Chain

**Auditor:** Independence audit workstream (Phase 12J + leakage/provenance/fallback + failure modes)
**Date:** 2026-09-22 · **Read-only:** no UCL / World Cup / football_core / config / web / live-season / historical-dataset files modified
**Scope:** `competitions/laliga/src/ensemble.py` (`market_only`), `football_core/signals/market_odds.py`, `football_core/predictors/odds.py:remove_vig`, `historical_backfill/{build.py,evaluate.py,market_elo_investigation.py,team_map.py}`, `data/historical/<season>/` (2019_20..2023_24)

---

## 1. Historical artifact verification (12J)

### 1a. Checksums (raw-byte SHA-256 vs `PROVENANCE.json`)

`write_json` (`contract.py:66-75`) records in `PROVENANCE.files` the SHA-256 of the bytes actually written (utf-8, `ensure_ascii=False`, `indent=2` + trailing `\n`). Recomputed on the committed working-tree bytes with `hashlib` — matched on every file.

| season | file | recorded (prefix) | recomputed (prefix) | match |
|---|---|---|---|---|
| 2019_20 | matches.json | `40d76ecb…` | `40d76ecb…` | **PASS** |
| 2019_20 | elo_ratings.json | `cbc6e6fd…` | `cbc6e6fd…` | **PASS** |
| 2020_21 | matches.json | `98cf4aac…` | `98cf4aac…` | **PASS** |
| 2020_21 | elo_ratings.json | `2865e5e2…` | `2865e5e2…` | **PASS** |
| 2021_22 | matches.json | `0975edc8…` | `0975edc8…` | **PASS** |
| 2021_22 | elo_ratings.json | `b0386848…` | `b0386848…` | **PASS** |
| 2022_23 | matches.json | `8af96220…` | `8af96220…` | **PASS** |
| 2022_23 | elo_ratings.json | `5eadaf5b…` | `5eadaf5b…` | **PASS** |
| 2023_24 | matches.json | `5f315b75…` | `5f315b75…` | **PASS** |
| 2023_24 | elo_ratings.json | `3fc488e3…` | `3fc488e3…` | **PASS** |

`PROVENANCE.json` itself is not self-hashed (by design — it carries the hashes of the other two files); sizes 2053 B each, timestamps consistent across the single 04:32:56Z build run. Windows CRLF is accounted for: the recorded hash is computed on the as-written bytes, and the recompute is done on the same stored bytes, so line-ending convention is inherently matched.

### 1b. Mojibake verdict

- All 27 distinct team keys pass `encode('utf-8').decode('utf-8','strict')`.
- No name contains U+00C3/Ã or U+00C2/Â (the double-encode pattern); no raw byte sequences `0xC3 0x83` / `0xC3 0x82` in any `matches.json`.
- Non-ASCII names hold exactly one proper codepoint: `CD Leganés` (0xe9), `Club Atlético de Madrid` (0xe9), `Cádiz CF` (0xe1), `Deportivo Alavés` (0xe9), `Real Betis Balompié` (0xe9), `Real Sociedad de Fútbol` (0xfa), `UD Almería` (0xed). (Console `�` renderings in audit logs are terminal artifacts; codepoints are correct.)

**Mojibake: PASS — no double-encoding remnant.**

### 1c. Canonical keys

`team_map.canonical(k) == k` for all 27 distinct dataset names (0 mapped), `canonical(canonical(k)) == canonical(k)` everywhere, and all 27 ∈ `CANONICAL_KEYS`. **PASS.**

### 1d. Reproducibility (no network)

`build.py` fetches from cached files under `%TEMP%\opencode` (`SP1_<season>.csv`, `EloRatings.csv`; present, dated 2026-09-21). Re-running `build.build()` in a redirected temp output dir (offline, cached inputs) regenerated `matches.json` + `elo_ratings.json` for all 5 seasons and they are **byte-identical** to the committed files (identical sizes). Verified per-season Elo snapshots are strictly before the first match (e.g. 2019_20: snapshot 2019-08-15 < first match 2019-08-16; 2023_24: 2023-08-01 < 2023-08-11).

**Reproducible: PASS.** No silent regeneration from a different source — hashes match and full regen is byte-identical to the cached-source pipeline output.

### 1e. Phase-11 evaluation freshness

`eval_results.json` `generated_at` = 2026-09-22T04:37:24Z, ~4.5 min after the dataset `PROVENANCE` run (04:32:56Z). All four `weights_learned[season].evaluation.weights_source` fields are present (`train:2019_20 -> eval:2020_21`, … `train:2019_20+…+2022_23 -> eval:2023_24`), confirming this is the post-mojibake-fix rebuild and not the stale artifact flagged by the Phase-11 audit. Coverage.md documents the rebuild. **Consistent.**

---

## 2. Leakage audit of the market_only path

Evidence chain (code-level, plus empirical):

- Every candidate prediction routes through `historical.build_context_for_match` (re-exported from `competitions/ucl/src/historical.py:166-189`), which builds context from `prior_matches` with a strict `<` chronological-key comparison (`:161`) — prior-only by construction. Confirmed in `evaluate.py:165/183/309` and `market_elo_investigation.py:139/152/165` for every config incl. `market_only`.
- `MarketOddsSignal.predict` reads **only** `match.get("odds_home"/"odds_draw"/"odds_away")` (`market_odds.py:23-25`); context is unused. Empirically: market_only outputs are identical with full context vs `None` context across all 380 sampled matches; 0 prior-window violations (every `ctx.fixtures` `event_date` < target `event_date`) sampled on 2023_24.
- Season Elo snapshot is fixed pre-match (never updated in-season); market_only does not touch Elo at all.
- Chronological splits are date-first: `order_matches`/`split_chronological` are event_date-keyed (all 1900 dates homogeneous ISO-UTC `…Z`); freq baselines are fit on strictly-earlier windows (`evaluate.py:256-259` per-season, `:340-343` pooled) or strictly-prior seasons (`market_elo_investigation.py:172`).
- **No weight fitted on the evaluation season for market_only**: the strategy is a fixed constant. `build_strategy_engine("market_only")` → `EnsembleEngine([MarketOddsSignal()], weights={"market_odds": 1.0})`; `engine.weights == {'market_odds': 1.0}` exactly, frozen at construction (no mutation path in `blender.py`). Learned weights (`weights_learned`) exist only for the 4-signal production config and use strictly-prior seasons.

**Leakage: PASS.** market_only shares the same leak-free protocol as the Phase-11-verified production harness; it is even more isolated (single signal, reads only the per-match odds dict, zero fitted weights).

---

## 3. Fallback provenance + failure-mode audit (12F)

### 3a. Failure-mode table

Odds triple under test, base `(odds_home, odds_draw, odds_away) = (2.0, 3.4, 3.6)`; gate in `market_odds.py:27-37` is `isinstance(o,(int,float)) and o > 0` on **all three**; missing → `SignalOutput(1/3,1/3,1/3)`.

| case | expected | observed (h, d, a) | verdict |
|---|---|---|---|
| all three missing (`None`) | flat 1/3 | (0.3333, 0.3333, 0.3333) | **PASS** |
| partial: draw missing | flat 1/3, no blend with present odds | (0.3333, 0.3333, 0.3333) | **PASS** |
| partial: home missing | flat 1/3 | (0.3333, 0.3333, 0.3333) | **PASS** |
| odds as string `"2.0"` | flat 1/3 (isinstance gate) | (0.3333, 0.3333, 0.3333) | **PASS** |
| odds = 0 | flat 1/3 (`>0` fails) | (0.3333, 0.3333, 0.3333) | **PASS** |
| odds < 0 (−1.5) | flat 1/3 | (0.3333, 0.3333, 0.3333) | **PASS** |
| odds = NaN | flat 1/3 (`nan>0` is False) | (0.3333, 0.3333, 0.3333) | **PASS** |
| odds = `+inf` | passes gate (`inf>0` True); see caveat | (0.0000, 0.5143, 0.4857) for (inf, 3.4, 3.6) | **ACCEPTABLE — caveat** |
| valid triple (2.0, 3.4, 3.6) | `remove_vig` output | (0.4665, 0.2744, 0.2591) | **PASS** |

**inf edge finding (concrete values):** `remove_vig(float('inf'), 2.0, 3.4)` → `{'home': 0.0, 'draw': 0.6296, 'away': 0.3704}`. For the engine on `(inf, 3.4, 3.6)` the blend is `(0.0, 0.5143, 0.4857)`. `1/inf = 0.0`, so the vig-removed result is a well-formed 3-way distribution that deterministically collapses the home leg to 0 — no crash, no NaN, no out-of-range or inverted probabilities. Assessment: **not a concrete correctness defect.** Real closing lines are finite (historical dataset has 0 non-numeric / ≤0 / inf odds values across all 1900 matches; the store is Pinnacle×1897 + Bet365×3, all valid), and the far-worse NaN path is correctly excluded by the gate. A one-line hardening (reject non-finite via `math.isfinite`) is worth recording but is not required by Phase 12. The earlier `_odds_available` production gate (`odds.py:27`) has the same `val <= 0` shape, so inf would also pass there — consistent behavior, not a regression.

### 3b. Duplicate market inputs / bookmaker aggregation / staleness

- Historical store holds **one** closing 1X2 triple per match: 1900 matches, `odds_bookmaker` = Pinnacle ×1897, Bet365 ×3 (Pinnacle→Bet365→Max→Avg preference, `results_fd.py:53-58`); the fixture files publish closing lines only, never intraday sets.
- Exactly 3 `odds_*` numeric fields per match — **no** multi-bookmaker aggregation in the historical or live path; no `Avg`/`Max` blends stored.
- Staleness is impossible to disguise: `odds_known_at == event_date` for all 1900 matches (`results_fd.py:123`, recorded in every `PROVENANCE.sources.results_odds.note`) — the closing line is knowable at kickoff, so a stale figure cannot masquerade as fresh.

### 3c. No accidental fallback to another predictive signal

The `market_only` engine has a **single** registered signal. Empirically: `engine.weights == {'market_odds': 1.0}`; `engine._registry.list() == ['market_odds']`; for a missing-odds match the blend is exactly `(1/3, 1/3, 1/3)` with `weights_applied == {'market_odds': 1.0}` — never Elo / form / squad.

### 3d. Determinism

- Same input twice (`MarketOddsSignal`): `(0.466463415, 0.274390244, 0.259146341)` both times — equal.
- Two independent `MarketOddsSignal()` instances: identical output.
- Engine on a missing-odds match: 1/3 flat twice — identical.

---

## 4. Audit verdict

**PASS.**

All 10 historical artifacts byte-match their recorded SHA-256; the full dataset regenerates byte-identically from cached sources offline; no mojibake or canonical-key remnants; market_only shares the prior-only leak-free protocol and never fits weights on the evaluation season; all failure-mode fallbacks behave as specified — **including the `+inf` caveat**, which is a deterministic, well-formed, non-crashing edge (home leg collapses to 0.0) absent from real data and judged not a concrete correctness defect requiring a fix.

Caveats:
1. `+inf` odds pass the `>0` gate and produce a valid-looking distribution with the home leg at 0 (recorded above). Add `math.isfinite` if robustness against corrupt odds feeds is ever required.
2. Reproducibility requires the pinned `%TEMP%\opencode` source cache; a cleared cache re-fetches over the network and could in principle see a changed upstream file (not observed; current state is byte-frozen).
3. `data/historical/` is currently untracked in git (same note as Phase-11 audit); audit was run against the working-tree data.