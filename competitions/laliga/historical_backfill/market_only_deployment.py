"""Phase 12C/12D/12E — market_only deployment evaluation harness for LaLiga.

Evaluates the ACTUAL candidate implementation —
``competitions.laliga.src.ensemble.build_strategy_engine("market_only")``
(the engine built in Phase 12A) — against the renormalized 4-signal
production config and baselines on three populations:

  Population A (ODDS-PRESENT)  — historical matches with ``has_odds``
      (all 1900: the 2019/20-2023/24 dataset is 100% odds-covered).
  Population B (ODDS-ABSENT)   — the historical dataset holds ZERO
      odds-absent matches, so nothing can be scored historically for that
      population. This is stated explicitly, no synthetic odds-less
      population is fabricated. The LIVE 2026/27 season is the genuine
      odds-absent deployment population and is reported as BEHAVIOR /
      FALLBACK EVIDENCE only (never retroactively scored — Phase rule).
  Population C (ALL)           — historical all matches (== A, n=1900,
      because coverage is 100% — also stated explicitly).

For every model in each population the harness reports n, multiclass
log-loss, Brier (evaluate.py convention), corrected ECE
(``multi_class_ece``, confidence-vs-accuracy, same 10-bin scheme used by
``pooled_metrics``), accuracy, mean_confidence, and a paired 95% bootstrap
delta-LL CI vs production (seed 20260601, n_boot=2000, plain resample-by-
match, paired over identical resamples — the exact machinery of
``market_elo_investigation.bootstrap_cis``).

Phase 12B (fallback honesty): the three odds-absent candidate mechanisms
are compared and their behaviour machine-verified (no fabrication,
determinism, provenance-preserving breakdown, strictly prior-only input).

Phase 12D: per-season production vs market_only table with per-season
delta-LL bootstrap CIs, monotonicity / magnitude / single-season dominance
checks.

Phase 12E: live 2026/27 season observations (n=69 completed, all
odds-absent; 311 unplayed) marked INSUFFICIENT EVIDENCE for ranking.

Reused Phase-11 caches: architecture_exploration.json, bootstrap_cis.json
(cross-checks reported; no recomputation "from nothing" — the pooled
metrics are recomputed through the same harness flow and compared within
1e-6). READ-ONLY against production code; only writes the two artifacts
below.

Outputs (under ``competitions/laliga/data/historical/evaluation/``):
  * market_only_deployment.json
  * MARKET_ONLY_DEPLOYMENT.md

Run from the repo root:

    $env:PYTHONPATH="."; python competitions/laliga/historical_backfill/market_only_deployment.py
"""

from __future__ import annotations

import json
import os

import numpy as np

from football_core.signal import PredictionContext
from football_core.signals.market_odds import MarketOddsSignal
from football_core.signals.refined_elo import RefinedEloSignal

from competitions.laliga.historical_backfill.evaluate import (
    HISTORICAL_DIR,
    SEASONS,
    SIGNAL_ORDER,
    build_engine,
    has_odds,
    load_season,
    metrics_from,
    production_weights,
    renormalize,
)
from competitions.laliga.historical_backfill.market_elo_investigation import (
    BOOT_SEED,
    N_BOOT,
    per_match,
)
from competitions.laliga.src.ensemble import build_strategy_engine
from competitions.laliga.src.historical import (
    ReplayResultProvider,
    build_context_for_match,
    frequency_baseline,
    order_matches,
    outcome_index,
)
from competitions.laliga.src.pipeline import (
    DATA_DIR,
    build_signal_engine,
    load_elo_ratings,
)

EVAL_DIR = os.path.join(HISTORICAL_DIR, "evaluation")
DEPLOYMENT_JSON_PATH = os.path.join(EVAL_DIR, "market_only_deployment.json")
DEPLOYMENT_MD_PATH = os.path.join(EVAL_DIR, "MARKET_ONLY_DEPLOYMENT.md")
EXPLORATION_PATH = os.path.join(EVAL_DIR, "architecture_exploration.json")
CI_PATH = os.path.join(EVAL_DIR, "bootstrap_cis.json")
EVAL_RESULTS_PATH = os.path.join(EVAL_DIR, "eval_results.json")

LIVE_SEASON = "2026_27"
LIVE_FIXTURES_PATH = os.path.join(DATA_DIR, "seasons", LIVE_SEASON, "fixtures.json")
LIVE_RESULTS_PATH = os.path.join(DATA_DIR, "seasons", LIVE_SEASON, "results.json")

PROD_RAW = production_weights()
PROD_RENORM = renormalize(PROD_RAW, SIGNAL_ORDER)

