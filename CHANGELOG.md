# CHANGELOG

Chronological project log. Newest entries first. States:
`IMPLEMENTED` (shipped code), `VERIFIED` (proven against live data/tests),
`NOT ENABLED` (built but intentionally not switched on), and
`EXTERNALLY UNAVAILABLE` (blocked by an upstream/source limitation).

## UNRELEASED — Phase 13B: generic live odds providers

**IMPLEMENTED**

- Generic, competition-agnostic `OddsProvider` abstraction in
  `football_core/odds.py` (provider interface/contract, acquisition core,
  canonical fixture mapping, validation, freshness, store/observability).
- `TheOddsApiOddsProvider` — official The Odds API v4 adapter (1X2, decimal,
  EU books); deterministic primary-book selection (default `pinnacle`, else
  most-recently-updated, ties broken lexically).
- `BSDOddsProvider` — re-shapes the existing BSD event feed onto the generic
  layer (no BSD behavior change).
- `ODDS_PROVIDER` configuration (`the-odds-api | bsd | auto | none`), kept
  separate from `DATA_PROVIDER` (fixtures/results). `auto` precedence:
  the-odds-api → bsd → none.
- LaLiga adapter retains its full public API over the generic layer
  (backward compatible; `acquire_laliga_odds(odds_mode=...)` added).
- Freshness: `provider_last_update` (bookmaker timestamp) and `fetched_at`
  both must precede kickoff; post-kickoff provider updates rejected as
  STALE. Kickoff-date compatibility check and competition isolation.
- Alias fixes: LaLiga `team_aliases.json` gains
  `Athletic Bilbao`, `Bilbao`, `Atlético Madrid`, `Atletico Madrid`,
  `Real Betis` variants (The Odds API naming).
- 48 new generic provider-layer tests (`football_core/tests/test_odds_providers.py`);
  all pre-existing Phase-13 odds-ingestion tests preserved.

**VERIFIED**

- Real LaLiga live odds via The Odds API: **20/20** current-season events
  mapped onto canonical fixtures (`state=ODDS_PARTIAL`, available=20,
  missing=360, invalid/stale/unmappable/kickoff_mismatch=0).
- Real non-uniform `market_only` output on an actual fixture
  (Málaga vs Espanyol, Pinnacle 2.67/3.25/2.73 → probs 0.3572/0.2935/0.3493).
- UCL: The Odds API feed availability verified (18 events, 346 h2h books).
- Full suite: **1751 passed / 1 skipped**.
- Security scan: no API keys in source/tests/logs/artifacts; `.env` ignored.

**NOT ENABLED**

- UCL consumption of The Odds API (feed is available; UCL pipeline unchanged).
- `market_only` remains a selectable candidate strategy; not promoted.

**EXTERNALLY UNAVAILABLE**

- World Cup: The Odds API returns no usable World Cup events
  (`soccer_fifa_world_cup` empty; not in the provider catalog). World Cup
  remains an odds-free competition; no-odds behavior unchanged.

## UNRELEASED — Phase 13: LaLiga live market-odds ingestion

**IMPLEMENTED**

- LaLiga bookmaker market-odds ingestion capability (market 1X2, decimal,
  vig-removed via `football_core.predictors.odds.remove_vig`).
- Contract: normalized per-fixture records with provenance
  (`provider`, `bookmaker`, `event_id`, `provider_last_update`, `fetched_at`,
  `event_kickoff`); runtime odds store with aggregate state
  (ODDS_AVAILABLE/ODDS_PARTIAL/ODDS_MISSING/…).
- Validation and freshness: pre-kickoff requirement, stale handling,
  missing-vs-stale distinction, honest fallback.
- Observability: odds status surfaced through the LaLiga pipeline, web
  dashboard, and simulation signal stats.
- `MarketOddsSignal` integration: live odds decorate fixtures and feed the
  ensemble.
- `market_only` strategy remains selectable-only (candidate, not promoted).
- Existing BSD odds path preserved.
- Regression coverage: odds ingestion, market_only strategy, historical
  leakage prevention.

**VERIFIED**

- LaLiga fixtures/results refreshed from football-data.org (380 fixtures,
  69 played at Phase 13; shipped fallback updated with real live data).
- Full suite: **1703 passed / 1 skipped** at Phase 13 completion
  (subsequently 1751 after Phase 13B).
- No production model weights changed; UCL shadow methodology/state
  unchanged; World Cup behavior unchanged; historical evaluation artifacts
  unchanged.