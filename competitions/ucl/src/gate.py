"""Match-level evaluation gate for champion-probability predictions.

Replays every available historical match in chronological order, builds
a leak-free PredictionContext for each, runs the standard five-signal
ensemble, and evaluates ensemble + per-signal accuracy against actual
outcomes.  The gate verdict determines whether champion probabilities
are REPORTED as VERIFIED or carry an explicit UNVERIFIED warning.

Usage:
    from competitions.ucl.src.gate import evaluate_matches, load_gate_inputs, verdict_status
"""

from __future__ import annotations

import logging
import math
import os
from datetime import datetime, timezone
from typing import Any

from football_core.blender import (
    EnsembleEngine,
    compute_log_loss_weights,
)
from football_core.evaluation import (
    multi_class_brier,
    multi_class_ece,
    multi_class_log_loss,
)
from football_core.signal import PredictionContext, SignalOutput

from competitions.ucl.src.historical import (
    ReplayResultProvider,
    available_signals,
    build_context_for_match,
    chronological_key,
    frequency_baseline,
    gate_verdict,
    load_replay_matches,
    order_matches,
    outcome_index,
)

logger = logging.getLogger(__name__)

_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)


class _EmptyResultProvider:
    """Minimal stub returning empty results — matches calibrate.py pattern."""

    def get_team_results(self, team: str, before_date: str, limit: int = 10) -> list[dict]:
        return []


def _build_signal_engine(
    *,
    elo_ratings: dict[str, float] | None = None,
    squad_values: dict[str, float] | None = None,
    results_file: str | None = None,
    weights: dict[str, float] | None = None,
    result_provider=None,
) -> EnsembleEngine:
    """Construct the standard five-signal engine — mirrors orchestrator.build_signal_engine wiring."""
    from football_core.signals.refined_elo import RefinedEloSignal
    from football_core.signals.market_odds import MarketOddsSignal
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signals.squad_value import SquadValueSignal
    from football_core.signals.rest_days import RestDaysSignal

    sv_path = os.path.join(_DATA_DIR, "squad_values.json")

    signals = [
        RefinedEloSignal(),
        MarketOddsSignal(),
        RollingFormSignal(
            result_provider=result_provider or _EmptyResultProvider(),
        ),
        SquadValueSignal(data_path=sv_path),
        RestDaysSignal(),
    ]

    if weights is not None:
        return EnsembleEngine(signals, weights=weights)

    weights_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "signal_weights.json",
    )
    if os.path.exists(weights_path):
        return EnsembleEngine(signals, weights_path=weights_path)

    return EnsembleEngine(signals)


def _detect_chronology(matches: list[dict]) -> str:
    """Determine chronology kind from the ordered matches."""
    if not matches:
        return "position"
    has_date = any(m.get("event_date") for m in matches)
    has_md = any(
        chronological_key(m, i)[0] == "matchday"
        for i, m in enumerate(matches)
    )
    if has_date:
        return "date"
    if has_md:
        return "matchday"
    return "position"


def _is_signal_varying(
    signal_probs: list[list[float]],
    eps: float = 1e-9,
) -> bool:
    """True if signal produced genuinely different prediction vectors across matches."""
    if len(signal_probs) < 2:
        return False
    first = signal_probs[0]
    for p in signal_probs[1:]:
        if any(abs(p[k] - first[k]) > eps for k in range(3)):
            return True
    return False


