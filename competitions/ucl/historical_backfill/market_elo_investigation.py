"""Market + Elo baseline investigation on the historical UCL backfill.

Evaluates six models and a weight-dilution ablation on the SAME
(i.e. identical eligible) match population — the 469 odds-covered matches
across 2020/21-2023/24 (2019/20 has zero odds data):

  1. market_odds_only
  2. elo_only
  3. market_elo (equal 0.5/0.5 weights)
  4. current production ensemble (4 signals, production-renormalized weights)
  5. uniform 1/3
  6. empirical frequency (strictly-prior-season base rates)

plus:

  * ablation tower with EQUAL weights   M+E -> M+E+F -> M+E+R -> M+E+F+R
  * dilution analysis on 2021/22-2023/24 (n=346, where strictly-prior
    learned weights are estimable): market_only, M+E equal, M+E learned,
    4-sig equal, 4-sig learned, 4-sig production — whether the learned /
    production weight split wastes market+elo mass on form/rest.

Constraints honored (READ-ONLY, no production code / signals / weights /
calibration / simulation / UI / datasets touched):

  * every prediction uses ``historical.build_context_for_match`` (prior-only)
    with the season's own pre-match Elo snapshot (no future data),
  * learned weights are inverse-log-loss fits on STRICTLY prior seasons only,
    never on the evaluation season (no weight tuning on the eval set),
  * all models in every directly-compared table run on the identical
    odds-covered match list, so log-loss/Brier/ECE are apples-to-apples,
  * ECE is ``football_core.evaluation.multi_class_ece``,
  * paired (same-resample) percentile bootstrap 95% CIs on pooled
    log-loss, Brier, ECE, and paired delta-LL (seed fixed for
    reproducibility) — the eval framework itself does not provide CIs.

Output: ``data/historical/evaluation/market_elo_results.json``
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np

from football_core.blender import compute_log_loss_weights
from football_core.evaluation import multi_class_log_loss

from competitions.ucl.historical_backfill.evaluate import (
    SEASONS,
    SIGNAL_ORDER,
    PROD_WEIGHTS_RAW,
    HISTORICAL_DIR,
    build_engine,
    has_odds,
    load_season,
    metrics_from,
    renormalize,
    _signal_output,
)
from competitions.ucl.src.historical import (
    ReplayResultProvider,
    build_context_for_match,
    frequency_baseline,
    order_matches,
    outcome_index,
)

OUT_PATH = os.path.join(HISTORICAL_DIR, "evaluation", "market_elo_results.json")

BOOT_SEED = 20260601
N_BOOT = 2000

CORE_MODELS = [
    ("market_only", ["market_odds"], None),
    ("elo_only", ["refined_elo"], None),
    ("me_equal", ["market_odds", "refined_elo"], {"market_odds": 0.5, "refined_elo": 0.5}),
    ("prod_ensemble", SIGNAL_ORDER, None),  # production-renormalized weights
]

EQUAL_ABLATIONS = {
    "me": (["market_odds", "refined_elo"], {"market_odds": 0.5, "refined_elo": 0.5}),
    "me_form": (["market_odds", "refined_elo", "rolling_form"],
                {"market_odds": 1 / 3, "refined_elo": 1 / 3, "rolling_form": 1 / 3}),
    "me_rest": (["market_odds", "refined_elo", "rest_days"],
                {"market_odds": 1 / 3, "refined_elo": 1 / 3, "rest_days": 1 / 3}),
    "me_form_rest": (SIGNAL_ORDER, {"market_odds": 0.25, "refined_elo": 0.25,
                                    "rolling_form": 0.25, "rest_days": 0.25}),
}


def model_probs(matches, elo, signals, weights, *, odds_only: bool = True):
    """(probs, actuals) on completed matches (optionally odds-covered only).

    ``weights=None`` → production-renormalized weights over ``signals``.
    Single-signal lists use the bare signal (no blending needed).
    Market odds falls back to uniform on matches without odds (as-is).
    """
    def eligible(m):
        return idx is not None and (not odds_only or has_odds(m))

    if len(signals) == 1 and weights is None:
        probs, actuals = [], []
        for m in matches:
            idx = outcome_index(m)
            if not eligible(m):
                continue
            ctx = build_context_for_match(m, matches, elo_ratings=elo)
            out = _signal_output(signals[0], m, ctx, matches)
            probs.append([out.home_prob, out.draw_prob, out.away_prob])
            actuals.append(idx)
        return probs, actuals

    eff_w = renormalize(PROD_WEIGHTS_RAW, signals) if weights is None else weights
    eng = build_engine(signals, eff_w, ReplayResultProvider(order_matches(matches)))
    probs, actuals = [], []
    for m in matches:
        idx = outcome_index(m)
        if not eligible(m):
            continue
        ctx = build_context_for_match(m, matches, elo_ratings=elo)
        bp = eng.evaluate(m, ctx)
        probs.append([bp.home_prob, bp.draw_prob, bp.away_prob])
        actuals.append(idx)
    return probs, actuals


def uniform_rows(matches, *, odds_only: bool = True):
    probs, actuals = [], []
    for m in matches:
        idx = outcome_index(m)
        if idx is None:
            continue
        if odds_only and not has_odds(m):
            continue
        probs.append([1 / 3, 1 / 3, 1 / 3])
        actuals.append(idx)
    return probs, actuals


def prior_odds_pool(target: str):
    """Per-signal probs + actuals on strictly-prior odds-covered pool."""
    pool_probs = {n: [] for n in SIGNAL_ORDER}
    actuals: list[int] = []
    for s in SEASONS[:SEASONS.index(target)]:
        matches, elo = load_season(s)
        for m in matches:
            if not has_odds(m):
                continue
            idx = outcome_index(m)
            if idx is None:
                continue
            ctx = build_context_for_match(m, matches, elo_ratings=elo)
            for n in SIGNAL_ORDER:
                out = _signal_output(n, m, ctx, matches)
                pool_probs[n].append([out.home_prob, out.draw_prob, out.away_prob])
            actuals.append(idx)
    return pool_probs, actuals


def learn_weights(target: str, signals: list[str]) -> dict[str, float] | None:
    """Inverse-log-loss weights for ``signals`` on strictly-prior odds pool."""
    pool_probs, actuals = prior_odds_pool(target)
    if not actuals:
        return None
    ll = {n: multi_class_log_loss(pool_probs[n], actuals) for n in signals}
    if len(ll) < len(signals):
        return None
    return compute_log_loss_weights(ll)


def freq_preds(target: str) -> list[float]:
    prior_m = [m for s in SEASONS[:SEASONS.index(target)] for m in load_season(s)[0]]
    d = frequency_baseline(prior_m)
    return [d["home"], d["draw"], d["away"]]


# ─────────────────────────── bootstrap CIs ───────────────────────────


def per_match(probs, actuals) -> dict:
    n = len(actuals)
    ll = np.empty(n)
    br = np.empty(n)
    conf = np.empty(n)
    hit = np.zeros(n, dtype=bool)
    for i, (p, a) in enumerate(zip(probs, actuals)):
        ll[i] = -np.log(max(p[a], 1e-12))
        br[i] = (1 - p[a]) ** 2 + sum(p[j] ** 2 for j in range(3) if j != a)
        conf[i] = max(p)
        hit[i] = int(np.argmax(np.asarray(p))) == a
    return {"n": n, "ll": ll, "brier": br, "conf": conf, "hit": hit}


def ece_from_cache(conf: np.ndarray, hit: np.ndarray, n_bins: int = 10) -> float:
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        mask = ((conf >= lo) & (conf < hi)) | ((b == n_bins - 1) & (conf == 1.0))
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        ece += (cnt / conf.size) * abs(float(conf[mask].mean()) - float(hit[mask].sum() / cnt))
    return round(ece, 6)


def cache_merge(cache: dict, name: str, probs, actuals):
    pm = per_match(probs, actuals)
    if name in cache:
        prev = cache[name]
        cache[name] = {
            "n": prev["n"] + pm["n"],
            "ll": np.concatenate([prev["ll"], pm["ll"]]),
            "brier": np.concatenate([prev["brier"], pm["brier"]]),
            "conf": np.concatenate([prev["conf"], pm["conf"]]),
            "hit": np.concatenate([prev["hit"], pm["hit"]]),
        }
    else:
        cache[name] = pm


def pooled_metrics(c: dict) -> dict:
    return {
        "n": c["n"],
        "log_loss": round(float(c["ll"].mean()), 6),
        "brier": round(float(c["brier"].mean() / 3), 6),
        "ece": ece_from_cache(c["conf"], c["hit"]),
        "mean_confidence": round(float(c["conf"].mean()), 6),
        "accuracy": round(float(c["hit"].mean()), 6),
    }


def bootstrap_cis(cached: dict[str, dict]) -> dict:
    rng = np.random.default_rng(BOOT_SEED)
    n = cached[next(iter(cached))]["n"]
    idx = rng.integers(0, n, size=(N_BOOT, n))

    out: dict = {}
    for name, c in cached.items():
        ll_b = c["ll"][idx].mean(axis=1)
        br_b = c["brier"][idx].mean(axis=1) / 3
        ece_b = np.array([ece_from_cache(c["conf"][row], c["hit"][row]) for row in idx])
        out[name] = {
            "log_loss": {"2.5": round(float(np.percentile(ll_b, 2.5)), 6),
                         "97.5": round(float(np.percentile(ll_b, 97.5)), 6)},
            "brier": {"2.5": round(float(np.percentile(br_b, 2.5)), 6),
                      "97.5": round(float(np.percentile(br_b, 97.5)), 6)},
            "ece": {"2.5": round(float(np.percentile(ece_b, 2.5)), 6),
                    "97.5": round(float(np.percentile(ece_b, 97.5)), 6)},
        }

    pairs = [
        ("prod_ensemble", "me_equal"), ("prod_ensemble", "market_only"),
        ("me_equal", "market_only"), ("me_equal", "elo_only"),
        ("me_equal", "me_learned"), ("me_learned", "market_only"),
        ("me", "me_form"), ("me", "me_rest"),
        ("me", "me_form_rest"),
        ("me_form", "me_form_rest"), ("me_rest", "me_form_rest"),
        ("prod_ensemble", "ens_equal"), ("prod_ensemble", "ens_learned"),
        ("ens_equal", "me_equal"), ("ens_learned", "me_learned"),
    ]
    delta: dict = {}
    for a, b in pairs:
        if a not in cached or b not in cached:
            continue
        d = cached[a]["ll"][idx].mean(axis=1) - cached[b]["ll"][idx].mean(axis=1)
        delta[f"{a}_vs_{b}"] = {
            "delta_ll": round(float(d.mean()), 6),
            "2.5": round(float(np.percentile(d, 2.5)), 6),
            "97.5": round(float(np.percentile(d, 97.5)), 6),
        }
    out["_delta_ll"] = delta
    return out


# ───────────────────────────────── main ─────────────────────────────────


def main() -> None:
    season_data = {s: load_season(s) for s in SEASONS}

    out: dict = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": "competitions/ucl/data/historical (2019/20-2023/24)",
            "population": "odds-covered completed matches; 2019/20 has zero odds "
                          "matches and is absent from the population",
            "method": "replay with historical.build_context_for_match (prior-only) "
                      "and season pre-match Elo snapshots; no future data leakage",
            "weighting": "directly-compared ablations use EQUAL weights; learned "
                          "weights are inverse-log-loss fits on strictly-prior "
                          "odds-covered seasons only (never the eval season); "
                          "production weights used as-is (renormalized over the 4 "
                          "historical signals)",
            "ece_note": "ece = football_core.evaluation.multi_class_ece (production)",
            "brier_note": "brier = football_core multi_class_brier convention "
                          "(mean of per-match squared-error vector length, 1/3 scale)",
            "ci_note": "95% percentile bootstrap, paired over identical resamples, "
                      "n_boot=2000, seed=20260601",
        },
        "population": {},
        "freq_by_season": {},
        "per_season": {},
        "pooled": {},
        "dilution": {},
        "learned_weights": {},
    }

    odds_n = {s: sum(1 for m in season_data[s][0] if has_odds(m)) for s in SEASONS}
    out["population"] = {
        "odds_by_season": odds_n,
        "odds_total": sum(odds_n.values()),
        "seasons_with_odds": [s for s in SEASONS if odds_n[s] > 0],
    }

    for s in SEASONS:
        out["freq_by_season"][s] = freq_preds(s)

    cached_pooled: dict[str, dict] = {}
    for s in SEASONS:
        matches, elo = season_data[s]
        row: dict[str, dict | int | None] = {}
        for name, sigs, wts in CORE_MODELS:
            probs, actuals = model_probs(matches, elo, sigs, wts)
            row[name] = metrics_from(probs, actuals) if actuals else None
        for cut, (sigs, wts) in EQUAL_ABLATIONS.items():
            probs, actuals = model_probs(matches, elo, sigs, wts)
            row[cut] = metrics_from(probs, actuals) if actuals else None
        probs_u, actuals_u = uniform_rows(matches)
        row["uniform"] = metrics_from(probs_u, actuals_u) if actuals_u else None
        freq = out["freq_by_season"][s]
        row["freq_prior_season"] = metrics_from([freq] * len(actuals_u), actuals_u) if actuals_u else None
        row["n_odds"] = len(actuals_u)
        out["per_season"][s] = row

        if not actuals_u:
            continue
        for name, sigs, wts in CORE_MODELS:
            probs, actuals = model_probs(matches, elo, sigs, wts)
            cache_merge(cached_pooled, name, probs, actuals)
        for cut, (sigs, wts) in EQUAL_ABLATIONS.items():
            probs, actuals = model_probs(matches, elo, sigs, wts)
            cache_merge(cached_pooled, cut, probs, actuals)
        cache_merge(cached_pooled, "uniform", probs_u, actuals_u)
        cache_merge(cached_pooled, "freq_prior_season", [freq] * len(actuals_u), actuals_u)

    out["pooled"]["n"] = cached_pooled["market_only"]["n"]
    out["pooled"]["models"] = {name: pooled_metrics(c) for name, c in cached_pooled.items()}
    out["pooled"]["ci"] = bootstrap_cis(cached_pooled)

    # ─────── secondary: full all-completed population (619) ───────
    # Grounds the architecture recommendation for matches where market odds
    # are absent (market signal falls back to uniform on those 150 matches).
    cached_all: dict[str, dict] = {}
    for s in SEASONS:
        matches, elo = season_data[s]
        for name, sigs, wts in [("prod_ensemble", SIGNAL_ORDER, None),
                                ("me_equal", ["market_odds", "refined_elo"],
                                 {"market_odds": 0.5, "refined_elo": 0.5}),
                                ("elo_only", ["refined_elo"], None)]:
            probs, actuals = model_probs(matches, elo, sigs, wts, odds_only=False)
            cache_merge(cached_all, name, probs, actuals)
        probs_u, actuals_u = uniform_rows(matches, odds_only=False)
        cache_merge(cached_all, "uniform", probs_u, actuals_u)
        freq = out["freq_by_season"][s]
        cache_merge(cached_all, "freq_prior_season", [freq] * len(actuals_u), actuals_u)
    out["all_pooled"] = {
        "n": cached_all["uniform"]["n"],
        "models": {name: pooled_metrics(c) for name, c in cached_all.items()},
        "ci": bootstrap_cis(cached_all),
    }

    # ─────────────────── dilution analysis (2021/22-2023/24) ───────────────────
    dil_seasons = SEASONS[2:]
    out["dilution"]["seasons"] = dil_seasons
    out["dilution"]["n"] = sum(odds_n[s] for s in dil_seasons)
    dil_caches: dict[str, dict] = {}
    for t in dil_seasons:
        matches, elo = season_data[t]
        me_w = learn_weights(t, ["market_odds", "refined_elo"])
        four_w = learn_weights(t, SIGNAL_ORDER)
        out["learned_weights"][t] = {"me": me_w, "four_sig": four_w}
        if me_w is None or four_w is None:
            continue
        variants = {
            "market_only": (["market_odds"], None),
            "me_equal": (["market_odds", "refined_elo"], {"market_odds": 0.5, "refined_elo": 0.5}),
            "me_learned": (["market_odds", "refined_elo"], me_w),
            "ens_equal": (SIGNAL_ORDER, {"market_odds": 0.25, "refined_elo": 0.25,
                                         "rolling_form": 0.25, "rest_days": 0.25}),
            "ens_learned": (SIGNAL_ORDER, four_w),
            "ens_prod": (SIGNAL_ORDER, None),
        }
        for name, (sigs, wts) in variants.items():
            probs, actuals = model_probs(matches, elo, sigs, wts)
            cache_merge(dil_caches, name, probs, actuals)

    out["dilution"]["models"] = {name: pooled_metrics(c) for name, c in dil_caches.items()}
    out["dilution"]["ci"] = bootstrap_cis(dil_caches)

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
    print(f"wrote {OUT_PATH}")


if __name__ == "__main__":
    main()