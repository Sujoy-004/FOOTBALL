"""Offline weight calibration for UCL prediction signals.

Reads replay data via historical.py, evaluates available signals with
leak-free chronological context, computes per-signal multi-class log-loss,
derives inverse-log-loss weights, and writes them atomically to
signal_weights.json.

Usage:
    from competitions.ucl.src.calibrate import run_calibration
    config = run_calibration(replay_data_path="path/to/results.json")
"""

import datetime
import json
import logging
import math
import os
import re
import tempfile

from football_core.evaluation import multi_class_log_loss
from football_core.blender import compute_log_loss_weights
from football_core.signal import PredictionContext, SignalRegistry

from competitions.ucl.src.historical import (
    ReplayResultProvider,
    available_signals,
    build_context_for_match,
    frequency_baseline,
    gate_verdict,
    load_replay_matches,
    order_matches,
    split_chronological,
)

logger = logging.getLogger(__name__)

DEFAULT_THRESHOLD = 20  # minimum matches for a signal to be included

_MD_RE = re.compile(r"^MD(\d{2})[_\-]", re.IGNORECASE)


class _EmptyResultProvider:
    """Compatibility result provider returning no historical results.

    Calibration evaluates rolling form via the leak-free context built by
    historical.build_context_for_match; this provider is only used so signal
    registries can be constructed without a concrete replay store.
    """

    def get_team_results(self, team, before_date, limit=10):
        return []


def _build_signal_registry() -> SignalRegistry:
    """Build the standard UCL signal registry (all signals, unfiltered).

    Preserved for backward-compatible test imports. Calibration uses
    available_signals() to filter which signals to actually evaluate.
    """
    from football_core.signals.refined_elo import RefinedEloSignal
    from football_core.signals.market_odds import MarketOddsSignal
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signals.squad_value import SquadValueSignal
    from football_core.signals.rest_days import RestDaysSignal

    registry = SignalRegistry()
    registry.register(RefinedEloSignal())
    registry.register(MarketOddsSignal())
    registry.register(RollingFormSignal(result_provider=_EmptyResultProvider()))
    registry.register(SquadValueSignal())
    registry.register(RestDaysSignal())
    return registry


