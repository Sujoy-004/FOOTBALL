# Production-Integration Safety Report — Phase 12H

Verifies that Phase 12A's selectable `market_only` LaLiga strategy cannot affect
the production path. Verified against the working tree at e3906fd+Phase 12A.

## 1. Production remains the default strategy

- `competitions/laliga/src/pipeline.py:150` — `build_signal_engine(..., *, strategy: str = "production")`.
- `competitions/laliga/src/simulation.py:117` — `run_mc_simulation(..., *, strategy: str = "production")`.
- `web/laliga_app.py` passes no `strategy` to `build_signal_engine` (lines 272, 288) or to
  `run_mc_simulation` (lines 487, 763, 770) → default `"production"` applies at every call site.
- `web/simulation_service.py` contains no `strategy` reference.
- Production default is corroborated by `competitions/laliga/tests/test_market_only_strategy.py`
  `TestProductionUnchanged` (5 signals registered + config weights loaded).

## 2. market_only is selectable only behind an explicit flag

- No `strategy` key exists in any `competitions/laliga/config/*.json` (grep: zero matches).
- No environment variable or config file reads `strategy`; the path is exercised only by an
  explicit `strategy="market_only"` keyword argument.

## 3. No cross-competition configuration leakage

- `competitions/laliga/src/ensemble.py` imports only `football_core.blender.EnsembleEngine`
  and, lazily, `football_core.signals.market_odds.MarketOddsSignal`; all other imports are local
  to `competitions/laliga/src/`.
- `git status --short` shows changes only under `competitions/laliga/` (pipeline.py, simulation.py
  modified; ensemble.py, tests/ untracked; historical dataset dirs pre-existing untracked).
- No `competitions/ucl`, `competitions/worldcup`, `football_core`, or `web` file is modified or
  created.

## 4. UCL and World Cup unchanged

- `git diff competitions/ucl` — empty (UCL Market+Elo strategies untouched; the UCL regression
  guard `competitions/ucl/tests/test_ensemble_strategy.py` still passes 17/17).
- `git diff competitions/worldcup` — empty.
- `git diff football_core web` — empty.

## 5. Simulation consumes the selected strategy

- `run_mc_simulation` (simulation.py:209) forwards `strategy=strategy` into
  `build_signal_engine(...)`, which dispatches non-production strategies to
  `build_strategy_engine` (pipeline.py:153-156). Verified live:
  `run_mc_simulation(..., strategy="market_only")` with fixture args returns `mode:
  "simulation"` and `signals == {"market_odds": {..., "weight": 1.0}}` — see
  `TestSimulationWiring::test_run_mc_simulation_market_only`.

## 6. Provenance identifies market_only explicitly

- `STRATEGIES = ("production", "market_only")` (ensemble.py:15).
- `build_strategy_engine("market_only")` returns `EnsembleEngine([MarketOddsSignal()],
  weights={"market_odds": 1.0})` (ensemble.py:30-33).
- Every `BlendedPrediction.signal_breakdown` for a market_only engine contains exactly
  `{"market_odds": {..., "weight": 1.0}}` — no Elo/form/squad fallback signals ever appear
  (asserted in `TestStrategyIsolation`).

## Verification artifacts

| Check | Command | Result |
|-------|---------|--------|
| New + leakage suites | `pytest competitions/laliga/tests/test_market_only_strategy.py competitions/laliga/tests/test_historical_leakage.py -q` | 38 passed |
| UCL regression guard | `pytest competitions/ucl/tests/test_ensemble_strategy.py -q` | 17 passed |
| Full LaLiga suite | `pytest competitions/laliga -q` | see Phase 12I report |
| Full UCL suite | `pytest competitions/ucl -q` | see Phase 12I report |