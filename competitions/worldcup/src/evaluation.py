"""Evaluation metrics for prediction quality assessment.

After D-04/D-05: imports metric primitives from football_core,
retains WC-specific evaluate_all_matches() and backtest_tournament().
"""

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from src.elo import apply_elo_update, expected_score

logger = logging.getLogger(__name__)

from football_core.evaluation import (
    brier_score,
    log_loss,
    compute_metrics,
    calibration_curve,
    expected_calibration_error,
)


def evaluate_all_matches(
    teams: dict[str, dict],
    played: dict[str, dict],
    played_groups: dict[str, dict],
    signal_name: str | None = None,
    history: list[dict] | None = None,
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
        history: Prediction history entries. Required for signal_name=None and non-elo signals.
            Not used for signal_name="elo" (which replays from played/played_groups).

    Returns:
        Report dict with metrics, calibration, and model info.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── Case: signal_name is None (D-11 default — all available signals) ──
    if signal_name is None:
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
                "n_history_entries": 0,
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
            "n_history_entries": len(history_entries),
        }
        # Caller is responsible for persisting history_entries if desired
        return report

    # ── Case: Other signal_name (market_odds, catboost, blended) ──
    # Read from prediction_history compound entries (caller provides via history param)
    if not history:
        return {
            "model": signal_name, "phase": "13",
            "generated_at": now_iso, "n_matches": 0,
            "metrics": {"brier": 0.0, "log_loss": 0.0, "accuracy": 0.0, "n": 0},
            "calibration": {"bins": [], "ece": 0.0},
            "n_history_entries": 0,
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
        "n_history_entries": len(history),
    }


def backtest_tournament(
    tournament_matches: list[dict],
    teams: dict[str, dict],
    tournament_name: str = "",
) -> dict:
    """Replay a historical tournament through the Elo pipeline.

    Takes a list of historical match dicts (with team_a, team_b, actual),
    replays them chronologically through expected_score() and apply_elo_update(),
    computes per-signal metrics and a winner prediction.

    Args:
        tournament_matches: List of dicts with team_a, team_b, actual, signals.elo.
        teams: Team data dict (deep-copied for replay — original unchanged).
        tournament_name: Label for the report (e.g., "2018").

    Returns:
        Per-tournament report dict with keys:
        tournament, n_matches, per_signal, winner_prediction, signal_ranking,
        available_signals, n_signals.
    """
    # Pitfall 6: deep-copy teams before replay
    replay_teams = copy.deepcopy(teams)

    # Sort matches chronologically (they should already be, but guard)
    sorted_matches = sorted(
        tournament_matches,
        key=lambda m: (m.get("match_id", ""), m.get("team_a", "")),
    )

    if not sorted_matches or not teams:
        return {
            "tournament": tournament_name,
            "n_matches": 0,
            "per_signal": {},
            "winner_prediction": {"predicted": None, "actual": None, "correct": False},
            "signal_ranking": [],
            "available_signals": [],
            "n_signals": 0,
        }

    # Determine available signals (only elo for now, D-12 constraint)
    all_signals: set[str] = set()
    for m in sorted_matches:
        sigs = m.get("signals", {})
        if isinstance(sigs, dict):
            all_signals.update(k for k in sigs if sigs[k].get("available", False))

    # ── Elo replay ──
    elo_predictions: list[float] = []
    actuals: list[float] = []

    for m in sorted_matches:
        t_a, t_b = m["team_a"], m["team_b"]
        if t_a not in replay_teams or t_b not in replay_teams:
            continue
        # Compute expected score before updating Elo
        p_a = expected_score(replay_teams[t_a]["elo"], replay_teams[t_b]["elo"])
        actual_a = m.get("actual")
        if actual_a is None:
            continue
        elo_predictions.append(p_a)
        actuals.append(actual_a)
        # Apply Elo update for next match
        try:
            apply_elo_update(m, replay_teams)
        except Exception:
            pass

    # ── Compute metrics per signal ──
    per_signal: dict[str, dict] = {}
    signal_ranking_entries: list[tuple[str, float]] = []

    if elo_predictions and "elo" in all_signals:
        metrics = compute_metrics(elo_predictions, actuals)
        cal = calibration_curve(elo_predictions, actuals)
        per_signal["elo"] = {
            "brier": round(metrics["brier"], 6),
            "log_loss": round(metrics["log_loss"], 6),
            "ece": round(cal["ece"], 6),
            "n": metrics["n"],
        }
        signal_ranking_entries.append(("elo", metrics["brier"]))

    # ── Winner prediction: highest initial Elo at tournament start ──
    winner_prediction = {"predicted": None, "actual": None, "correct": False}
    if teams:
        # Find team with highest Elo among those participating in tournament
        participating_teams: set[str] = set()
        for m in sorted_matches:
            if m.get("team_a") in teams:
                participating_teams.add(m["team_a"])
            if m.get("team_b") in teams:
                participating_teams.add(m["team_b"])
        if participating_teams:
            predicted_winner = max(
                participating_teams,
                key=lambda name: teams[name]["elo"],
            )
            # Actual winner = last match's winner (tournament final)
            last_match = sorted_matches[-1]
            actual_winner = last_match.get("winner")
            winner_prediction = {
                "predicted": predicted_winner,
                "actual": actual_winner,
                "correct": (
                    predicted_winner == actual_winner
                    if actual_winner is not None
                    else False
                ),
            }

    # ── Signal ranking (sorted by Brier ascending) ──
    signal_ranking_entries.sort(key=lambda x: x[1])
    signal_ranking = [s for s, _ in signal_ranking_entries]

    # Architecture Q3: n_signals < 2 → omit blended
    available_signals = list(all_signals)
    n_signals = len(available_signals)

    return {
        "tournament": tournament_name,
        "n_matches": len(elo_predictions),
        "per_signal": per_signal,
        "winner_prediction": winner_prediction,
        "signal_ranking": signal_ranking,
        "available_signals": available_signals,
        "n_signals": n_signals,
    }


