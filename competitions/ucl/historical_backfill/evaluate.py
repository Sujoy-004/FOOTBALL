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
with the season's own pre-match Elo snapshot — no future data leaks.

Output: ``data/historical/evaluation/eval_results.json``
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np

from football_core.blender import EnsembleEngine, compute_log_loss_weights
from football_core.evaluation import multi_class_brier, multi_class_ece, multi_class_log_loss
from football_core.signals.market_odds import MarketOddsSignal
from football_core.signals.refined_elo import RefinedEloSignal
from football_core.signals.rest_days import RestDaysSignal
from football_core.signals.rolling_form import RollingFormSignal

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


# ─────────────────────────── loaders & helpers ───────────────────────────


def load_season(season: str) -> tuple[list[dict], dict[str, float]]:
    matches = load_replay_matches(os.path.join(HISTORICAL_DIR, season, "matches.json"))
    with open(os.path.join(HISTORICAL_DIR, season, "elo_ratings.json")) as f:
        elo: dict[str, float] = json.load(f)
    return matches, elo


def renormalize(weights: dict[str, float], subset: list[str]) -> dict[str, float]:
    active = {s: w for s, w in weights.items() if s in subset and w > 0}
    total = sum(active.values())
    if total <= 0:
        return {}
    return {s: w / total for s, w in active.items()}


def _signal_output(name: str, match: dict, ctx, season_matches: list[dict]):
    if name == "market_odds":
        return MarketOddsSignal().predict(match, ctx)
    if name == "refined_elo":
        return RefinedEloSignal().predict(match, ctx)
    if name == "rest_days":
        return RestDaysSignal().predict(match, ctx)
    if name == "rolling_form":
        return RollingFormSignal(
            result_provider=ReplayResultProvider(order_matches(season_matches))
        ).predict(match, ctx)
    raise ValueError(name)


def build_engine(signals: list[str], weights: dict[str, float], provider) -> EnsembleEngine:
    registry: dict[str, object] = {
        "market_odds": MarketOddsSignal(),
        "refined_elo": RefinedEloSignal(),
        "rest_days": RestDaysSignal(),
    }
    if "rolling_form" in signals:
        registry["rolling_form"] = RollingFormSignal(result_provider=provider)
    ins = [registry[n] for n in signals]
    return EnsembleEngine(signals=ins, weights=renormalize(weights, signals))


def completed_indices(matches: list[dict]) -> tuple[list[list[float]], list[int], list[dict]]:
    """Return (placeholder-probs, actuals, completed_matches) where probs are 1/3."""
    actuals: list[int] = []
    completed: list[dict] = []
    for m in matches:
        idx = outcome_index(m)
        if idx is None:
            continue
        actuals.append(idx)
        completed.append(m)
    return [[1 / 3, 1 / 3, 1 / 3]] * len(actuals), actuals, completed


def metrics_from(probs: list[list[float]], actuals: list[int]) -> dict:
    if not actuals:
        return {"n": 0}
    confidences = [max(p) for p in probs]
    preds = [int(np.argmax(p)) for p in probs]
    correct = [1.0 if pc == a else 0.0 for pc, a in zip(preds, actuals)]
    return {
        "n": len(actuals),
        "log_loss": round(multi_class_log_loss(probs, actuals), 6),
        "brier": round(multi_class_brier(probs, actuals), 6),
        "ece": round(multi_class_ece(probs, actuals), 6),
        "mean_confidence": round(sum(confidences) / len(confidences), 6),
        "accuracy": round(sum(correct) / len(correct), 6),
    }


def uniform_metrics(matches: list[dict]) -> dict | None:
    probs, actuals, _ = completed_indices(matches)
    if not actuals:
        return None
    return {"uniform_log_loss": metrics_from(probs, actuals)["log_loss"],
            "uniform_brier": metrics_from(probs, actuals)["brier"],
            "n": len(actuals)}


def eval_config(
    matches: list[dict], elo: dict[str, float], engine: EnsembleEngine
) -> dict | None:
    probs: list[list[float]] = []
    actuals: list[int] = []
    for m in matches:
        idx = outcome_index(m)
        if idx is None:
            continue
        ctx = build_context_for_match(m, matches, elo_ratings=elo)
        bp = engine.evaluate(m, ctx)
        probs.append([bp.home_prob, bp.draw_prob, bp.away_prob])
        actuals.append(idx)
    if not actuals:
        return None
    return metrics_from(probs, actuals)


