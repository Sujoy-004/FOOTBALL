# TESTING

## Run everything

```bash
python -m pytest
```

Run a single competition's suite (note: World Cup tests import via the
`src.` package prefix and must run with the repo root as working directory —
the plain `python -m pytest` invocation above handles this):

```bash
python -m pytest competitions/worldcup/tests
python -m pytest competitions/ucl/tests
python -m pytest football_core/tests
python -m pytest tests            # cross-cutting regression tests
```

## What is covered

- **football_core** — Elo math, Poisson simulation, tiebreakers, evaluation
  metrics, ensemble blending, weight-fitting contract, signal behaviour,
  generic odds-provider layer (providers, resolution/precedence, mapping,
  validation, freshness, states).
- **World Cup** — group/knockout format logic (Annex C, third-place),
  state persistence, fetch/parse adapters, counterfactual overrides.
- **UCL** — Swiss tiebreaker chain, playoff round, R16 bracket rules,
  two-legged ties, Monte Carlo determinism, bootstrap CIs, calibration.
- **LaLiga** — table rules, simulation, odds ingestion, MarketOddsSignal /
  market_only regression, historical leakage.
- **Cross-cutting (`tests/`)** — canonical ensemble guarantees: blend math,
  weight normalization/determinism/fallback, no deleted-signal leakage,
  WC + UCL production integration.

## Conventions

- Deterministic simulations: fixed seeds everywhere; tests assert exact or
  sum-to-one invariants rather than timings.
- Network-dependent provider tests are skipped/failing without API access —
  they exercise graceful degradation paths.


## Current baseline

As measured (`python -m pytest --tb=short -q`) after Phase 1: **1868 collected —
1749 passed, 14 skipped, 103 failed, 2 errors**.

The failures are not regressions. They are dominated by `FileNotFoundError` on
runtime stores that git does not carry — chiefly
`competitions/ucl/data/results.json`, which only a live refresh writes — plus a
few order-dependent integration tests that depend on those same stores. The
skips are environment-dependent provider tests exercising graceful-degradation
paths. See GETTING-STARTED for producing the stores.

Because the totals move with whatever data is on disk, the enforced gate is a
**node-id set**, not a pass count: the 105 failing/error node ids captured in
`.planning/phases/01-layering-inversion-deprecated-path-removal/01-01-BASELINE.md`
must not grow. Diff against it with:

```bash
python -m pytest -q --tb=no -p no:cacheprovider 2>&1 | Select-String "^(FAILED|ERROR)"
```
