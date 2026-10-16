"""Leak-free out-of-sample evaluation of the historical LaLiga backfill.

Reads the committed dataset under ``competitions/laliga/data/historical`` and
the production signal weights from ``config/signal_weights.json`` (READ-ONLY —
no model code, weights, or UI are touched), and evaluates:

  * cross-season and pooled metrics for the ensemble and baselines
    (uniform, empirical-frequency, Elo-only, market-odds-only) on
    identically-labelled match populations (apples-to-apples),
  * leave-one-signal-out ablations,
  * inverse-log-loss weights learned on strictly-prior training windows
    per season, plus their stability across windows,
  * calibration (confidence-based ECE) per config.

Every prediction uses ``historical.build_context_for_match`` (prior-only)
with the season's own pre-match Elo snapshot — no future data leaks. That
protocol is implemented once in ``football_core.historical_backfill``; this
module is the LaLiga configuration of it (seasons, dataset path, production
weights) and keeps the original public helper names/signatures for the
sibling investigation modules.

Production weights: squad_value has no historical data source, so the five
production weights are renormalized over the four signals with historical
inputs (market_odds / refined_elo / rolling_form / rest_days), matching the
UCL calibration convention.

Output: ``competitions/laliga/data/historical/evaluation/eval_results.json``
"""

from __future__ import annotations

import json
import os
from functools import partial
from pathlib import Path

from football_core import historical_backfill as shared
from football_core.evaluation_report import render_evaluation_markdown
from football_core.historical_backfill import (
    Harness,
    build_engine,
    first_date,
    has_odds,
    metrics_from,
    renormalize,
    run_evaluation,
)
from football_core.state import atomic_write_text

from competitions.laliga.src.historical import (
    ReplayResultProvider,
    build_context_for_match,
    frequency_baseline,
    load_replay_matches,
    order_matches,
    outcome_index,
)

from competitions.laliga.historical_backfill.contract import SEASONS as _SEASON_LABELS

HISTORICAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "historical"
)
OUT_DIR = os.path.join(HISTORICAL_DIR, "evaluation")
OUT_PATH = os.path.join(OUT_DIR, "eval_results.json")

CONFIG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
)

# D-01 window, derived from the contract so the evaluated seasons cannot drift
# from the committed corpus the build produced.
SEASONS = list(_SEASON_LABELS)
SIGNAL_ORDER = ["market_odds", "refined_elo", "rolling_form", "rest_days"]

DATASET = "competitions/laliga/data/historical (2000/01-2025/26)"

# Competition-specific declarations rendered once, before the first number, by
# the shared renderer's "## Declarations" block. The D-01 window is taken from
# DATASET (contract-derived) so it cannot drift from the corpus.
_EXTRA_DECLARATIONS = [
    "LaLiga odds coverage: every match in the backtest carries Pinnacle "
    "closing odds (~100% coverage), so the reported numbers are computed on a "
    "fully-covered population with no odds-less subpopulation.",
    "4-signal renormalization: `squad_value` has no historical data source, so "
    "the production weights are renormalized over the four historical signals "
    "(market_odds / refined_elo / rolling_form / rest_days); this is not the "
    "live 5-signal engine.",
    f"D-01 window: the corpus spans {DATASET}; one fixed chronological split "
    "(train ≤ 2020-12-31, validate 2021–2026).",
]

_HARNESS = Harness(
    build_context=build_context_for_match,
    outcome_index=outcome_index,
    order_matches=order_matches,
    frequency_baseline=frequency_baseline,
    replay_provider=ReplayResultProvider,
    load_replay_matches=load_replay_matches,
)


def production_weights() -> dict[str, float]:
    with open(os.path.join(CONFIG_DIR, "signal_weights.json"), encoding="utf-8") as f:
        data = json.load(f)
    return data["weights"]


# ─────────────────────────── loaders & helpers ───────────────────────────
# Same names, same signatures as before; the shared kernel supplies the bodies.

load_season = partial(shared.load_season, HISTORICAL_DIR, load_replay_matches=load_replay_matches)
_signal_output = partial(shared.signal_output, harness=_HARNESS)
completed_indices = partial(shared.completed_indices, outcome_index=outcome_index)
uniform_metrics = partial(shared.uniform_metrics, outcome_index=outcome_index)
eval_config = partial(shared.eval_config, harness=_HARNESS)
signal_metrics = partial(shared.signal_metrics, harness=_HARNESS)
freq_metrics_on = partial(shared.freq_metrics_on, outcome_index=outcome_index)


# ───────────────────────────────── main ─────────────────────────────────


def main() -> None:
    results = run_evaluation(OUT_PATH, HISTORICAL_DIR, SEASONS, SIGNAL_ORDER,
                             production_weights(), DATASET, _HARNESS)
    md = render_evaluation_markdown(
        results, competition="LaLiga", extra_declarations=_EXTRA_DECLARATIONS,
    )
    atomic_write_text(Path(os.path.join(OUT_DIR, "EVALUATION.md")), md)


if __name__ == "__main__":
    main()
