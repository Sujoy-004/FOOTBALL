"""Evaluation metrics for prediction quality assessment.
Provides Brier score, log loss, calibration curves, and ECE computation.
"""

import copy
import math
from datetime import datetime, timezone

from src.elo import apply_elo_update, expected_score
from src.state import append_prediction_history, load_prediction_history


def brier_score(prediction: float, actual: float) -> float:
    return (prediction - actual) ** 2


def log_loss(prediction: float, actual: float, eps: float = 1e-15) -> float:
    p = max(eps, min(1 - eps, prediction))
    if actual == 0.5:
        return -0.5 * (math.log(p) + math.log(1 - p))
    return -(actual * math.log(p) + (1 - actual) * math.log(1 - p))


def compute_metrics(predictions: list[float], actuals: list[float]) -> dict:
    if not predictions or len(predictions) != len(actuals):
        return {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0}
    n = len(predictions)
    brier_sum = ll_sum = 0.0
    correct = 0.0
    for p, a in zip(predictions, actuals):
        brier_sum += brier_score(p, a)
        ll_sum += log_loss(p, a)
        if a == 0.5:
            correct += 0.5
        elif (p >= 0.5 and a == 1.0) or (p < 0.5 and a == 0.0):
            correct += 1
    return {"brier": brier_sum / n, "log_loss": ll_sum / n, "accuracy": correct / n, "n": n}


def calibration_curve(predictions: list[float], actuals: list[float], n_bins: int = 10) -> dict:
    bins = []
    for i in range(n_bins):
        lo, hi = i / n_bins, (i + 1) / n_bins
        bin_preds, bin_actuals = [], []
        for p, a in zip(predictions, actuals):
            if lo <= p < hi or (i == n_bins - 1 and p == 1.0):
                bin_preds.append(p)
                bin_actuals.append(a)
        if bin_preds:
            mean_pred = sum(bin_preds) / len(bin_preds)
            frac_pos = sum(a for a in bin_actuals) / len(bin_actuals)
            bins.append({"bin_start": round(lo, 2), "bin_end": round(hi, 2), "count": len(bin_preds), "mean_predicted": round(mean_pred, 4), "fraction_positives": round(frac_pos, 4)})
        else:
            bins.append({"bin_start": round(lo, 2), "bin_end": round(hi, 2), "count": 0, "mean_predicted": 0.0, "fraction_positives": 0.0})
    ece = expected_calibration_error({"bins": bins})
    return {"bins": bins, "ece": round(ece, 6)}


def expected_calibration_error(calibration: dict) -> float:
    bins = calibration.get("bins", [])
    total = sum(b.get("count", 0) for b in bins)
    if total == 0:
        return 0.0
    ece = 0.0
    for b in bins:
        n = b.get("count", 0)
        if n > 0:
            ece += (n / total) * abs(b["mean_predicted"] - b["fraction_positives"])
    return ece