def signal_metrics(
    matches: list[dict], elo: dict[str, float], name: str
) -> dict | None:
    probs: list[list[float]] = []
    actuals: list[int] = []
    for m in matches:
        idx = outcome_index(m)
        if idx is None:
            continue
        ctx = build_context_for_match(m, matches, elo_ratings=elo)
        out = _signal_output(name, m, ctx, matches)
        probs.append([out.home_prob, out.draw_prob, out.away_prob])
        actuals.append(idx)
    if not actuals:
        return None
    return metrics_from(probs, actuals)


def freq_metrics_on(freqs: dict[str, float], matches: list[dict]) -> dict | None:
    probs, actuals, _ = completed_indices(matches)
    if not actuals:
        return None
    probs = [[freqs["home"], freqs["draw"], freqs["away"]]] * len(actuals)
    return metrics_from(probs, actuals)


def has_odds(m: dict) -> bool:
    return all(m.get(k) is not None for k in ("odds_home", "odds_draw", "odds_away"))


def first_date(matches: list[dict]) -> str:
    return min((m.get("event_date") or "") for m in matches)


# ───────────────────────────────── main ─────────────────────────────────


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    season_data = {s: load_season(s) for s in SEASONS}
    prod_renorm = renormalize(PROD_WEIGHTS_RAW, SIGNAL_ORDER)

    results: dict = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": "competitions/ucl/data/historical (2019/20-2023/24)",
            "weights": {
                "production_raw": PROD_WEIGHTS_RAW,
                "production_renormalized_over_historical": prod_renorm,
                "note": "squad_value has no historical data; production weights "
                "renormalized over market_odds/refined_elo/rolling_form/rest_days",
            },
            "method": "replay: every match predicted with a prior-only context "
            "and its own season's pre-match Elo snapshot; no future-data leakage",
            "ece_note": "ece = football_core.evaluation.multi_class_ece "
            "(confidence-vs-accuracy ECE; the production implementation)",
        },
        "per_season": {},
        "overall": {},
        "ablation": {},
        "weights_learned": {},
    }

    # ─────────────────────────── per season ───────────────────────────
    for s in SEASONS:
        matches, elo = season_data[s]
        provider = ReplayResultProvider(order_matches(matches))
        odds_matches = [m for m in matches if has_odds(m)]
        elo_matches = [m for m in matches if m.get("team_a") in elo and m.get("team_b") in elo]
        ref_engine = build_engine(SIGNAL_ORDER, prod_renorm, provider)

        full_all = eval_config(matches, elo, ref_engine)
        full_odds = eval_config(odds_matches, elo, ref_engine) if odds_matches else None
        full_covered = eval_config(elo_matches, elo, ref_engine) if elo_matches else None

        um = uniform_metrics(matches)
        elo_only = signal_metrics(matches, elo, "refined_elo")
        elo_only_covered = signal_metrics(elo_matches, elo, "refined_elo") if elo_matches else None
        market_only = signal_metrics(odds_matches, elo, "market_odds") if odds_matches else None

        # within-season chronological 70/30 window → freq baseline OOS
        ord_m = order_matches(matches)
        split_at = max(1, int(round(len(ord_m) * 0.7)))
        fit_m, oos_m = ord_m[:split_at], ord_m[split_at:]
        freq = frequency_baseline(fit_m)
        window = {
            "n_fit": len(fit_m),
            "n_eval": len(oos_m),
            "freq_dist": freq,
            "ensemble": eval_config(oos_m, elo, ref_engine),
            "elo_only": signal_metrics(oos_m, elo, "refined_elo"),
            "freq": freq_metrics_on(freq, oos_m),
        }

        results["per_season"][s] = {
            "n": len(matches),
            "odds_n": len(odds_matches),
            "elo_covered_n": len(elo_matches),
            "all": {
                "ensemble": full_all,
                "uniform": um,
                "elo_only": elo_only,
            },
            "elo_covered": {
                "n": len(elo_matches),
                "ensemble": full_covered,
                "elo_only": elo_only_covered,
            },
            "odds": (
                {"n": len(odds_matches), "ensemble": full_odds, "market_odds_only": market_only}
                if odds_matches else None
            ),
            "window": window,
        }

    # ─────────────────────────── pooled overall ───────────────────────────
    # per-season elo maps are used per match (season-scoped aggregation)
    def run_pool(match_filter):
        """Return per-config metrics over the pooled matches matching ``match_filter``."""
        all_probs: list[list[float]] = []
        all_actuals: list[int] = []
        elo_probs: list[list[float]] = []
        mkt_probs: list[list[float]] = [[1 / 3, 1 / 3, 1 / 3]]
        ens_odds_probs: list[list[float]] = []
        mkt_odds_probs: list[list[float]] = []
        odds_actuals: list[int] = []
        for s in SEASONS:
            matches, elo = season_data[s]
            eng = build_engine(SIGNAL_ORDER, prod_renorm, ReplayResultProvider(order_matches(matches)))
            for m in matches:
                if not match_filter(m, s, elo):
                    continue
                idx = outcome_index(m)
                if idx is None:
                    continue
                ctx = build_context_for_match(m, matches, elo_ratings=elo)
                bp = eng.evaluate(m, ctx)
                all_probs.append([bp.home_prob, bp.draw_prob, bp.away_prob])
                all_actuals.append(idx)
                eo = RefinedEloSignal().predict(m, ctx)
                elo_probs.append([eo.home_prob, eo.draw_prob, eo.away_prob])
                if has_odds(m):
                    mo = MarketOddsSignal().predict(m, ctx)
                    ens_odds_probs.append([bp.home_prob, bp.draw_prob, bp.away_prob])
                    mkt_odds_probs.append([mo.home_prob, mo.draw_prob, mo.away_prob])
                    odds_actuals.append(idx)
        return {
            "all_n": len(all_actuals),
            "ensemble": metrics_from(all_probs, all_actuals),
            "elo_only": metrics_from(elo_probs, all_actuals),
            "uniform": metrics_from([[1 / 3, 1 / 3, 1 / 3]] * len(all_actuals), all_actuals),
            "odds_n": len(odds_actuals),
            "odds_ensemble": metrics_from(ens_odds_probs, odds_actuals),
            "odds_market_only": metrics_from(mkt_odds_probs, odds_actuals),
            "odds_uniform": metrics_from([[1 / 3, 1 / 3, 1 / 3]] * len(odds_actuals), odds_actuals),
        }

    overall = {
        "all": run_pool(lambda m, s, elo: True),
        "elo_covered": run_pool(lambda m, s, elo: m.get("team_a") in elo and m.get("team_b") in elo),
        "odds": run_pool(lambda m, s, elo: has_odds(m)),
    }
    overall["n"] = overall["all"]["all_n"]
    overall["odds_n"] = overall["all"]["odds_n"]

    # overall chronological 70/30 window → freq OOS (freq uses pool, not season-split)
    ord_pool = order_matches([m for s in SEASONS for m in season_data[s][0]])
    psplit = max(1, int(round(len(ord_pool) * 0.7)))
    pfit, poos = ord_pool[:psplit], ord_pool[psplit:]
    pfreq = frequency_baseline(pfit)
    win = run_pool(lambda m, s, elo: id(m) in {id(x) for x in poos})
    overall["window"] = {
        "n_fit": len(pfit),
        "n_eval": len(poos),
        "freq_dist": pfreq,
        "ensemble": win["ensemble"],
        "elo_only": win["elo_only"],
        "uniform": win["uniform"],
        "freq": freq_metrics_on(pfreq, poos),
    }
    results["overall"] = overall

    # ─────────────────────── leave-one-signal-out ───────────────────────
    configs = {
        "full": SIGNAL_ORDER,
        "without_elo": [x for x in SIGNAL_ORDER if x != "refined_elo"],
        "without_odds": [x for x in SIGNAL_ORDER if x != "market_odds"],
        "without_form": [x for x in SIGNAL_ORDER if x != "rolling_form"],
        "without_rest": [x for x in SIGNAL_ORDER if x != "rest_days"],
    }
    for s in SEASONS:
        matches, elo = season_data[s]
        provider = ReplayResultProvider(order_matches(matches))
        row: dict = {"n": len(matches)}
        for cfg, sigs in configs.items():
            eng = build_engine(sigs, prod_renorm, provider)
            row[cfg] = eval_config(matches, elo, eng)
        results["ablation"][s] = row

    pooled_abl: dict = {"n": len([m for s in SEASONS for m in season_data[s][0]])}
    for cfg, sigs in configs.items():
        probs_, actuals_ = [], []
        for s in SEASONS:
            matches, elo = season_data[s]
            eng = build_engine(sigs, prod_renorm, ReplayResultProvider(order_matches(matches)))
            for m in matches:
                idx = outcome_index(m)
                if idx is None:
                    continue
                ctx = build_context_for_match(m, matches, elo_ratings=elo)
                bp = eng.evaluate(m, ctx)
                probs_.append([bp.home_prob, bp.draw_prob, bp.away_prob])
                actuals_.append(idx)
        if actuals_:
            pooled_abl[cfg] = metrics_from(probs_, actuals_)
    results["ablation"]["overall"] = pooled_abl

    # ─────────────────── learned weights by training window ───────────────────
    learned: dict = {}
    for i, target in enumerate(SEASONS[1:], start=1):
        prior: list[tuple[list[dict], dict[str, float]]] = []
        for prev in SEASONS[:i]:
            pm, pe = season_data[prev]
            prior.append((pm, pe))

        # per-signal log-loss over the strictly-prior training pool
        sig_probs = {n: {"probs": [], "actuals": []} for n in SIGNAL_ORDER}
        for pm, pe in prior:
            eng_single = None
            for m in pm:
                idx = outcome_index(m)
                if idx is None:
                    continue
                ctx = build_context_for_match(m, pm, elo_ratings=pe)
                for n in SIGNAL_ORDER:
                    out = _signal_output(n, m, ctx, pm)
                    sig_probs[n]["probs"].append([out.home_prob, out.draw_prob, out.away_prob])
                    sig_probs[n]["actuals"].append(idx)
        sig_ll: dict[str, float] = {}
        for n in SIGNAL_ORDER:
            data = sig_probs[n]
            if len(data["probs"]) >= 20:
                sig_ll[n] = round(multi_class_log_loss(data["probs"], data["actuals"]), 6)
        wts = compute_log_loss_weights(sig_ll) if sig_ll else {}

        tmatches, telo = season_data[target]
        eng = build_engine(SIGNAL_ORDER, wts, ReplayResultProvider(order_matches(tmatches)))
        ev = eval_config(tmatches, telo, eng)
        ev["weights_source"] = f"train:{'+'.join(SEASONS[:i])} -> eval:{target}"
        learned[target] = {
            "train_pool_n": sum(len(p) for p, _ in prior),
            "signals_used": list(sig_ll.keys()),
            "per_signal_train_log_loss": sig_ll,
            "weights": wts,
            "evaluation": ev,
        }

    # stability across windows + vs production
    stability: dict = {"per_signal_min_max": {}, "window_to_window_shift": {}, "vs_production": {}}
    for n in SIGNAL_ORDER:
        vals = [learned[s]["weights"].get(n, 0.0) for s in SEASONS[1:]]
        if vals:
            stability["per_signal_min_max"][n] = {
                "min": min(vals), "max": max(vals),
                "spread": round(max(vals) - min(vals), 6),
            }
    prev_w = None
    for s in SEASONS[1:]:
        cur_w = learned[s]["weights"]
        if prev_w is not None:
            allk = sorted(set(prev_w) | set(cur_w))
            stability["window_to_window_shift"][s] = {
                k: round(cur_w.get(k, 0.0) - prev_w.get(k, 0.0), 6) for k in allk
            }
        prev_w = cur_w
    # correlation of final-window weights with production renormalized
    final_w = learned[SEASONS[-1]]["weights"]
    keys = [k for k in SIGNAL_ORDER if k in final_w or k in prod_renorm]
    if len(keys) >= 2:
        a = [final_w.get(k, 0.0) for k in keys]
        b = [prod_renorm.get(k, 0.0) for k in keys]
        mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
        num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        den = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** 0.5
        stability["vs_production"]["pearson"] = round(num / den, 4) if den else None
    results["weights_learned"]["stability"] = stability
    results["weights_learned"]["per_season"] = learned

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()