def evaluate_matches(
    matches: list[dict],
    *,
    elo_ratings: dict[str, float] | None = None,
    squad_values: dict[str, float] | None = None,
    engine: EnsembleEngine | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """Replay historical matches and evaluate ensemble accuracy.

    Builds a leak-free PredictionContext for each completed match (prior-only),
    runs the five-signal ensemble, and computes multi-class log-loss,
    Brier, and ECE for the ensemble and each individual signal.

    Returns a dict with keys: n, n_real_signals, signals_available, per_signal,
    baselines, ensemble, chronology, verdict, evaluated_at.

    Never raises — degrades gracefully to UNVERIFIED on any edge case.
    """
    if not matches:
        return {
            "n": 0,
            "n_real_signals": 0,
            "signals_available": {},
            "per_signal": {},
            "baselines": {"uniform_log_loss": None, "frequency_log_loss": None},
            "ensemble": {"log_loss": None, "brier": None, "ece": None},
            "chronology": "position",
            "verdict": {"status": "UNVERIFIED", "reasons": ["no evaluable historical matches"]},
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    ordered = order_matches(matches)
    completed = [m for m in ordered if outcome_index(m) is not None]

    if not completed:
        return {
            "n": 0,
            "n_real_signals": 0,
            "signals_available": {},
            "per_signal": {},
            "baselines": {"uniform_log_loss": None, "frequency_log_loss": None},
            "ensemble": {"log_loss": None, "brier": None, "ece": None},
            "chronology": _detect_chronology(ordered),
            "verdict": {"status": "UNVERIFIED", "reasons": ["no evaluable historical matches"]},
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    sig_avail = available_signals(
        matches,
        squad_values=squad_values,
        elo_ratings=elo_ratings,
    )

    if engine is None:
        engine = _build_signal_engine(
            elo_ratings=elo_ratings,
            squad_values=squad_values,
            weights=weights,
            result_provider=ReplayResultProvider(completed),
    )

    ensemble_probs: list[list[float]] = []
    ensemble_actuals: list[int] = []
    per_signal_probs: dict[str, list[list[float]]] = {}
    per_signal_actuals: dict[str, list[int]] = {}

    for match in completed:
        ctx = build_context_for_match(
            match,
            ordered,
            squad_values=squad_values,
            elo_ratings=elo_ratings,
        )
        bp = engine.evaluate(match, ctx)
        actual = outcome_index(match)
        ensemble_probs.append([bp.home_prob, bp.draw_prob, bp.away_prob])
        ensemble_actuals.append(actual)

        for sig_name, sig_data in bp.signal_breakdown.items():
            if sig_name not in per_signal_probs:
                per_signal_probs[sig_name] = []
                per_signal_actuals[sig_name] = []
            per_signal_probs[sig_name].append([
                sig_data.get("home", 1 / 3),
                sig_data.get("draw", 1 / 3),
                sig_data.get("away", 1 / 3),
            ])
            per_signal_actuals[sig_name].append(actual)

    n = len(completed)

    # Uniform baseline: always predict 1/3 each
    uniform_ll = None
    if n > 0:
        uniform_probs = [[1 / 3, 1 / 3, 1 / 3]] * n
        uniform_ll = multi_class_log_loss(uniform_probs, ensemble_actuals)

    # Frequency baseline: fit on all data (chronological; in a real
    # evaluation you'd split fit/oos, but here we use the full set
    # to compute the empirical baseline applied to every match).
    freq_rates = frequency_baseline(completed)
    freq_ll = None
    if n > 0:
        freq_probs = [[freq_rates["home"], freq_rates["draw"], freq_rates["away"]]] * n
        freq_ll = multi_class_log_loss(freq_probs, ensemble_actuals)

    # Ensemble metrics
    ens_ll = multi_class_log_loss(ensemble_probs, ensemble_actuals) if n > 0 else None
    ens_brier = multi_class_brier(ensemble_probs, ensemble_actuals) if n > 0 else None
    ens_ece = multi_class_ece(ensemble_probs, ensemble_actuals) if n > 0 else None

    # Per-signal metrics
    per_signal: dict[str, dict] = {}
    for sig_name in sorted(per_signal_probs):
        probs = per_signal_probs[sig_name]
        actuals = per_signal_actuals[sig_name]
        sig_available = sig_avail.get(sig_name, "unknown").startswith("available")
        constant = not _is_signal_varying(probs)
        sig_ll = multi_class_log_loss(probs, actuals) if probs else None
        per_signal[sig_name] = {
            "log_loss": sig_ll,
            "n": len(probs),
            "constant": constant,
            "available": sig_available,
        }

    # Count "real" signals: available AND genuinely varying
    n_real_signals = sum(
        1 for name, ps in per_signal.items()
        if ps["available"] and not ps["constant"]
    )

    chronology = _detect_chronology(ordered)

    verdict = gate_verdict(
        n_oos=n,
        chronology=chronology,
        ensemble_ll=ens_ll if ens_ll is not None else float("inf"),
        uniform_ll=uniform_ll,
        freq_ll=freq_ll,
        n_real_signals=n_real_signals,
    )

    return {
        "n": n,
        "n_real_signals": n_real_signals,
        "signals_available": sig_avail,
        "per_signal": per_signal,
        "baselines": {
            "uniform_log_loss": uniform_ll,
            "frequency_log_loss": freq_ll,
        },
        "ensemble": {
            "log_loss": ens_ll,
            "brier": ens_brier,
            "ece": ens_ece,
        },
        "chronology": chronology,
        "verdict": verdict,
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


def load_gate_inputs() -> tuple[list[dict], dict[str, float] | None]:
    """Load results.json + squad_values.json from the UCL data directory.

    Returns (matches, squad_values).  Tolerates missing files and
    various JSON shapes (list or {"matches": [...]}).
    """
    results_path = os.path.join(_DATA_DIR, "results.json")
    sv_path = os.path.join(_DATA_DIR, "squad_values.json")

    matches: list[dict] = []
    if os.path.exists(results_path):
        try:
            matches = load_replay_matches(results_path)
        except Exception:
            logger.warning("Could not load results.json for gate evaluation", exc_info=True)

    squad_values: dict[str, float] | None = None
    if os.path.exists(sv_path):
        try:
            import json
            with open(sv_path) as f:
                sv_data = json.load(f)
            if isinstance(sv_data, dict):
                squad_values = sv_data
        except Exception:
            logger.warning("Could not load squad_values.json for gate evaluation", exc_info=True)

    return matches, squad_values


def verdict_status(evaluation: dict | None) -> str:
    """Extract gate status from an evaluation dict. Returns 'UNVERIFIED' when missing."""
    if not evaluation or not isinstance(evaluation, dict):
        return "UNVERIFIED"
    verdict = evaluation.get("verdict")
    if not verdict or not isinstance(verdict, dict):
        return "UNVERIFIED"
    status = verdict.get("status")
    if status in ("PASS", "UNVERIFIED"):
        return status
    return "UNVERIFIED"