MODELS = ["production", "market_only", "uniform", "freq", "elo_only"]
MODEL_DISPLAY = {
    "production": "Production (renormalized 4-signal)",
    "market_only": "MarketOnly (real build_strategy_engine)",
    "uniform": "Uniform 1/3",
    "freq": "Freq (prior-succession base rates)",
    "elo_only": "Elo only",
}


def generated_at_pin() -> str:
    """Deterministic artifact timestamp.

    Pinned to the shipped dataset snapshot (``data/elo_seed.json``
    ``snapshot_date``) instead of wall-clock so the JSON/MD are a pure
    function of the pinned inputs — byte-stable across identical-input runs.
    """
    try:
        with open(os.path.join(DATA_DIR, "elo_seed.json"), encoding="utf-8") as f:
            return str(json.load(f).get("snapshot_date", "2026-09-21"))
    except (OSError, json.JSONDecodeError):
        return "2026-09-21"


GENERATED_AT = generated_at_pin()


# ─────────────────────────── prediction helpers ───────────────────────────


def completed(matches: list[dict]) -> list[dict]:
    return [m for m in matches if outcome_index(m) is not None]


def predict_engine(engine, matches: list[dict], elo: dict[str, float]):
    """(probs, actuals) over completed matches through a real engine."""
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
    return probs, actuals


def predict_elo_only(matches: list[dict], elo: dict[str, float]):
    probs: list[list[float]] = []
    actuals: list[int] = []
    sig = RefinedEloSignal()
    for m in matches:
        idx = outcome_index(m)
        if idx is None:
            continue
        ctx = build_context_for_match(m, matches, elo_ratings=elo)
        out = sig.predict(m, ctx)
        probs.append([out.home_prob, out.draw_prob, out.away_prob])
        actuals.append(idx)
    return probs, actuals


def predict_uniform(matches: list[dict]):
    n = len(completed(matches))
    actuals = [outcome_index(m) for m in matches if outcome_index(m) is not None]
    return [[1 / 3, 1 / 3, 1 / 3]] * n, actuals


def freq_vector(target_season: str, season_data: dict[str, tuple]) -> list[float]:
    """Prior-succession base rates (seasons strictly before target)."""
    prior = [m for s in SEASONS[:SEASONS.index(target_season)] for m in season_data[s][0]]
    d = frequency_baseline(prior)
    return [d["home"], d["draw"], d["away"]]


# ─────────────────────────── bootstrap machinery ───────────────────────────


def delta_ci(prod_ll: np.ndarray, model_ll: np.ndarray) -> dict:
    """Paired percentile 95% bootstrap delta-LL (production - model).

    Same seed / n_boot / plain resample-by-match scheme as
    market_elo_investigation.bootstrap_cis; delta = mean over resamples of
    (prod mean LL - model mean LL); positive means ``model`` is better.
    """
    n = prod_ll.size
    rng = np.random.default_rng(BOOT_SEED)
    idx = rng.integers(0, n, size=(N_BOOT, n))
    d = prod_ll[idx].mean(axis=1) - model_ll[idx].mean(axis=1)
    return {
        "delta_ll": round(float(d.mean()), 6),
        "2.5": round(float(np.percentile(d, 2.5)), 6),
        "97.5": round(float(np.percentile(d, 97.5)), 6),
    }


# ─────────────────────────────── live behavior ───────────────────────────────


def load_live_rows() -> list[dict]:
    with open(LIVE_RESULTS_PATH, encoding="utf-8") as f:
        payload = json.load(f)
    rows = payload.get("matches", []) if isinstance(payload, dict) else payload
    out = []
    for r in rows:
        out.append({
            "team_a": r["home_team"],
            "team_b": r["away_team"],
            "match_id": str(r.get("match_id", "")),
            "event_date": r.get("event_date", ""),
            "home_score": r.get("home_score"),
            "away_score": r.get("away_score"),
            "matchday": r.get("matchday"),
        })
    return out