def _get_default_output_path() -> str:
    """Return the default path for signal_weights.json relative to this file."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "signal_weights.json",
    )


def _build_available_registry(
    avail: dict[str, str],
    squad_values_path: str | None,
    *,
    rolling_form_provider=None,
) -> SignalRegistry:
    """Build a registry containing only available signals."""
    registry = SignalRegistry()
    for name, status in avail.items():
        if status != "available":
            continue
        if name == "squad_value":
            from football_core.signals.squad_value import SquadValueSignal
            registry.register(SquadValueSignal(data_path=squad_values_path))
        elif name == "refined_elo":
            from football_core.signals.refined_elo import RefinedEloSignal
            registry.register(RefinedEloSignal())
        elif name == "market_odds":
            from football_core.signals.market_odds import MarketOddsSignal
            registry.register(MarketOddsSignal())
        elif name == "rolling_form":
            from football_core.signals.rolling_form import RollingFormSignal

            registry.register(
                RollingFormSignal(
                    result_provider=rolling_form_provider or _EmptyResultProvider()
                )
            )
        elif name == "rest_days":
            from football_core.signals.rest_days import RestDaysSignal
            registry.register(RestDaysSignal())
    return registry


def _signal_predictions_vary(
    predictions: list[list[float]], eps: float = 1e-10
) -> bool:
    """True if the signal produces non-identical predictions across matches."""
    if len(predictions) < 2:
        return False
    first = predictions[0]
    return any(
        abs(p[0] - first[0]) > eps or abs(p[1] - first[1]) > eps or abs(p[2] - first[2]) > eps
        for p in predictions[1:]
    )


def _detect_oos_matchdays(matches: list[dict]) -> list[int] | None:
    """Detect distinct matchdays from MD IDs. Returns list of ints or None."""
    mds: set[int] = set()
    for m in matches:
        md = _MD_RE.match(str(m.get("match_id", "")))
        if md:
            mds.add(int(md.group(1)))
    if not mds:
        return None
    return sorted(mds)


def _load_squad_values(path: str | None) -> dict[str, float]:
    """Load squad values from a JSON file. Returns {} on failure."""
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def run_calibration(
    replay_data_path: str,
    threshold: int = DEFAULT_THRESHOLD,
    output_path: str | None = None,
    *,
    oos_matchdays: int | None = None,
    oos_fraction: float = 0.3,
    min_oos: int = 30,
    require_verified: bool = False,
    squad_values_path: str | None = None,
    elo_ratings: dict[str, float] | None = None,
) -> dict:
    """Run weight calibration using replay data.

    Loads matches via historical.load_replay_matches, splits
    chronologically, builds leak-free contexts via
    historical.build_context_for_match, evaluates only available signals,
    and computes per-signal multi-class log-loss (football_core.evaluation
    multi_class_log_loss).

    Args:
        replay_data_path: Path to replay JSON file.
        threshold: Minimum fit matches for a signal to be included.
        output_path: Path for output signal_weights.json.
        oos_matchdays: Explicit list of matchday ints to hold out.
            None -> auto-detect (last 3 if >= 4 matchdays; else
            split_chronological with oos_fraction).
        oos_fraction: Fraction for split_chronological fallback.
        min_oos: Minimum OOS matches for a PASS gate verdict.
        require_verified: If True and verdict != PASS, do not write output.
            Additionally, UNVERIFIED calibrations are never written to the
            production signal_weights.json (only to an explicit output_path).
        squad_values_path: Path to squad_values.json. Default resolves
            relative to this file.
        elo_ratings: Pre-loaded elo map. Default {} (no fabrication).

    Returns:
        Full config dict with weights, metrics, split info, and verdict.

    Raises:
        FileNotFoundError: If replay_data_path doesn't exist.
        ValueError: On empty or unparseable replay data.
    """
    # Resolve default squad_values_path
    if squad_values_path is None:
        candidate = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "squad_values.json",
        )
        if os.path.exists(candidate):
            squad_values_path = candidate

    elo = elo_ratings or {}
    squad_values = _load_squad_values(squad_values_path)

    # 1. Load replay data
    matches = load_replay_matches(replay_data_path)
    if not matches:
        raise ValueError(f"No matches loaded from replay data: {replay_data_path}")

    # 2. Chronological split
    if oos_matchdays is not None and oos_matchdays > 0:
        try:
            fit, oos, split_meta = split_chronological(
                matches, oos_matchdays=oos_matchdays, oos_fraction=oos_fraction,
            )
        except ValueError as e:
            if not matches:
                raise ValueError(
                    f"No matches loaded from replay data: {replay_data_path}"
                ) from e
            raise ValueError(
                "Not enough historical matches for calibration "
                f"({len(matches)} matches, cannot split: {e})"
            ) from e
    else:
        # Auto-detect: if >= 4 distinct matchdays, hold out last 3
        detected = _detect_oos_matchdays(matches)
        if detected is not None and len(detected) >= 4:
            last_3 = detected[-3:]
            try:
                fit, oos, split_meta = split_chronological(
                    matches, oos_matchdays=len(last_3), oos_fraction=oos_fraction,
                )
            except ValueError as e:
                raise ValueError(
                    "Not enough historical matches for calibration "
                    f"({len(matches)} matches, cannot split: {e})"
                ) from e
        else:
            try:
                fit, oos, split_meta = split_chronological(
                    matches, oos_fraction=oos_fraction,
                )
            except ValueError as e:
                if not matches:
                    raise ValueError(
                        f"No matches loaded from replay data: {replay_data_path}"
                    ) from e
                raise ValueError(
                    "Not enough historical matches for calibration "
                    f"({len(matches)} matches, cannot split: {e})"
                ) from e

    n_fit = split_meta["n_fit"]
    n_oos = split_meta["n_oos"]
    chronology = split_meta["chronology"]

    if n_oos < 1:
        raise ValueError(
            f"Not enough historical matches for calibration "
            f"({len(matches)} matches, 0 out-of-sample)"
        )

    # 3. Check signal availability on full dataset
    avail = available_signals(
        matches, squad_values=squad_values or None, elo_ratings=elo or None,
    )
    avail_names = [n for n, s in avail.items() if s == "available"]

    # 4. Build registry with only available signals
    rolling_form_provider = ReplayResultProvider(order_matches(matches))
    registry = _build_available_registry(
        avail, squad_values_path, rolling_form_provider=rolling_form_provider,
    )

    # 5. Build contexts and evaluate
    fit_pred_by_sig: dict[str, list[list[float]]] = {n: [] for n in avail_names}
    fit_actuals: list[int] = []

    for m in fit:
        ctx = build_context_for_match(
            m, matches, elo_ratings=elo, squad_values=squad_values or None,
        )
        idx = _outcome_index(m)
        if idx is None:
            continue
        fit_actuals.append(idx)
        outputs = registry.evaluate(m, ctx)
        for sig_name in avail_names:
            if sig_name in outputs:
                out = outputs[sig_name]
                fit_pred_by_sig[sig_name].append([out.home_prob, out.draw_prob, out.away_prob])

    # 6. Per-signal fit log-loss (only for signals with data)
    fit_ll: dict[str, float] = {}
    for sig_name in avail_names:
        preds = fit_pred_by_sig[sig_name]
        if len(preds) >= threshold:
            fit_ll[sig_name] = multi_class_log_loss(preds, fit_actuals)

    # 7. Weights from fit-set log-losses
    weights = compute_log_loss_weights(fit_ll) if fit_ll else {}

    # 8. Ensemble in-sample log-loss (weighted blend on FIT set)
    in_sample_ll = None
    if fit_actuals:
        fit_ensemble_preds = _blend_ensemble(
            fit_pred_by_sig, weights, avail_names, fit_actuals,
        )
        in_sample_ll = multi_class_log_loss(fit_ensemble_preds, fit_actuals)

    # 9. OOS evaluation
    oos_pred_by_sig: dict[str, list[list[float]]] = {n: [] for n in avail_names}
    oos_actuals: list[int] = []

    for m in oos:
        ctx = build_context_for_match(
            m, matches, elo_ratings=elo, squad_values=squad_values or None,
        )
        idx = _outcome_index(m)
        if idx is None:
            continue
        oos_actuals.append(idx)
        outputs = registry.evaluate(m, ctx)
        for sig_name in avail_names:
            if sig_name in outputs:
                out = outputs[sig_name]
                oos_pred_by_sig[sig_name].append([out.home_prob, out.draw_prob, out.away_prob])

    # Per-signal OOS log-loss
    oos_per_signal: dict[str, dict] = {}
    for sig_name in avail_names:
        preds = oos_pred_by_sig[sig_name]
        n_sig = len(preds)
        if n_sig > 0:
            ll = multi_class_log_loss(preds, oos_actuals)
            oos_per_signal[sig_name] = {"log_loss": round(ll, 6), "n": n_sig}
        else:
            oos_per_signal[sig_name] = {"log_loss": None, "n": 0}

    # Ensemble OOS log-loss
    ensemble_oos_ll = None
    uniform_oos_ll = None
    freq_oos_ll = None

    if oos_actuals:
        oos_ensemble_preds = _blend_ensemble(
            oos_pred_by_sig, weights, avail_names, oos_actuals,
        )
        ensemble_oos_ll = multi_class_log_loss(oos_ensemble_preds, oos_actuals)

        # Uniform 1/3 baseline
        uniform_oos_ll = multi_class_log_loss(
            [[1 / 3, 1 / 3, 1 / 3]] * len(oos_actuals), oos_actuals,
        )

        # Frequency baseline from FIT matches
        freq = frequency_baseline(fit)
        if freq is not None:
            freq_dist = [freq["home"], freq["draw"], freq["away"]]
            freq_oos_ll = multi_class_log_loss(
                [freq_dist] * len(oos_actuals), oos_actuals,
            )

    # 10. Count "real" OOS signals (available + predictions vary)
    n_real_signals = sum(
        1 for sig_name in avail_names
        if _signal_predictions_vary(oos_pred_by_sig[sig_name])
    )

    # 11. Gate verdict
    verdict = gate_verdict(
        n_oos=n_oos,
        chronology=chronology,
        ensemble_ll=ensemble_oos_ll if ensemble_oos_ll is not None else float("inf"),
        uniform_ll=uniform_oos_ll,
        freq_ll=freq_oos_ll,
        n_real_signals=n_real_signals,
        min_oos=min_oos,
        min_signals=2,
    )

    # 12. Per-signal fit stats
    per_signal: dict[str, dict] = {}
    for sig_name in sorted(set(list(fit_pred_by_sig.keys()) + list(avail_names))):
        fit_preds_n = len(fit_pred_by_sig.get(sig_name, []))
        per_signal[sig_name] = {
            "log_loss": round(fit_ll.get(sig_name, 0), 6) if sig_name in fit_ll else None,
            "n_matches": fit_preds_n,
            "excluded": sig_name not in weights,
            "availability": avail.get(sig_name, "not_registered"),
        }

    # 13. Assemble config
    config = {
        "version": 1,
        "calibrated_at": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
        "method": "inverse_log_loss",
        "source": replay_data_path,
        "n_matches": len(fit_actuals) + len(oos_actuals),
        "threshold": threshold,
        "weights": weights,
        "metric": "multi_class_log_loss",
        "per_signal": per_signal,
        "split": {
            "n_fit": n_fit,
            "n_oos": n_oos,
            "chronology": chronology,
        },
        "signals_available": avail,
        "in_sample": {
            "n": len(fit_actuals),
            "ensemble_log_loss": round(in_sample_ll, 6) if in_sample_ll is not None else None,
            "per_signal": {
                sig: {"log_loss": round(fit_ll[sig], 6), "n": len(fit_pred_by_sig[sig])}
                for sig in avail_names
                if sig in fit_ll
            },
        },
        "out_of_sample": {
            "n": len(oos_actuals),
            "ensemble_log_loss": round(ensemble_oos_ll, 6) if ensemble_oos_ll is not None else None,
            "uniform_log_loss": round(uniform_oos_ll, 6) if uniform_oos_ll is not None else None,
            "frequency_log_loss": round(freq_oos_ll, 6) if freq_oos_ll is not None else None,
            "per_signal": oos_per_signal,
        },
        "verdict": verdict,
        "written": False,
    }

    # 14. Write gate
    output = output_path or _get_default_output_path()
    is_production = os.path.abspath(output) == os.path.abspath(
        _get_default_output_path()
    )
    do_write = True
    if verdict["status"] != "PASS":
        if require_verified:
            do_write = False
        elif is_production:
            # Never silently overwrite production weights with an UNVERIFIED
            # calibration. UNVERIFIED results may only be written to an
            # explicit (non-production) output_path.
            do_write = False
            verdict["reasons"] = verdict["reasons"] + [
                "refusing to overwrite production signal_weights.json "
                "with an UNVERIFIED calibration"
            ]

    if do_write:
        config["written"] = True
        os.makedirs(os.path.dirname(output), exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", delete=False, suffix=".tmp", encoding="utf-8",
        ) as f:
            json.dump(config, f, indent=2)
            tmp_path = f.name
        os.replace(tmp_path, output)
        logger.info("Calibration weights written to %s", output)

    return config


def _outcome_index(match: dict) -> int | None:
    """0 = home win, 1 = draw, 2 = away win. None if scores missing."""
    hs = match.get("home_score")
    aws = match.get("away_score")
    if hs is None or aws is None:
        return None
    if hs > aws:
        return 0
    if aws > hs:
        return 2
    return 1


def _blend_ensemble(
    pred_by_sig: dict[str, list[list[float]]],
    weights: dict[str, float],
    avail_names: list[str],
    actuals: list[int],
) -> list[list[float]]:
    """Blend per-signal predictions using fitted weights."""
    n = len(actuals)
    if n == 0:
        return []
    active_names = [s for s in avail_names if s in weights and weights[s] > 0 and pred_by_sig[s]]
    if not active_names:
        return [[1 / 3, 1 / 3, 1 / 3]] * n
    total_w = sum(weights[s] for s in active_names)
    norm = {s: weights[s] / total_w for s in active_names}
    blended = []
    for i in range(n):
        h = sum(norm[s] * pred_by_sig[s][i][0] for s in active_names)
        d = sum(norm[s] * pred_by_sig[s][i][1] for s in active_names)
        a = sum(norm[s] * pred_by_sig[s][i][2] for s in active_names)
        total = h + d + a
        if total > 0:
            h, d, a = h / total, d / total, a / total
        blended.append([h, d, a])
    return blended