def evaluate_all_matches(
    teams: dict[str, dict],
    played: dict[str, dict],
    played_groups: dict[str, dict],
    signal_name: str | None = None,
) -> dict:
    """Evaluate prediction performance for one or all signals.

    Args:
        teams: Team data dict (name -> {elo: int}).
        played: Dict of played knockout matches.
        played_groups: Dict of played group matches.
        signal_name: Which signal to evaluate.
            - None (default, D-11): Multi-signal report with all available signal keys.
            - "elo": Replay through Elo pipeline (existing behavior), produce compound entries.
            - "market_odds", "catboost", "blended": Read from prediction_history compound entries.

    Returns:
        Report dict with metrics, calibration, and model info.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── Case: signal_name is None (D-11 default — all available signals) ──
    if signal_name is None:
        history = load_prediction_history()
        if not history:
            return {
                "model": "all_signals",
                "phase": "13",
                "generated_at": now_iso,
                "signals": {},
                "n_history_entries": 0,
            }
        # Collect all signal keys from compound entries
        all_signal_keys: set[str] = set()
        for entry in history:
            signals = entry.get("signals", {})
            if isinstance(signals, dict):
                all_signal_keys.update(signals.keys())
        if not all_signal_keys:
            return {
                "model": "all_signals",
                "phase": "13",
                "generated_at": now_iso,
                "signals": {},
                "n_history_entries": len(history),
            }
        signals_report: dict[str, dict] = {}
        for sig_key in sorted(all_signal_keys):
            preds: list[float] = []
            actuals: list[float] = []
            for entry in history:
                signals = entry.get("signals", {})
                if not isinstance(signals, dict):
                    continue
                sig = signals.get(sig_key)
                if not isinstance(sig, dict):
                    continue
                if not sig.get("available", False):
                    continue
                prob = sig.get("probability")
                if prob is None:
                    continue
                actual = entry.get("actual")
                if actual is None:
                    continue
                preds.append(prob)
                actuals.append(actual)
            if not preds:
                signals_report[sig_key] = {
                    "metrics": {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0},
                    "calibration": {"bins": [], "ece": 0.0},
                    "n_matches": 0,
                }
            else:
                metrics = compute_metrics(preds, actuals)
                cal = calibration_curve(preds, actuals)
                signals_report[sig_key] = {
                    "metrics": {
                        "brier": round(metrics["brier"], 6),
                        "log_loss": round(metrics["log_loss"], 6),
                        "accuracy": round(metrics["accuracy"], 6),
                        "n": metrics["n"],
                    },
                    "calibration": cal,
                    "n_matches": metrics["n"],
                }
        return {
            "model": "all_signals",
            "phase": "13",
            "generated_at": now_iso,
            "signals": signals_report,
            "n_history_entries": len(history),
        }

    # ── Case: signal_name == "elo" — Replay through Elo pipeline ──
    if signal_name == "elo":
        all_matches: list[dict] = []
        for match_dict in [played, played_groups]:
            for m in match_dict.values():
                all_matches.append(dict(m))
        all_matches.sort(key=lambda x: (x.get("completed_at", ""), x.get("match_id", "")))
        replay_teams = copy.deepcopy(teams)
        predictions: list[float] = []
        actuals: list[float] = []
        history_entries: list[dict] = []
        for m in all_matches:
            t_a, t_b = m["team_a"], m["team_b"]
            if t_a not in replay_teams or t_b not in replay_teams:
                continue
            p_a = expected_score(replay_teams[t_a]["elo"], replay_teams[t_b]["elo"])
            winner = m.get("winner")
            if winner is None:
                actual_a = 0.5
            elif winner == t_a:
                actual_a = 1.0
            elif winner == t_b:
                actual_a = 0.0
            else:
                continue
            predictions.append(p_a)
            actuals.append(actual_a)
            # Compound format entry (D-01) — no top-level prediction/signal keys
            history_entries.append({
                "match_id": m.get("match_id", ""),
                "timestamp": now_iso,
                "team_a": t_a,
                "team_b": t_b,
                "actual": actual_a,
                "signals": {
                    "elo": {
                        "probability": round(p_a, 4),
                        "version": "v1",
                        "timestamp": now_iso,
                        "available": True,
                        "team_a_elo": replay_teams[t_a]["elo"],
                        "team_b_elo": replay_teams[t_b]["elo"],
                    }
                },
            })
            try:
                apply_elo_update(m, replay_teams)
            except Exception:
                pass
        if not predictions:
            return {
                "model": "elo-only", "phase": "13",
                "generated_at": now_iso, "n_matches": 0,
                "metrics": {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0},
                "calibration": {"bins": [], "ece": 0.0},
                "history_file": "data/prediction_history.json", "n_history_entries": 0,
            }
        metrics = compute_metrics(predictions, actuals)
        cal = calibration_curve(predictions, actuals)
        report = {
            "model": "elo-only", "phase": "13",
            "generated_at": now_iso, "n_matches": metrics["n"],
            "metrics": {
                "brier": round(metrics["brier"], 6),
                "log_loss": round(metrics["log_loss"], 6),
                "accuracy": round(metrics["accuracy"], 6),
                "brier_skill_score": 0.0,
                "n": metrics["n"],
            },
            "calibration": cal,
            "history_file": "data/prediction_history.json",
            "n_history_entries": len(history_entries),
        }
        for entry in history_entries:
            try:
                append_prediction_history(entry)
            except Exception:
                pass
        return report

    # ── Case: Other signal_name (market_odds, catboost, blended) ──
    # Read from prediction_history compound entries
    history = load_prediction_history()
    if not history:
        return {
            "model": signal_name, "phase": "13",
            "generated_at": now_iso, "n_matches": 0,
            "metrics": {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0},
            "calibration": {"bins": [], "ece": 0.0},
            "history_file": "data/prediction_history.json", "n_history_entries": 0,
        }
    signal_preds: list[float] = []
    signal_actuals: list[float] = []
    for entry in history:
        signals = entry.get("signals", {})
        if not isinstance(signals, dict):
            continue
        sig = signals.get(signal_name)
        if not isinstance(sig, dict):
            continue
        if not sig.get("available", False):
            continue
        prob = sig.get("probability")
        if prob is None:
            continue
        actual = entry.get("actual")
        if actual is None:
            continue
        signal_preds.append(prob)
        signal_actuals.append(actual)
    if not signal_preds:
        return {
            "model": signal_name, "phase": "13",
            "generated_at": now_iso, "n_matches": 0,
            "metrics": {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0},
            "calibration": {"bins": [], "ece": 0.0},
            "history_file": "data/prediction_history.json",
            "n_history_entries": len(history),
        }
    metrics = compute_metrics(signal_preds, signal_actuals)
    cal = calibration_curve(signal_preds, signal_actuals)
    return {
        "model": signal_name, "phase": "13",
        "generated_at": now_iso, "n_matches": metrics["n"],
        "metrics": {
            "brier": round(metrics["brier"], 6),
            "log_loss": round(metrics["log_loss"], 6),
            "accuracy": round(metrics["accuracy"], 6),
            "brier_skill_score": 0.0,
            "n": metrics["n"],
        },
        "calibration": cal,
        "history_file": "data/prediction_history.json",
        "n_history_entries": len(history),
    }


def compare_baselines(before: dict, after: dict) -> dict:
    b_m, a_m = before.get("metrics", {}), after.get("metrics", {})
    def delta(key):
        return round(a_m.get(key, 0) - b_m.get(key, 0), 6)
    return {
        "comparison": f"{before.get('model', '?')} vs {after.get('model', '?')}",
        "before": {"model": before.get("model"), "generated_at": before.get("generated_at"), "n_matches": before.get("n_matches"), "metrics": b_m, "ece": before.get("calibration", {}).get("ece")},
        "after": {"model": after.get("model"), "generated_at": after.get("generated_at"), "n_matches": after.get("n_matches"), "metrics": a_m, "ece": after.get("calibration", {}).get("ece")},
        "deltas": {"brier": delta("brier"), "log_loss": delta("log_loss"), "accuracy": delta("accuracy"), "ece": round(after.get("calibration", {}).get("ece", 0) - before.get("calibration", {}).get("ece", 0), 6), "n_matches": a_m.get("n", 0) - b_m.get("n", 0)},
        "verdict": "IMPROVED" if a_m.get("brier", 0) - b_m.get("brier", 0) < -0.01 else "REGRESSED" if a_m.get("brier", 0) - b_m.get("brier", 0) > 0.01 else "SIMILAR",
    }