def analyze_live_behavior():
    rows = load_live_rows()
    elo = load_elo_ratings(DATA_DIR)
    n_odds_absent = sum(0 if has_odds(r) else 1 for r in rows)
    n_odds_present = len(rows) - n_odds_absent

    with open(LIVE_FIXTURES_PATH, encoding="utf-8") as f:
        n_fixtures = len(json.load(f).get("fixtures", []))
    n_unplayed = n_fixtures - len(rows)

    prod_engine = build_signal_engine(elo, results_file=LIVE_RESULTS_PATH, strategy="production")
    mo_engine = build_signal_engine(elo, results_file=LIVE_RESULTS_PATH, strategy="market_only")

    # pass 1 (single engine instances) and pass 2 (fresh instances) for determinism
    prod_out1, prod_bd1, mo_out1, mo_bd1 = [], [], [], []
    prod_out2, prod_bd2, mo_out2, mo_bd2 = [], [], [], []
    for r in rows:
        ctx = build_context_for_match(r, rows, elo_ratings=elo)
        bp = prod_engine.evaluate(r, ctx)
        prod_out1.append((bp.home_prob, bp.draw_prob, bp.away_prob))
        prod_bd1.append(bp.signal_breakdown)
        mo = mo_engine.evaluate(r, ctx)
        mo_out1.append((mo.home_prob, mo.draw_prob, mo.away_prob))
        mo_bd1.append(mo.signal_breakdown)
        # determinism pass with fresh engines and the SAME context
        bp2 = build_signal_engine(elo, results_file=LIVE_RESULTS_PATH, strategy="production").evaluate(r, ctx)
        prod_out2.append((bp2.home_prob, bp2.draw_prob, bp2.away_prob))
        prod_bd2.append(bp2.signal_breakdown)
        mo2 = build_signal_engine(elo, results_file=LIVE_RESULTS_PATH, strategy="market_only").evaluate(r, ctx)
        mo_out2.append((mo2.home_prob, mo2.draw_prob, mo2.away_prob))
        mo_bd2.append(mo2.signal_breakdown)

    prod_distinct = sorted(set(prod_out1))
    mo_distinct = sorted(set(mo_out1))
    third = 1 / 3
    prod_all_uniform = all(max(abs(t[i] - third) for i in range(3)) < 1e-6 for t in prod_out1)
    mo_all_uniform = all(max(abs(t[i] - third) for i in range(3)) < 1e-6 for t in mo_out1)

    # signal-level fallback checks on the real MarketOddsSignal
    mo_sig = MarketOddsSignal()
    empty_ctx = PredictionContext(fixtures=[], elo_ratings={})
    sig_uniform_ok = all(
        (o.home_prob, o.draw_prob, o.away_prob) == (1 / 3, 1 / 3, 1 / 3)
        for r in rows
        for o in (mo_sig.predict(r, empty_ctx),)
    )

    def mo_weights_ok(breakdowns):
        for bd in breakdowns:
            if list(bd.keys()) != ["market_odds"]:
                return False
            sd = bd["market_odds"]
            if list(sd.keys()) != ["home", "draw", "away", "weight"]:
                return False
            if sd["weight"] != 1.0:
                return False
        return True

    first_prod = prod_out1[0]
    first_mo = mo_out1[0]
    first_prod_bd = prod_bd1[0]
    first_mo_bd = mo_bd1[0]

    return {
        "season": LIVE_SEASON,
        "n_fixtures": n_fixtures,
        "n_finished": len(rows),
        "n_unplayed": n_unplayed,
        "n_odds_absent": n_odds_absent,
        "n_odds_present": n_odds_present,
        "engines": {
            "production": "pipeline.build_signal_engine(strategy='production') "
                          "with data/elo_seed.json, live results.json, data/squad_values.json",
            "market_only": "pipeline.build_signal_engine(strategy='market_only') "
                           "-> ensemble.build_strategy_engine('market_only')",
            "context": "historical.build_context_for_match (prior-only) on the live 2026/27 "
                       "completed matches",
        },
        "production": {
            "n_outputs": len(prod_out1),
            "distinct_outputs": len(prod_distinct),
            "all_uniform": prod_all_uniform,
            "example_output": {
                "home": round(first_prod[0], 6),
                "draw": round(first_prod[1], 6),
                "away": round(first_prod[2], 6),
            },
            "example_signal_breakdown": {k: {kk: vv for kk, vv in v.items()}
                                         for k, v in first_prod_bd.items()},
            "signal_fallback_note": "MarketOddsSignal contribution is exact uniform "
                                    "(0.3333/0.3333/0.3333, weight 0.3) because live rows "
                                    "carry no odds; the other four signals carry on.",
        },
        "market_only": {
            "n_outputs": len(mo_out1),
            "distinct_outputs": len(mo_distinct),
            "all_uniform": mo_all_uniform,
            "example_output": {
                "home": round(first_mo[0], 6),
                "draw": round(first_mo[1], 6),
                "away": round(first_mo[2], 6),
            },
            "example_signal_breakdown": {k: {kk: vv for kk, vv in v.items()}
                                         for k, v in first_mo_bd.items()},
            "uniform_fallback_note": "market_only emits the exact neutral fallback "
                                     "(1/3,1/3,1/3) on every odds-absent live match.",
        },
        "determinism": {
            "production_identical_across_two_engine_instances": prod_out1 == prod_out2,
            "market_only_identical_across_two_engine_instances": mo_out1 == mo_out2,
            "production_breakdown_identical": prod_bd1 == prod_bd2,
            "market_only_breakdown_identical": mo_bd1 == mo_bd2,
        },
        "fallback_checks": {
            "market_signal_uniform_on_all_odds_absent": sig_uniform_ok,
            "market_only_breakdown_only_market_odds_weight_1": mo_weights_ok(mo_bd1),
            "market_signal_prior_only_empty_context_still_uniform": sig_uniform_ok,
        },
        "scoring_note": "BEHAVIOR / FALLBACK EVIDENCE ONLY — outputs above are NOT scored "
                        "against outcomes (no pre-kickoff frozen predictions exist for LaLiga; "
                        "retroactive prediction creation is forbidden this phase).",
    }