# ──────────────────────────────────────────────
# Functions extracted from web.wc_app (Phase 2)
# ──────────────────────────────────────────────


def compute_signal_stats(data_dir: Path | None = None) -> dict:
    """Signal statistics from on-disk caches — no ledger dependency."""
    from src.state import load_signal_cache

    if data_dir is None:
        from src import constants as _c

        data_dir = _c.DATA_DIR

    cache_files: list[tuple[str, str]] = [
        ("odds_cache.json", "market_odds"),
        ("catboost_cache.json", "catboost"),
        ("form_cache.json", "form"),
        ("lineup_cache.json", "lineup_strength"),
        ("defensive_cache.json", "defensive_quality"),
        ("manager_effect_cache.json", "manager_effect"),
        ("availability_cache.json", "availability"),
        ("elo_odds_cache.json", "elo_odds"),
        ("team_synergy_cache.json", "team_synergy"),
        ("rolling_form_cache.json", "rolling_form"),
        ("squad_value_cache.json", "squad_value"),
        ("rest_days_cache.json", "rest_days"),
    ]
    signal_data: dict[str, dict] = {}
    n_total = 0
    for fname, sname in cache_files:
        cache = load_signal_cache(fname, data_dir)
        matches = (cache or {}).get("matches", {})
        if not matches:
            continue
        n_total += len(matches)
        probs = []
        avail = 0
        for mid, entry in matches.items():
            if entry.get("available", False):
                avail += 1
            prob = entry.get("probability")
            if prob is not None:
                probs.append(prob)
        signal_data[sname] = {
            "n_matches": len(matches),
            "available": avail,
            "available_pct": round(avail / len(matches) * 100, 1) if matches else 0,
            "avg_probability": round(sum(probs) / len(probs), 4) if probs else 0,
            "min_probability": round(min(probs), 4) if probs else 0,
            "max_probability": round(max(probs), 4) if probs else 0,
        }
    return {"signals": signal_data, "n_total": n_total}


