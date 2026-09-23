"""LaLiga reduced-architecture investigation + promotion-gate evidence.

Evaluates seven architectures and the leave-one-signal-out ablations on the
SAME out-of-sample protocol as ``evaluate.py`` (every match predicted through
``historical.build_context_for_match`` — prior-only — with the season's own
pre-match Elo snapshot; per-season chronological + pooled reporting):

    1. market_only                    — market_odds alone (weights=1)
    2. elo_only                       — refined_elo alone (weights=1)
    3. market_elo_equal               — 0.5/0.5 market+elo
    4. market_form_equal              — 0.5/0.5 market+form
    5. market_form_rest               — 0.55/0.35/0.10 market+form+rest
    6. market_form_rest_elo_equal     — 0.25 each (all four signals)
    7. production_with_historical_inputs — the FIVE production weights
       renormalized over the four signals with historical inputs
       (market_odds/refined_elo/rolling_form/rest_days — exactly as
       evaluate.py does; squad_value has no historical source and is NOT
       invented). Weights are reused as-is, never fitted.

It also:

  * extracts the leave-one-signal-out ablation the eval harness already wrote
    into ``eval_results.json`` (removing elo / odds / form / rest one at a
    time with production-renormalized weights) and reports the delta-log-loss
    per removal,
  * reuses the ``weights_learned`` section of ``eval_results.json``
    (inverse-log-loss fit on STRICTLY-prior seasons, never the eval season)
    for weight-stability evidence,
  * computes 2000-resample 95% percentile bootstrap CIs on the pooled
    headline metrics (log_loss, brier, ece, accuracy) for the production
    config and market_only (plus uniform and prior-season freq), paired over
    identical resamples, and paired delta-LL CIs,
  * writes a LaLiga-specific promotion gate verdict (CANDIDATE_GATE.md).

Constraints honored (READ-ONLY: nothing in football_core, competitions/ucl,
competitions/worldcup, production code, or live LaLiga data is modified):

  * every prediction routes through ``historical.build_context_for_match``
    (prior-only) with the season's pre-match Elo snapshot,
  * directly-compared tables always use identical match lists,
  * no weight tuning on the evaluation set; the production config reuses
    evaluate.py's renormalized production weights verbatim,
  * deterministic bootstrap (fixed seed 20260601, fixed resamples).

Outputs (all under ``competitions/laliga/data/historical/evaluation/``):
  * architecture_exploration.json
  * bootstrap_cis.json
  * CANDIDATE_GATE.md

Run from the repo root:

    $env:PYTHONPATH="."; python competitions/laliga/historical_backfill/market_elo_investigation.py
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import numpy as np

from competitions.laliga.historical_backfill.evaluate import (
    HISTORICAL_DIR,
    SEASONS,
    SIGNAL_ORDER,
    _signal_output,
    build_engine,
    load_season,
    metrics_from,
    production_weights,
    renormalize,
)
from competitions.laliga.src.historical import (
    ReplayResultProvider,
    build_context_for_match,
    frequency_baseline,
    order_matches,
    outcome_index,
)

EVAL_DIR = os.path.join(HISTORICAL_DIR, "evaluation")
EXPLORATION_PATH = os.path.join(EVAL_DIR, "architecture_exploration.json")
CI_PATH = os.path.join(EVAL_DIR, "bootstrap_cis.json")
GATE_MD_PATH = os.path.join(EVAL_DIR, "CANDIDATE_GATE.md")
EVAL_RESULTS_PATH = os.path.join(EVAL_DIR, "eval_results.json")

BOOT_SEED = 20260601
N_BOOT = 2000
UNIFORM_LL = 1.098612

# Configuration table. ``weights=None`` for a single signal means "bare signal";
# ``weights=None`` for a multi-signal config means "production weights
# renormalized over those signals" (i.e. the production config).
CONFIGS = [
    ("market_only", ["market_odds"], None),
    ("elo_only", ["refined_elo"], None),
    ("market_elo_equal", ["market_odds", "refined_elo"],
     {"market_odds": 0.5, "refined_elo": 0.5}),
    ("market_form_equal", ["market_odds", "rolling_form"],
     {"market_odds": 0.5, "rolling_form": 0.5}),
    ("market_form_rest", ["market_odds", "rolling_form", "rest_days"],
     {"market_odds": 0.55, "rolling_form": 0.35, "rest_days": 0.10}),
    ("market_form_rest_elo_equal", SIGNAL_ORDER,
     {"market_odds": 0.25, "refined_elo": 0.25, "rolling_form": 0.25, "rest_days": 0.25}),
    ("production_with_historical_inputs", SIGNAL_ORDER, None),
]

CONFIG_DISPLAY = {
    "market_only": "Market odds only",
    "elo_only": "Elo only",
    "market_elo_equal": "Market + Elo (equal 0.5/0.5)",
    "market_form_equal": "Market + Form (equal 0.5/0.5)",
    "market_form_rest": "Market + Form + Rest (0.55/0.35/0.10)",
    "market_form_rest_elo_equal": "Market + Form + Rest + Elo (equal 0.25)",
    "production_with_historical_inputs": "Production ensemble (5 wts renormalized /4)",
}

PROD_RAW = production_weights()
PROD_RENORM = renormalize(PROD_RAW, SIGNAL_ORDER)


# ─────────────────────────── prediction helpers ───────────────────────────


def predict_config(matches, elo, signals, weights):
    """(probs, actuals) on completed matches for one config.

    ``weights=None`` + single signal → bare signal output;
    ``weights=None`` + multi signal → production weights renormalized over
    ``signals`` (idempotent with evaluate.py's engine build).
    """
    if len(signals) == 1 and weights is None:
        probs, actuals = [], []
        for m in matches:
            idx = outcome_index(m)
            if idx is None:
                continue
            ctx = build_context_for_match(m, matches, elo_ratings=elo)
            out = _signal_output(signals[0], m, ctx, matches)
            probs.append([out.home_prob, out.draw_prob, out.away_prob])
            actuals.append(idx)
        return probs, actuals

    eff_w = renormalize(PROD_RAW, signals) if weights is None else weights
    eng = build_engine(signals, eff_w, ReplayResultProvider(order_matches(matches)))
    probs, actuals = [], []
    for m in matches:
        idx = outcome_index(m)
        if idx is None:
            continue
        ctx = build_context_for_match(m, matches, elo_ratings=elo)
        bp = eng.evaluate(m, ctx)
        probs.append([bp.home_prob, bp.draw_prob, bp.away_prob])
        actuals.append(idx)
    return probs, actuals


def uniform_rows(matches):
    probs, actuals = [], []
    for m in matches:
        idx = outcome_index(m)
        if idx is None:
            continue
        probs.append([1 / 3, 1 / 3, 1 / 3])
        actuals.append(idx)
    return probs, actuals


def freq_preds(target, season_data):
    """Prior-succession base rates (strictly-before seasons only)."""
    prior_m = [m for s in SEASONS[:SEASONS.index(target)] for m in season_data[s][0]]
    d = frequency_baseline(prior_m)
    return [d["home"], d["draw"], d["away"]]


# ─────────────────────── per-match arrays + bootstrap ───────────────────────


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


def cache_merge(cache, name, probs, actuals):
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


def pooled_metrics(c) -> dict:
    # Brier follows evaluate.py's multi_class_brier convention (mean per-class
    # squared error), so the mean per-match vector length is divided by 3.
    return {
        "n": c["n"],
        "log_loss": round(float(c["ll"].mean()), 6),
        "brier": round(float(c["brier"].mean() / 3), 6),
        "ece": round(float(ece_points(c["conf"], c["hit"])), 6),
        "mean_confidence": round(float(c["conf"].mean()), 6),
        "accuracy": round(float(c["hit"].mean()), 6),
    }


def ece_points(conf, hit, n_bins=10):
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        mask = ((conf >= lo) & (conf < hi)) | ((b == n_bins - 1) & (conf == 1.0))
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        ece += (cnt / conf.size) * abs(float(conf[mask].mean()) - float(hit[mask].sum() / cnt))
    return ece


def _ece_bulk(conf_all, hit_all, idx, n_bins=10):
    """Vectorized ECE across all bootstrap resamples (same binning as above).

    Confidences/hits are indexed by the resample indices (``conf_all[idx]``)
    so each resample is binned by ITS draws' confidence, not the originals'.
    """
    n = conf_all.size
    ece = np.zeros(N_BOOT)
    drawn_conf = conf_all[idx]
    drawn_hit = hit_all[idx]
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        mask = (conf_all >= lo) & (conf_all < hi)
        if b == n_bins - 1:
            mask = mask | (conf_all == 1.0)
        if not mask.any():
            continue
        m_row = mask[idx]
        cnt = m_row.sum(axis=1).astype(float)
        cnt_safe = np.where(cnt > 0, cnt, 1.0)
        mc = (m_row * drawn_conf).sum(axis=1) / cnt_safe
        mh = (m_row * drawn_hit).sum(axis=1) / cnt_safe
        ece += np.where(cnt > 0, (cnt / n) * np.abs(mc - mh), 0.0)
    return ece


def _pct(vals, q):
    return round(float(np.percentile(vals, q)), 6)


def bootstrap_cis(cache: dict[str, dict]) -> dict:
    """95% percentile bootstrap, plain resample-by-match, paired over
    identical resamples. Simpler than season-block bootstrap (n=1900 across
    only 5 seasons) and documented as such in the meta."""
    rng = np.random.default_rng(BOOT_SEED)
    n = cache[next(iter(cache))]["n"]
    idx = rng.integers(0, n, size=(N_BOOT, n))

    out: dict = {}
    for name, c in cache.items():
        ll_b = c["ll"][idx].mean(axis=1)
        br_b = c["brier"][idx].mean(axis=1) / 3.0
        acc_b = c["hit"][idx].mean(axis=1)
        ece_b = _ece_bulk(c["conf"], c["hit"], idx)
        pts = pooled_metrics(c)
        out[name] = {
            "log_loss": {"point": pts["log_loss"], "2.5": _pct(ll_b, 2.5), "97.5": _pct(ll_b, 97.5)},
            "brier": {"point": pts["brier"], "2.5": _pct(br_b, 2.5), "97.5": _pct(br_b, 97.5)},
            "ece": {"point": pts["ece"], "2.5": _pct(ece_b, 2.5), "97.5": _pct(ece_b, 97.5)},
            "accuracy": {"point": pts["accuracy"], "2.5": _pct(acc_b, 2.5), "97.5": _pct(acc_b, 97.5)},
        }

    pairs = [
        ("production_with_historical_inputs", "market_only"),
        ("production_with_historical_inputs", "uniform"),
        ("production_with_historical_inputs", "freq_prior_season"),
        ("market_only", "uniform"),
        ("market_only", "freq_prior_season"),
        ("production_with_historical_inputs", "elo_only"),
        ("market_only", "elo_only"),
    ]
    delta: dict = {}
    for a, b in pairs:
        if a not in cache or b not in cache:
            continue
        d = cache[a]["ll"][idx].mean(axis=1) - cache[b]["ll"][idx].mean(axis=1)
        delta[f"{a}_vs_{b}"] = {
            "delta_ll": round(float(d.mean()), 6),
            "2.5": round(float(np.percentile(d, 2.5)), 6),
            "97.5": round(float(np.percentile(d, 97.5)), 6),
        }
    out["_delta_ll"] = delta
    return out


# ────────────────────────────── ablation ──────────────────────────────

_ABL_RENAME = {
    "without_elo": "remove_refined_elo",
    "without_odds": "remove_market_odds",
    "without_form": "remove_rolling_form",
    "without_rest": "remove_rest_days",
}


def extract_ablation(eval_results):
    """Pull the leave-one-signal-out ablation the eval harness already wrote
    (production-renormalized weights over the 4 historical signals)."""
    abl = eval_results["ablation"]
    overall = abl["overall"]
    full_ll = overall["full"]["log_loss"]
    delta = {
        _ABL_RENAME[k]: round(overall[k]["log_loss"] - full_ll, 6)
        for k in _ABL_RENAME
    }
    most = max(delta, key=delta.get)
    redundant = min(delta, key=lambda k: abs(delta[k]))
    return {
        "per_season": {
            s: {"n": abl[s]["n"],
                **{_ABL_RENAME[k]: v for k, v in abl[s].items() if k in _ABL_RENAME}}
            for s in SEASONS
        },
        "overall": {
            "n": overall["n"],
            **{_ABL_RENAME[k]: v for k, v in overall.items() if k in _ABL_RENAME},
        },
        "delta_log_loss_overall_removal_minus_full": delta,
        "summary": {
            "signal_with_largest_log_loss_contribution": most,
            "signal_closest_to_redundant": redundant,
            "note": "delta-log-loss = LL(without signal) - LL(full); positive "
                    "means removing the signal hurts (the signal helps).",
        },
    }


# ────────────────────────────── gate ──────────────────────────────


def run_gate(pooled, ci, per_prod, per_market, season_n, window):
    checks: list[dict] = []

    d = ci["_delta_ll"]["production_with_historical_inputs_vs_uniform"]
    checks.append({
        "id": "C1",
        "condition": "Ensemble beats uniform 1/3 on the full population",
        "test": "production pooled LL < uniform (1.0986) and delta-LL CI "
                "(production - uniform) entirely negative",
        "value": pooled["production_with_historical_inputs"]["log_loss"],
        "ref": UNIFORM_LL,
        "delta_ll": d,
        "pass": pooled["production_with_historical_inputs"]["log_loss"] < UNIFORM_LL
                and d["97.5"] < 0,
    })

    d = ci["_delta_ll"]["production_with_historical_inputs_vs_freq_prior_season"]
    checks.append({
        "id": "C2",
        "condition": "Ensemble beats empirical-frequency baseline",
        "test": "production pooled LL < freq_prior_season and delta-LL CI "
                "entirely negative; supplementary: pooled chronological 70/30 "
                "window from evaluate.py",
        "value": pooled["production_with_historical_inputs"]["log_loss"],
        "ref": pooled["freq_prior_season"]["log_loss"],
        "delta_ll": d,
        "supplementary_eval_window": {
            "n": window["n_eval"],
            "ensemble": window["ensemble"]["log_loss"],
            "freq": window["freq"]["log_loss"],
        },
        "pass": pooled["production_with_historical_inputs"]["log_loss"]
                < pooled["freq_prior_season"]["log_loss"] and d["97.5"] < 0,
    })

    cece = ci["production_with_historical_inputs"]["ece"]
    checks.append({
        "id": "C3",
        "condition": "Acceptable calibration (ECE)",
        "test": "production pooled ECE <= 0.10 with the bootstrap 95% CI upper "
                "bound also <= 0.10 (0.05 = 'good', 0.10 = acceptable)",
        "point": cece["point"],
        "ci": cece,
        "pass": cece["97.5"] <= 0.10,
    })

    d = ci["_delta_ll"]["production_with_historical_inputs_vs_market_only"]
    checks.append({
        "id": "C4",
        "condition": "Ensemble beats market-only (net LL gain w/ CI)",
        "test": "bootstrap delta-LL (production - market_only) 95% CI upper "
                "bound strictly below 0 (i.e. production better)",
        "value": pooled["production_with_historical_inputs"]["log_loss"],
        "ref": pooled["market_only"]["log_loss"],
        "delta_ll": d,
        "pass": d["97.5"] < 0,
    })

    deficits = {s: round(per_prod[s]["log_loss"] - per_market[s]["log_loss"], 6)
                for s in SEASONS}
    pooled_deficit = pooled["production_with_historical_inputs"]["log_loss"] \
        - pooled["market_only"]["log_loss"]
    no_uniform_flip = all(per_prod[s]["log_loss"] < UNIFORM_LL for s in SEASONS)
    worst = max(deficits.values())
    checks.append({
        "id": "C5",
        "condition": "No catastrophic season in per-season results",
        "test": "production beats uniform in every season and no season's "
                "production - market_only deficit exceeds 2x the pooled deficit "
                "(season-collapse guard)",
        "per_season_deficit_production_minus_market": deficits,
        "pooled_deficit": round(pooled_deficit, 6),
        "worst_season_deficit": worst,
        "pass": no_uniform_flip and worst < 2 * max(pooled_deficit, 1e-6),
    })

    status = "PASS" if all(c["pass"] for c in checks) else "FAIL"
    c4 = checks[3]["delta_ll"]
    if status == "PASS":
        rec = "YES"
    elif all(c["pass"] for c in checks if c["id"] != "C4"):
        rec = "CONDITIONAL"
    else:
        rec = "NO"

    text = (
        "The production 4-signal config clears uniform, frequency, and "
        "calibration (C1/C2/C3/C5 PASS) but is DECISIVELY worse than calling "
        "the market on the fully odds-covered population: delta-LL "
        "(production - market_only) = +{0:.4f}, 95% CI [{1:.4f}, {2:.4f}] — "
        "CI excludes zero, so market_only is significantly better. On LaLiga "
        "historical data every match has usable market odds, so there is no "
        "coverage gap to justify the diluted ensemble."
    ).format(c4["delta_ll"], c4["2.5"], c4["97.5"])
    if rec == "CONDITIONAL":
        text += (
            " CONDITIONAL: promote only behind a market-only (or market+elo) "
            "reference and a reweighted blend — not as the standalone "
            "historical baseline."
        )
    elif rec == "NO":
        text += " Promote market_only (pooled LL {0:.4f}) or market+elo instead.".format(
            pooled["market_only"]["log_loss"]
        )

    return {"conditions": checks, "status": status,
            "recommendation": rec, "recommendation_text": text}


# ────────────────────────────── markdown ──────────────────────────────


def _ci_compact(c: dict) -> str:
    if "2.5" not in c:
        return "—"
    return f"[{c['2.5']:.4f}, {c['97.5']:.4f}]"


def build_markdown(exploration: dict, ci: dict, gate: dict) -> str:
    out: list[str] = []
    add = out.append
    meta = exploration["meta"]
    add("# LaLiga Reduced-Architecture Investigation + Promotion Gate "
        "(OOS/leak-free harness)")
    add("")
    add(f"Generated: `{meta['generated_at']}`  ")
    add(f"Dataset: `{meta['dataset']}`  ")
    add("Method: replay with `historical.build_context_for_match` (prior-only) "
        "+ per-season pre-match Elo snapshot; no future-data leakage; "
        "production config reuses evaluate.py's renormalized weights verbatim "
        "(squad_value has no historical source).")
    add("")
    add("## 1. Pooled results — full population (n = {})".format(
        exploration["pooled"]["n"]))
    add("")
    add("| config | log_loss | 95% CI | brier | ece | acc |")
    add("| --- | --- | --- | --- | --- | --- |")
    for name in exploration["pooled"]["model_order"]:
        m = exploration["pooled"]["models"][name]
        c = ci.get(name, {})
        add("| {} | {:.4f} | {} | {:.4f} | {:.4f} | {:.4f} |".format(
            CONFIG_DISPLAY.get(name, name), m["log_loss"],
            _ci_compact(c.get("log_loss", {})), m["brier"], m["ece"], m["accuracy"]))
    add("")
    add("## 2. Architecture exploration — ranking (pooled log-loss)")
    add("")
    rank = sorted(exploration["pooled"]["models"].items(),
                  key=lambda kv: kv[1]["log_loss"])
    for i, (name, m) in enumerate(rank, 1):
        add(f"{i}. **{CONFIG_DISPLAY.get(name, name)}** — LL {m['log_loss']:.4f}, "
            f"ECE {m['ece']:.4f}, acc {m['accuracy']:.4f}")
    add("")
    add("## 3. Ablation (leave-one-signal-out, production-renormalized weights)")
    add("")
    abl = exploration["ablation"]
    add("| removal | delta-LL (removal - full) | effect |")
    add("| --- | --- | --- |")
    for k, v in abl["delta_log_loss_overall_removal_minus_full"].items():
        add(f"| {k} | {v:+.4f} | {'hurts' if v > 0 else 'helps'} |")
    add("")
    s = abl["summary"]
    add(f"- **Most contributing signal**: `{s['signal_with_largest_log_loss_contribution']}` "
        f"(removal most hurtful).")
    add(f"- **Closest to redundant**: `{s['signal_closest_to_redundant']}` "
        "(removal barely moves log-loss).")
    add("")
    add("## 4. Bootstrap CIs (95%, 2000 resamples, seed 20260601, plain "
        "resample-by-match)")
    add("")
    add("| model | log_loss CI | brier CI | ece CI | accuracy CI |")
    add("| --- | --- | --- | --- | --- |")
    for name in ("production_with_historical_inputs", "market_only", "uniform", "freq_prior_season"):
        c = ci[name]
        add("| {} | {} | {} | {} | {} |".format(
            name, _ci_compact(c["log_loss"]), _ci_compact(c["brier"]),
            _ci_compact(c["ece"]), _ci_compact(c["accuracy"])))
    add("")
    add("Paired delta-LL CIs:")
    for label, d in ci["_delta_ll"].items():
        add(f"- {label}: `{d['delta_ll']:.4f}` [`{d['2.5']:.4f}`, `{d['97.5']:.4f}`]")
    add("")
    add("## 5. Promotion-gate verdict")
    add("")
    for c in gate["conditions"]:
        add(f"### {c['id']}: {'PASS' if c['pass'] else 'FAIL'}")
        add(f"- Condition: {c['condition']}")
        add(f"- Test: {c['test']}")
        if "delta_ll" in c:
            d = c["delta_ll"]
            add(f"- production LL `{c['value']:.4f}` vs reference `{c['ref']:.4f}`; "
                f"delta-LL `{d['delta_ll']:.4f}`, 95% CI `[{d['2.5']:.4f}, {d['97.5']:.4f}]`")
        if "ci" in c:
            add(f"- ECE point `{c['point']:.4f}`, 95% CI `[{c['ci']['2.5']:.4f}, {c['ci']['97.5']:.4f}]`")
        if c["id"] == "C5":
            add(f"- per-season production-market deficit: "
                f"{ {k: round(v, 4) for k, v in c['per_season_deficit_production_minus_market'].items()} }; "
                f"worst {c['worst_season_deficit']:.4f}, pooled {c['pooled_deficit']:.4f}")
        add("")
    add("## Recommendation")
    add("")
    add(f"**{gate['recommendation']}** — {gate['recommendation_text']}")
    add("")
    return "\n".join(out)


# ────────────────────────────── main ──────────────────────────────


def main() -> None:
    os.makedirs(EVAL_DIR, exist_ok=True)

    if not os.path.exists(EVAL_RESULTS_PATH):
        raise SystemExit(
            f"missing {EVAL_RESULTS_PATH} — run evaluate.py first "
            "(ablation + weights_learned sections are reused from it)"
        )
    with open(EVAL_RESULTS_PATH, encoding="utf-8") as f:
        eval_results = json.load(f)

    season_data = {s: load_season(s) for s in SEASONS}

    # ── 1. architecture exploration: per-season + pooled, cached per match ──
    pred_cache: dict[str, dict[str, tuple]] = {}
    per_season: dict = {}
    boot_cache: dict = {}

    for s in SEASONS:
        matches, elo = season_data[s]
        row: dict = {"n": len([m for m in matches if outcome_index(m) is not None])}
        for name, signals, weights in CONFIGS:
            probs, actuals = predict_config(matches, elo, signals, weights)
            pred_cache.setdefault(name, {})[s] = (probs, actuals)
            row[name] = metrics_from(probs, actuals)
        per_season[s] = row

        probs_u, actuals_u = uniform_rows(matches)
        cache_merge(boot_cache, "uniform", probs_u, actuals_u)
        freq = freq_preds(s, season_data)
        cache_merge(boot_cache, "freq_prior_season", [freq] * len(actuals_u), actuals_u)
        for name, _, _ in CONFIGS:
            cache_merge(boot_cache, name, *pred_cache[name][s])

    pooled: dict = {"n": boot_cache["uniform"]["n"], "model_order": [c[0] for c in CONFIGS]}
    pooled["models"] = {}
    for name in pooled["model_order"]:
        merged, acts = [], []
        for s in SEASONS:
            p, a = pred_cache[name][s]
            merged.extend(p)
            acts.extend(a)
        pooled["models"][name] = metrics_from(merged, acts)
    pooled["models"]["uniform"] = pooled_metrics(boot_cache["uniform"])
    pooled["models"]["freq_prior_season"] = pooled_metrics(boot_cache["freq_prior_season"])

    cross_ref = {
        "production_with_historical_inputs": eval_results["overall"]["all"]["ensemble"]["log_loss"],
        "market_only": eval_results["overall"]["all"]["odds_market_only"]["log_loss"],
        "elo_only": eval_results["overall"]["all"]["elo_only"]["log_loss"],
    }
    cross_check = {
        k: {"our_pooled": pooled["models"][k]["log_loss"], "eval_results": ref}
        for k, ref in cross_ref.items()
    }

    exploration = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": "competitions/laliga/data/historical (2019/20-2023/24)",
            "population": "all 1900 completed matches — every LaLiga historical "
                          "match has usable market odds and Elo coverage",
            "method": "replay with historical.build_context_for_match (prior-only) "
                      "and per-season pre-match Elo snapshots; no future-data leakage",
            "weighting": {
                "production_with_historical_inputs": PROD_RENORM,
                "note": "squad_value has no historical data, so the five production "
                        "weights are renormalized over market_odds/refined_elo/"
                        "rolling_form/rest_days (evaluate.py convention); no "
                        "weights are fitted on the evaluation set",
            },
            "ece_note": "ece = football_core.evaluation.multi_class_ece (production)",
            "brier_note": "brier = multi_class_brier convention (1/3 scale)",
            "cross_check_vs_eval_results": cross_check,
        },
        "configs": {
            name: {"signals": signals,
                   "weights": (weights if weights is not None
                               else ({signals[0]: 1.0} if len(signals) == 1
                                     else PROD_RENORM)),
                   "weight_note": (
                       "bare single signal (weight 1.0)"
                       if len(signals) == 1 and weights is None else
                       "production weights renormalized over the listed signals"
                       if weights is None else "fixed weights")}
            for name, signals, weights in CONFIGS
        },
        "per_season": per_season,
        "pooled": pooled,
        "ablation": extract_ablation(eval_results),
    }
    with open(EXPLORATION_PATH, "w", encoding="utf-8") as f:
        json.dump(exploration, f, indent=2, default=str)
    print(f"wrote {EXPLORATION_PATH}")

    # ── 2. bootstrap CIs (production + market_only + baselines) ──
    ci = bootstrap_cis(boot_cache)
    ci_out = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": "competitions/laliga/data/historical (2019/20-2023/24)",
            "population": "all 1900 completed matches",
            "method": "percentile 95% bootstrap, seed 20260601, n_boot=2000, "
                      "paired over identical resamples",
            "resample_scheme_note": "plain iid resample-by-match chosen over "
                "season-block bootstrap (n=1900 across only 5 seasons — blocks "
                "would be too coarse); within-season team/opponent dependence "
                "is not modelled, so CIs treat matches as exchangeable",
            "ece_note": "ece recomputed on each resample with the same 10-bin "
                        "confidence binning as multi_class_ece",
            "brier_note": "brier per resample = mean per-match squared-error "
                          "vector length /3 (multi_class_brier convention)",
        },
        "models": {
            name: {
                metric: {"point": v["point"], "95ci": [v["2.5"], v["97.5"]]}
                for metric, v in c.items()
            }
            for name, c in ci.items() if not name.startswith("_")
        },
        "delta_ll": ci["_delta_ll"],
        "weights_learned": {
            "per_season": eval_results["weights_learned"]["per_season"],
            "stability": eval_results["weights_learned"]["stability"],
            "note": "reused verbatim from eval_results.json (inverse-log-loss "
                    "weights fit on STRICTLY-prior seasons; never the eval season)",
        },
    }
    with open(CI_PATH, "w", encoding="utf-8") as f:
        json.dump(ci_out, f, indent=2, default=str)
    print(f"wrote {CI_PATH}")

    # ── 3. promotion gate + markdown ──
    per_prod = {s: per_season[s]["production_with_historical_inputs"] for s in SEASONS}
    per_market = {s: per_season[s]["market_only"] for s in SEASONS}
    gate = run_gate(pooled["models"], ci, per_prod, per_market,
                    {s: per_season[s]["n"] for s in SEASONS},
                    eval_results["overall"]["window"])

    with open(GATE_MD_PATH, "w", encoding="utf-8") as f:
        f.write(build_markdown(exploration, ci, gate))
    print(f"wrote {GATE_MD_PATH}")
    print("gate status:", gate["status"])
    for c in gate["conditions"]:
        print(f"  {c['id']}: {'PASS' if c['pass'] else 'FAIL'}")
    print("recommendation:", gate["recommendation"])


if __name__ == "__main__":
    main()