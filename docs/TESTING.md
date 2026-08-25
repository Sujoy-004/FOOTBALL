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
  metrics, ensemble blending, weight-fitting contract, signal behaviour.
- **World Cup** — group/knockout format logic (Annex C, third-place),
  state persistence, fetch/parse adapters, counterfactual overrides.
- **UCL** — Swiss tiebreaker chain, playoff round, R16 bracket rules,
  two-legged ties, Monte Carlo determinism, bootstrap CIs, calibration.
- **Cross-cutting (`tests/`)** — canonical ensemble guarantees: blend math,
  weight normalization/determinism/fallback, no deleted-signal leakage,
  WC + UCL production integration.

## Conventions

- Deterministic simulations: fixed seeds everywhere; tests assert exact or
  sum-to-one invariants rather than timings.
- Network-dependent provider tests are skipped/failing without API access —
  they exercise graceful degradation paths.


## Current baseline

904 collected: 899 passed / 4 failed / 1 skipped. The four persistent
failures are environment-dependent and tracked (one UCL replay-injection
assertion; three WC fetcher tests that monkeypatch `requests.get` while the
implementation uses a `requests.Session`). A minority of integration tests
additionally need local match-result files produced by a live refresh - see
GETTING-STARTED.