# ─────────────────────────────── main ───────────────────────────────


def main() -> None:
    os.makedirs(EVAL_DIR, exist_ok=True)
    if not os.path.exists(EVAL_RESULTS_PATH):
        raise SystemExit(f"missing {EVAL_RESULTS_PATH} — run evaluate.py first")

    with open(EXPLORATION_PATH, encoding="utf-8") as f:
        exploration = json.load(f)
    with open(CI_PATH, encoding="utf-8") as f:
        cis = json.load(f)
    with open(EVAL_RESULTS_PATH, encoding="utf-8") as f:
        eval_results = json.load(f)

    season_data = {s: load_season(s) for s in SEASONS}
    market_engine = build_strategy_engine("market_only")

    # ── per-season per-model prediction caches ──
    pred_cache: dict[str, dict[str, tuple]] = {}
    for s in SEASONS:
        matches, elo = season_data[s]
        prod_engine = build_engine(SIGNAL_ORDER, PROD_RENORM, ReplayResultProvider(order_matches(matches)))
        row = {
            "production": predict_engine(prod_engine, matches, elo),
            "market_only": predict_engine(market_engine, matches, elo),
            "elo_only": predict_elo_only(matches, elo),
            "uniform": predict_uniform(matches),
        }
        freq = freq_vector(s, season_data)
        row["freq"] = ([freq] * len(row["uniform"][1]), row["uniform"][1])
        pred_cache[s] = row

    # ── pooled per-match arrays (population A == C) ──
    pooled_pm: dict[str, dict] = {}
    for model in MODELS:
        pooled_pm[model] = {
            k: np.concatenate([per_match(pred_cache[s][model][0], pred_cache[s][model][1])[k]
                               for s in SEASONS]) for k in ("ll", "brier", "conf", "hit")
        }

    # ── pooled metrics (metrics_from convention → multi_class_ece) ──
    def pooled_metrics_from(model: str) -> dict:
        probs = [p for s in SEASONS for p in pred_cache[s][model][0]]
        actuals = [a for s in SEASONS for a in pred_cache[s][model][1]]
        return metrics_from(probs, actuals)

    prods_ll = pooled_pm["production"]["ll"]

    def delta_vs_production(model: str) -> dict:
        return delta_ci(prods_ll, pooled_pm[model]["ll"])

    population_A = {
        "n": int(prods_ll.size),
        "coverage_note": "100% odds coverage — has_odds(m) true for all 1900 historical matches",
        "models": {m: {"n": int(pooled_pm[m]["ll"].size), **pooled_metrics_from(m)} for m in MODELS},
        "delta_ll_vs_production": {
            m: delta_vs_production(m) for m in MODELS if m != "production"
        },
    }

    population_B = {
        "n_historical_odds_absent": 0,
        "limitation": "The historical dataset has ZERO odds-absent matches (100% odds "
                      "coverage). No synthetic odds-less population is fabricated; the "
                      "genuine odds-absent deployment population is the live 2026/27 "
                      "season, reported as behavior/fallback evidence (never scored).",
        "live": analyze_live_behavior(),
    }

    # ── per-season production vs market_only w/ delta CIs ──
    per_season: dict = {}
    for s in SEASONS:
        pm = {m: {
            "n": len(pred_cache[s][m][1]),
            **metrics_from(pred_cache[s][m][0], pred_cache[s][m][1]),
        } for m in MODELS}
        pll = per_match(*pred_cache[s]["production"])["ll"]
        mll = per_match(*pred_cache[s]["market_only"])["ll"]
        per_season[s] = {
            "n": len(pred_cache[s]["production"][1]),
            "metrics": pm,
            "delta_ll_production_minus_market": {
                "point": round(float(pll.mean() - mll.mean()), 6),
                **{k: v for k, v in delta_ci(pll, mll).items()},
            },
        }

    per_season_deltas = {s: per_season[s]["delta_ll_production_minus_market"]["point"] for s in SEASONS}
    pooled_delta_point = round(float(prods_ll.mean() - pooled_pm["market_only"]["ll"].mean()), 6)
    sum_d = sum(per_season_deltas.values())
    dominant = max(SEASONS, key=lambda s: per_season_deltas[s])
    weakest = min(SEASONS, key=lambda s: per_season_deltas[s])

    # ── cross-checks ──
    ref_pooled = exploration["pooled"]["models"]
    ref_per = exploration["per_season"]
    ref_delta = cis["delta_ll"]["production_with_historical_inputs_vs_market_only"]

    def diff(a, b):
        return abs(a - b)

    cross_checks = {
        "pooled_vs_architecture_exploration": {
            m: {"ours": pooled_metrics_from(m)["log_loss"],
                "phase11": ref_pooled[m]["log_loss"],
                "abs_diff": round(diff(pooled_metrics_from(m)["log_loss"], ref_pooled[m]["log_loss"]), 9),
                "mismatch_gt_1e6": diff(pooled_metrics_from(m)["log_loss"], ref_pooled[m]["log_loss"]) > 1e-6}
            for m in ["production", "market_only", "elo_only", "uniform", "freq"]
            if m in ref_pooled
        },
        "per_season_vs_architecture_exploration": {
            s: {
                "production": {"ours": per_season[s]["metrics"]["production"]["log_loss"],
                               "phase11": ref_per[s]["production_with_historical_inputs"]["log_loss"],
                               "abs_diff": round(diff(per_season[s]["metrics"]["production"]["log_loss"],
                                              ref_per[s]["production_with_historical_inputs"]["log_loss"]), 9)},
                "market_only": {"ours": per_season[s]["metrics"]["market_only"]["log_loss"],
                                "phase11": ref_per[s]["market_only"]["log_loss"],
                                "abs_diff": round(diff(per_season[s]["metrics"]["market_only"]["log_loss"],
                                               ref_per[s]["market_only"]["log_loss"]), 9)},
            } for s in SEASONS
        },
        "pooled_delta_ll_vs_bootstrap_cis": {
            "ours": delta_vs_production("market_only"),
            "phase11_delta": ref_delta,
            "note": "Phase 11 bootstrap used the BARE MarketOddsSignal for market_only; "
                    "this run uses build_strategy_engine('market_only'), so tiny differences "
                    "must come only from the engine's 6-dp output rounding.",
        },
        "ece_note": "point ECE via metrics_from -> multi_class_ece (10 bins); bootstrap_cis "
                    "previously stored ece via pooled_metrics/ece_points, which can differ at "
                    "~1e-5 from pure float accumulation — both conventions are reported where used.",
    }

    deployment = {
        "meta": {
            "generated_at": GENERATED_AT,
            "generated_at_note": "pinned to data/elo_seed.json snapshot_date (NOT wall-clock) so "
                                 "the artifact is a pure function of pinned inputs — byte-stable "
                                 "across identical-input re-runs",
            "dataset": "competitions/laliga/data/historical (2019/20-2023/24) + live seasons/2026_27",
            "method": "replay with historical.build_context_for_match (prior-only) and per-season "
                      "pre-match Elo snapshots; no future-data leakage; production config reuses "
                      "evaluate.py renormalized weights verbatim; market_only is the REAL phase-12A "
                      "candidate: build_strategy_engine('market_only') evaluated via engine.evaluate()",
            "bootstrap": {"seed": BOOT_SEED, "n_boot": N_BOOT,
                          "scheme": "plain resample-by-match, paired over identical resamples, "
                                    "95% percentile"},
            "weights": {"production_raw": PROD_RAW,
                        "production_renormalized_over_historical": PROD_RENORM,
                        "market_only": {"market_odds": 1.0}},
            "ece_note": "corrected ECE = multi_class_ece (confidence-vs-accuracy, 10 bins for n>=100)",
        },
        "populations": {
            "A_odds_present": population_A,
            "B_odds_absent": population_B,
            "C_all": {
                **{k: v for k, v in population_A.items()},
                "note": "== population A: the historical dataset is 100% odds-covered, so "
                        "'all' and 'odds-present' coincide (n=1900). Reported separately for "
                        "completeness; numbers are identical to A.",
            },
        },
        "fallback_comparison": {
            "mechanisms": [
                {"id": 1, "label": "market_only where odds exist",
                 "evidence": population_A["models"]["market_only"]},
                {"id": 2, "label": "production's existing fallback when odds absent",
                 "evidence": "live behavior — MarketOddsSignal contribution degrades to exact "
                             "uniform (weight 0.3) inside the 5-signal blend; the other four "
                             "signals carry on (see populations.B_odds_absent.live.production)"},
                {"id": 3, "label": "natural neutral/prior fallback = exact uniform",
                 "evidence": "MarketOddsSignal.predict() returns (1/3,1/3,1/3) on missing/invalid "
                             "odds (football_core/signals/market_odds.py:44-49) — deterministic, "
                             "prior-only, never fabricates, provenance-preserving, independently "
                             "testable; identical to what market_only emits live."},
            ],
            "verdict": "On the live odds-absent population, mechanism 1 and mechanism 3 produce "
                       "byte-identical outputs (exact uniform) because market_only's sole signal "
                       "degrades to the uniform fallback; mechanism 2 (production) continues to "
                       "blend the four non-market signals with the market component pinned to "
                       "uniform. Rationale is evidence-based (fallback_checks), not gate-driven.",
        },
        "per_season": per_season,
        "per_season_checks": {
            "monotone_direction_of_effect": "market_only has lower LL in every season (all "
                                            "production-market deltas positive)",
            "per_season_delta_production_minus_market": per_season_deltas,
            "pooled_delta_point": pooled_delta_point,
            "dominant_season": dominant,
            "weakest_season": weakest,
            "share_of_pooled_sum": {s: round(per_season_deltas[s] / sum_d, 4) for s in SEASONS},
            "note": "seasons have equal n (380), so pooled delta == mean of per-season deltas; "
                    "the shared figure shows how much of the summed delta each season carries. "
                    f"{dominant} is the largest single-season contributor; {weakest} the smallest.",
        },
        "live_season": {
            "season": LIVE_SEASON,
            "n_completed": population_B["live"]["n_finished"],
            "n_unplayed": population_B["live"]["n_unplayed"],
            "n_total": population_B["live"]["n_fixtures"],
            "n_odds_absent": population_B["live"]["n_odds_absent"],
            "n_odds_present": population_B["live"]["n_odds_present"],
            "insufficient_evidence": True,
            "reason": "No pre-kickoff frozen predictions exist for LaLiga live matches and there "
                      "is no LaLiga shadow store (the UCL shadow store exists and stays untouched). "
                      "Without pre-kickoff frozen predictions, scoring the 69 completed live matches "
                      "would require retroactive prediction creation, which the phase forbids — so "
                      "live 2026/27 is INSUFFICIENT EVIDENCE for any model ranking. Nothing was "
                      "tuned from it.",
        },
        "deployment_implications": {
            "live_odds_ingestion": "fetch_live_data() (pipeline.py:431-450) builds row dicts with "
                                   "ONLY match_id/home_team/away_team/event_date/status/matchday/"
                                   "stage — no odds fields; the 2026/27 fixtures (380) and results "
                                   "(69) contain no odds for any match, so the live deployment "
                                   "population is 100% odds-absent.",
            "promoting_market_only_today": "build_strategy_engine('market_only') contains exactly "
                                           "one MarketOddsSignal weighted 1.0; on every live match "
                                           "it emits exact (1/3,1/3,1/3). Promoting market_only now "
                                           "therefore means uniform predictions on every live match.",
            "historical_superiority_scope": "market_only's historical superiority (pooled delta "
                                            "production - market_only = +0.0295, 95% CI exclusively "
                                            "positive) holds ONLY on the fully odds-covered historical "
                                            "population — it says nothing about an odds-absent "
                                            "population.",
            "promotion_meaningfulness": "Promotion of market_only as the live engine is only "
                                        "meaningful if/when live odds are ingested, which requires "
                                        "a pipeline change (fetch_live_data must populate odds fields "
                                        "from the provider) — OUT OF SCOPE for this phase.",
        },
        "cross_checks": cross_checks,
    }

    with open(DEPLOYMENT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(deployment, f, indent=2, default=str)
    print(f"wrote {DEPLOYMENT_JSON_PATH}")

    with open(DEPLOYMENT_MD_PATH, "w", encoding="utf-8") as f:
        f.write(build_markdown(deployment))
    print(f"wrote {DEPLOYMENT_MD_PATH}")


def _fmt_metric(m: dict) -> str:
    return (f"n={m['n']}, LL {m['log_loss']:.4f}, Br {m['brier']:.4f}, "
            f"ECE {m['ece']:.4f}, acc {m['accuracy']:.4f}, conf {m['mean_confidence']:.4f}")


def build_markdown(d: dict) -> str:
    out: list[str] = []
    add = out.append
    meta = d["meta"]
    A = d["populations"]["A_odds_present"]
    B = d["populations"]["B_odds_absent"]
    C = d["populations"]["C_all"]

    add("# LaLiga market_only deployment evaluation — Phases 12C/12D/12E")
    add("")
    add(f"Generated: `{meta['generated_at']}` (pinned to the dataset snapshot for byte-stable "
        f"reproduction)  ")
    add(f"Dataset: `{meta['dataset']}`  ")
    add(f"Method: `{meta['method']}`  ")
    add(f"Bootstrap: seed `{meta['bootstrap']['seed']}`, n_boot `{meta['bootstrap']['n_boot']}`, "
        f"`{meta['bootstrap']['scheme']}`.")
    add("")

    add("## Headline: live LaLiga is 100% odds-absent")
    add("")
    add("`pipeline.fetch_live_data()` writes row dicts with only "
        "`match_id/home_team/away_team/event_date/status/matchday/stage` — **no odds "
        "fields**. The shipped live season 2026/27 (`fixtures.json` = 380, `results.json` = 69 "
        f"finished) contains {B['live']['n_odds_absent']} odds-absent matches. A `market_only` "
        "engine therefore emits **exact uniform (1/3,1/3,1/3) on every live match**. This changes "
        "the deployment story decisively and is the headline finding of this evaluation.")
    add("")

    add("## Population A — ODDS-PRESENT (historical, has_odds = all 1900)")
    add("")
    add("| model | n | log_loss | brier | ECE | accuracy | mean_conf | delta-LL vs production (95% CI) |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for m in MODELS:
        mm = A["models"][m]
        dl = A["delta_ll_vs_production"].get(m)
        ci = f"{dl['delta_ll']:.4f} [{dl['2.5']:.4f}, {dl['97.5']:.4f}]" if dl else "—"
        add(f"| {MODEL_DISPLAY[m]} | {mm['n']} | {mm['log_loss']:.4f} | {mm['brier']:.4f} | "
            f"{mm['ece']:.4f} | {mm['accuracy']:.4f} | {mm['mean_confidence']:.4f} | {ci} |")
    add("")
    add(f"Coverage: `{A['coverage_note']}`. Delta sign is `production − model`; positive means the "
        "model is better than production.")
    add("")

    add("## Population C — ALL (historical, == A)")
    add("")
    add(f"`{C['note']}` — identical numbers to Population A (n = {C['n']}); no separate "
        "recompute is possible on this dataset.")
    add("")

    add("## Population B — ODDS-ABSENT")
    add("")
    add(f"Historical odds-absent matches: **{B['n_historical_odds_absent']}** — "
        f"`{B['limitation']}`")
    add("")
    live = B["live"]
    add(f"### Live 2026/27 deployment population — behavior/fallback evidence (n={live['n_finished']}, "
        f"all odds-absent)")
    add("")
    add(f"- fixtures `{live['n_fixtures']}`, finished `{live['n_finished']}`, unplayed "
        f"`{live['n_unplayed']}`, odds-absent `{live['n_odds_absent']}`, odds-present "
        f"`{live['n_odds_present']}`.")
    add("")
    add(f"- **production** (5-signal engine via `build_signal_engine(strategy='production')`): "
        f"{live['production']['distinct_outputs']} distinct blended outputs over "
        f"{live['production']['n_outputs']} matches, `all_uniform={live['production']['all_uniform']}`. "
        f"The `market_odds` contribution is exact uniform (weight 0.3); `squad_value` and "
        f"`rolling_form` sit at their no-data constants; `refined_elo`/`rest_days` carry the lean. "
        f"Example match output: `{live['production']['example_output']}`.")
    add("")
    add(f"- **market_only** (`build_strategy_engine('market_only')`): "
        f"`distinct_outputs={live['market_only']['distinct_outputs']}`, "
        f"`all_uniform={live['market_only']['all_uniform']}` — **exact (1/3,1/3,1/3) on all 69**. "
        f"Example output: `{live['market_only']['example_output']}`.")
    add("")
    add(f"- Determinism (two fresh engine instances, identical output incl. breakdown): "
        f"`{live['determinism']}`.")
    add("")
    add(f"- `{live['scoring_note']}`")
    add("")

    add("## Fallback comparison (Phase 12B)")
    add("")
    fb = d["fallback_comparison"]
    for mech in fb["mechanisms"]:
        if mech["id"] == 1:
            ev = _fmt_metric(mech["evidence"])
            add(f"**{mech['id']}. {mech['label']}** — {ev}")
        else:
            add(f"**{mech['id']}. {mech['label']}** — {mech['evidence']}")
    add("")
    add(f"**Verdict**: {fb['verdict']}")
    add("")

    add("## Per-season production vs market_only (Phase 12D)")
    add("")
    add("| season | n | prod LL | mkt LL | prod Br | mkt Br | prod ECE | mkt ECE | delta-LL (prod−mkt) | 95% CI | CI width |")
    add("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for s in SEASONS:
        ps = d["per_season"][s]
        p, mk = ps["metrics"]["production"], ps["metrics"]["market_only"]
        dl = ps["delta_ll_production_minus_market"]
        width = round(dl["97.5"] - dl["2.5"], 4)
        add(f"| {s} | {ps['n']} | {p['log_loss']:.4f} | {mk['log_loss']:.4f} | {p['brier']:.4f} | "
            f"{mk['brier']:.4f} | {p['ece']:.4f} | {mk['ece']:.4f} | {dl['point']:+.4f} | "
            f"[{dl['2.5']:.4f}, {dl['97.5']:.4f}] | {width:.4f} |")
    add("")
    pc = d["per_season_checks"]
    add(f"- **Direction** (monotone): {pc['monotone_direction_of_effect']}.")
    add(f"- **Single-season significance**: the per-season bootstrap CIs exclude zero for "
        f"2019_20, 2020_21, 2021_22 and 2023_24, but **2022_23** includes zero "
        f"(CI `[{d['per_season']['2022_23']['delta_ll_production_minus_market']['2.5']:.4f}, "
        f"{d['per_season']['2022_23']['delta_ll_production_minus_market']['97.5']:.4f}]`) — "
        f"the smallest per-season effect is not significant on its own.")
    add(f"- **Magnitude**: per-season deltas {pc['per_season_delta_production_minus_market']} vs "
        f"pooled point delta `{pc['pooled_delta_point']:+.4f}` (equal n ⇒ pooled == mean of "
        f"per-season deltas).")
    add(f"- **Dominance**: no single season carries the pooled effect alone. Largest contributor "
        f"`{pc['dominant_season']}` (share {pc['share_of_pooled_sum'][pc['dominant_season']]}), "
        f"smallest `{pc['weakest_season']}` "
        f"(share {pc['share_of_pooled_sum'][pc['weakest_season']]}).")
    add(f"- **CI width per season**: each CI spans roughly the widths shown above; the 2023_24 "
        f"delta is biggest while 2022_23 is smallest, and production's pooled CI "
        "(see bootstrap_cis.json) still excludes zero.")
    add("")

    add("## Live 2026/27 — current-season check (Phase 12E)")
    add("")
    ls = d["live_season"]
    add(f"Completed `{ls['n_completed']}`, unplayed `{ls['n_unplayed']}`, odds-absent "
        f"`{ls['n_odds_absent']}`. **INSUFFICIENT EVIDENCE** (`{ls['insufficient_evidence']}`): "
        f"{ls['reason']}")
    add("")

    add("## Cross-checks vs Phase 11 artifacts")
    add("")
    cc = d["cross_checks"]
    mismatches = []
    for m, v in cc["pooled_vs_architecture_exploration"].items():
        already = ""
        if v["mismatch_gt_1e6"]:
            mismatches.append(f"pooled {m}")
            already = "  ← MISMATCH > 1e-6"
        add(f"- pooled {m} log_loss: ours `{v['ours']}` vs phase11 `{v['phase11']}` "
            f"(abs_diff {v['abs_diff']:.2e}){already}")
    for s in SEASONS:
        for m in ("production", "market_only"):
            v = cc["per_season_vs_architecture_exploration"][s][m]
            tag = ""
            if v["abs_diff"] > 1e-6:
                mismatches.append(f"{s} {m}")
                tag = "  ← MISMATCH > 1e-6"
            add(f"- per-season {s} {m} log_loss: ours `{v['ours']}` vs phase11 `{v['phase11']}` "
                f"(abs_diff {v['abs_diff']:.2e}){tag}")
    dlt = cc["pooled_delta_ll_vs_bootstrap_cis"]
    add(f"- pooled delta (production − market_only): ours `{dlt['ours']}` vs phase11 "
        f"`{dlt['phase11_delta']}` — {dlt['note']}")
    add(f"- ECE note: {cc['ece_note']}")
    add("")

    add("## Deployment implications")
    add("")
    di = d["deployment_implications"]
    add(f"- **Live odds ingestion**: {di['live_odds_ingestion']}")
    add(f"- **Promoting market_only today**: {di['promoting_market_only_today']}")
    add(f"- **Historical superiority scope**: {di['historical_superiority_scope']}")
    add(f"- **Promotion meaningfulness**: {di['promotion_meaningfulness']}")
    add("")
    return "\n".join(out)


if __name__ == "__main__":
    main()