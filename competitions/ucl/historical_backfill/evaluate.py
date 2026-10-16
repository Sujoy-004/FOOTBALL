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

from competitions.ucl.historical_backfill import contract

SEASONS = [s for s in contract.SEASONS if os.path.isdir(contract.season_dir(s))]
SIGNAL_ORDER = ["market_odds", "refined_elo", "rolling_form", "rest_days"]

PROD_WEIGHTS_RAW = {
    "market_odds": 0.203813,
    "refined_elo": 0.191216,
    "rolling_form": 0.197345,
    "rest_days": 0.203813,
    "squad_value": 0.203813,
}

_WINDOW = (
    f"{contract.SEASONS[SEASONS[0]]}-{contract.SEASONS[SEASONS[-1]]}"
    if SEASONS
    else "none"
)
DATASET = f"competitions/ucl/data/historical ({_WINDOW})"

# Competition-specific declarations rendered once, before the first UCL 1X2
# number, by the shared renderer's "## Declarations" block. The knockout
# mapping (D-05/D-06) must be declared before any UCL number is published.
_EXTRA_DECLARATIONS = [
    "Knockout mapping (D-05/D-06): UCL ties are two-legged, so a per-match "
    "\"advancing winner\" cannot be derived from a single match. Every UCL "
    "match in this report is scored as a three-way H/D/A outcome on that leg's "
    "own result (90/120-minute score); the two-legged tie winner is a separate "
    "figure and is not scored here. No per-match advancing-winner label is "
    "applied to UCL.",
    "Reconciliation with `football_core/elo.py:37`: the Elo update codes a "
    "penalty-shootout win as `W = 0.75/0.25` (a two-way partial result), "
    "whereas a leg result is a three-way H/D/A. The two codings must not be "
    "conflated: a shootout outcome is never rendered as a draw in the tie "
    "figure, and the per-match 1X2 labels stay three-way.",
    "LaLiga has no knockout stage, so this knockout mapping applies to UCL only.",
]

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
    results = run_evaluation(OUT_PATH, HISTORICAL_DIR, SEASONS, SIGNAL_ORDER,
                             PROD_WEIGHTS_RAW, DATASET, _HARNESS)
    md = render_evaluation_markdown(
        results, competition="UCL", extra_declarations=_EXTRA_DECLARATIONS,
    )
    atomic_write_text(Path(os.path.join(OUT_DIR, "EVALUATION.md")), md)


if __name__ == "__main__":
    main()
