"""Leak-free out-of-sample evaluation of the historical UCL backfill.

Reads the committed dataset under ``data/historical`` and production signal
weights, and evaluates (READ-ONLY — no model code, weights, or UI are
touched):

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
module is the UCL configuration of it (seasons, dataset path, production
weights) and keeps the original public helper names/signatures for the
sibling investigation modules and the candidate gate.

Output: ``data/historical/evaluation/eval_results.json``
"""

from __future__ import annotations

import os
from functools import partial

from football_core import historical_backfill as shared
from football_core.historical_backfill import (
    Harness,
    build_engine,
    first_date,
    has_odds,
    metrics_from,
    renormalize,
    run_evaluation,
)

from competitions.ucl.src.historical import (
    ReplayResultProvider,
    build_context_for_match,
    frequency_baseline,
    load_replay_matches,
    order_matches,
    outcome_index,
)

HISTORICAL_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "historical"
)
OUT_DIR = os.path.join(HISTORICAL_DIR, "evaluation")
OUT_PATH = os.path.join(OUT_DIR, "eval_results.json")

SEASONS = ["2019_20", "2020_21", "2021_22", "2022_23", "2023_24"]
SIGNAL_ORDER = ["market_odds", "refined_elo", "rolling_form", "rest_days"]

PROD_WEIGHTS_RAW = {
    "market_odds": 0.203813,
    "refined_elo": 0.191216,
    "rolling_form": 0.197345,
    "rest_days": 0.203813,
    "squad_value": 0.203813,
}

DATASET = "competitions/ucl/data/historical (2019/20-2023/24)"

_HARNESS = Harness(
    build_context=build_context_for_match,
    outcome_index=outcome_index,
    order_matches=order_matches,
    frequency_baseline=frequency_baseline,
    replay_provider=ReplayResultProvider,
    load_replay_matches=load_replay_matches,
)

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
    run_evaluation(OUT_PATH, HISTORICAL_DIR, SEASONS, SIGNAL_ORDER,
                   PROD_WEIGHTS_RAW, DATASET, _HARNESS)


if __name__ == "__main__":
    main()