def compute_signal_detail(
    name: str,
    data_dir: Path | None = None,
    cache_eval: dict | None = None,
) -> dict:
    """Detailed per-signal report including match-by-match ledger breakdown."""
    if data_dir is None:
        from src import constants as _c

        data_dir = _c.DATA_DIR
    if cache_eval is None:
        cache_eval = {}

    ledger = json.loads((data_dir / "predictions_ledger.json").read_text(encoding="utf-8"))
    played = json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
    played_groups_raw = (data_dir / "played_groups.json").read_text(encoding="utf-8")
    played_groups = json.loads(played_groups_raw) if played_groups_raw.strip() else {}

    matches = []
    eval_matches = 0
    correct = 0
    brier_sum = 0.0
    for mid, signals in ledger.items():
        if name not in signals:
            continue
        sv = signals[name]
        match_data = {
            "match_id": mid,
            "probability": sv.get("probability"),
            "available": sv.get("available", False),
            "reason": sv.get("reason"),
        }
        if mid in played:
            m = played[mid]
            match_data["team_a"] = m.get("team_a", "")
            match_data["team_b"] = m.get("team_b", "")
            match_data["result"] = m.get("winner")
        elif mid in played_groups:
            m = played_groups[mid]
            match_data["team_a"] = m.get("team_a", "")
            match_data["team_b"] = m.get("team_b", "")
            match_data["result"] = m.get("winner")
        else:
            match_data["team_a"] = sv.get("team_a", "")
            match_data["team_b"] = sv.get("team_b", "")
        matches.append(match_data)
        prob = sv.get("probability")
        result = match_data.get("result")
        if prob is not None and result is not None:
            eval_matches += 1
            actual = 1.0 if result == match_data.get("team_a") else (0.0 if result == match_data.get("team_b") else 0.5)
            brier_sum += (prob - actual) ** 2
            if (actual == 1.0 and prob > 0.5) or (actual == 0.0 and prob < 0.5) or (actual == 0.5):
                correct += 1

    ev = cache_eval
    sig_eval = ev.get(name, {})
    return {
        "name": name,
        "n_matches": len(matches),
        "n_with_results": eval_matches,
        "live_eval": {
            "brier": round(brier_sum / eval_matches, 4) if eval_matches else None,
            "accuracy": round(correct / eval_matches, 4) if eval_matches else None,
            "n": eval_matches,
        },
        "cache_eval": sig_eval if sig_eval.get("n_matches", 0) > 0 else None,
        "matches": matches,
    }


def compute_signal_briers_from_predictions(
    engine_predictions: list,
    all_matches: list[dict],
    played: dict,
    played_groups: dict,
) -> dict[str, dict]:
    """Compute per-signal Brier/log-loss/accuracy from engine predictions.

    Uses zip() to associate each BlendedPrediction with its match fixture
    (since BlendedPrediction has no match_id field).

    Returns: {signal_name: {"brier": ..., "log_loss": ..., "accuracy": ..., "n": ...}}
    """
    played_all = dict(played)
    if played_groups:
        played_all.update(played_groups)

    accum: dict[str, list[tuple[float, float]]] = {}

    for bp, match in zip(engine_predictions, all_matches):
        mid = match.get("match_id", "")
        if not mid or mid not in played_all:
            continue
        m = played_all[mid]
        t_a, t_b = m.get("team_a", ""), m.get("team_b", "")
        winner = m.get("winner")
        if winner == t_a:
            actual = 1.0
        elif winner == t_b:
            actual = 0.0
        elif winner is None:
            actual = 0.5
        else:
            continue
        for sig_name, sd in (bp.signal_breakdown or {}).items():
            prob = sd.get("home", 0.33)
            accum.setdefault(sig_name, []).append((prob, actual))

    from football_core.evaluation import compute_metrics

    result = {}
    for sig_name, pairs in sorted(accum.items()):
        preds = [p for p, _ in pairs]
        actuals = [a for _, a in pairs]
        metrics = compute_metrics(preds, actuals)
        result[sig_name] = {
            "brier": round(metrics["brier"], 6),
            "log_loss": round(metrics["log_loss"], 6),
            "accuracy": round(metrics["accuracy"], 6),
            "n": metrics["n"],
        }
    return result


def compute_signal_eval(
    teams: dict,
    played: dict,
    played_groups: dict,
    engine_predictions: list,
    all_matches: list[dict],
) -> dict:
    """Evaluate signals from engine predictions — no ledger dependency."""
    elo_report = evaluate_all_matches(teams, played, played_groups, signal_name="elo")
    signal_briers = compute_signal_briers_from_predictions(
        engine_predictions, all_matches, played, played_groups,
    )
    all_report = evaluate_all_matches(
        teams,
        played,
        played_groups,
        signal_name=None,
        history=_build_eval_history_from_predictions(
            engine_predictions, all_matches, played, played_groups,
        ),
    )
    return {"elo": elo_report, "all_signals": all_report}


def _build_eval_history_from_predictions(
    predictions: list,
    all_matches: list[dict],
    played: dict,
    played_groups: dict,
) -> list[dict]:
    """Build eval history from BlendedPrediction list + match fixtures.

    Uses zip() since BlendedPrediction has no match_id field.
    """
    played_all = dict(played)
    if played_groups:
        played_all.update(played_groups)
    played_mids = set(played_all.keys())
    history = []
    for bp, match in zip(predictions, all_matches):
        mid = match.get("match_id", "")
        if not mid or mid not in played_mids:
            continue
        m = played_all[mid]
        t_a, t_b = m.get("team_a", ""), m.get("team_b", "")
        winner = m.get("winner")
        if winner == t_a:
            actual = 1.0
        elif winner == t_b:
            actual = 0.0
        elif winner is None:
            actual = 0.5
        else:
            continue
        sigs = {}
        for sk, sd in (bp.signal_breakdown or {}).items():
            prob = sd.get("home", 0.33)
            sigs[sk] = {"probability": prob, "available": True}
        if sigs:
            history.append({"match_id": mid, "actual": actual, "signals": sigs})
    return history


def compute_blend_info(
    data_dir: Path | None = None,
    eval_data: dict | None = None,
    gov_data: dict | None = None,
) -> dict:
    """Blend info from evaluation data + backtest — no cache dependency."""
    if data_dir is None:
        from src import constants as _c

        data_dir = _c.DATA_DIR
    if eval_data is None:
        eval_data = {}
    if gov_data is None:
        gov_data = {}

    backtest_path = data_dir / "eval_backtest_report.json"
    backtest = json.loads(backtest_path.read_text(encoding="utf-8")) if backtest_path.exists() else {}

    available_signals = sorted(
        k for k in eval_data if k != "elo" and eval_data[k].get("n_matches", 0) > 0
    )
    n_available = len(available_signals)
    per_signal = backtest.get("per_signal", {})
    briers = {}
    for sk, sv in per_signal.items():
        b = sv.get("brier")
        if b is not None:
            briers[sk] = b
    for sk in available_signals:
        if sk not in briers:
            briers[sk] = 0.25
    total_inv = sum(1.0 / max(b, 0.01) for b in briers.values()) if briers else 1
    weights = (
        {sk: round((1.0 / max(b, 0.01)) / total_inv, 4) for sk, b in briers.items()}
        if total_inv
        else {}
    )
    n_matches = gov_data.get("n_matches", 0)
    return {
        "n_signals_available": n_available,
        "available_signals": available_signals,
        "blend_weights": weights,
        "backtest_briers": {sk: round(b, 4) for sk, b in briers.items()},
        "calibration_status": "cold_start" if n_matches < 30 else "calibrated",
        "n_matches_for_calibration": n_matches,
        "threshold": 30,
    }
