"""Shared historical-backfill kernel for UCL and LaLiga.

Both competitions ship a ``historical_backfill/`` package that ingests completed
seasons into the same leak-free replay format (``data/historical/<season>/``
with ``matches.json`` + ``elo_ratings.json`` + ``PROVENANCE.json``) and then
evaluates them with the same harness. Only the data sources, team keys, id
scheme, dataset label and the production-weight source differ, so the *logic*
lives here once and each package is a thin wrapper supplying its own constants.

WHY per-season snapshots (the anti-leakage invariant, do not "optimise" it away):
every prediction is built by ``build_context_for_match`` (prior-only) against a
*fixed per-season* Elo snapshot taken strictly before that season's first
match, plus that season's fixtures/results. Ratings are never refreshed with
in-season outcomes, so no future data can reach a prediction. Learned weights
are inverse-log-loss fits on *strictly prior* seasons only, never on the season
being evaluated.

Layering: this module may import only from ``football_core`` (never from
``competitions/*``). Each competition's ``src.historical`` primitives are
injected through :class:`Harness`, which lets the wrappers keep their existing
import paths and call signatures unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Callable, NamedTuple

import numpy as np

from football_core.blender import EnsembleEngine, compute_log_loss_weights
from football_core.evaluation import (
    multi_class_brier,
    multi_class_ece,
    multi_class_log_loss,
)
from football_core.signals.market_odds import MarketOddsSignal
from football_core.signals.refined_elo import RefinedEloSignal
from football_core.signals.rest_days import RestDaysSignal
from football_core.signals.rolling_form import RollingFormSignal

# Provenance schema version written by every competition's build.
PROVENANCE_SCHEMA = 1


# ══════════════════════════════ contract / storage ══════════════════════════════


def year_key(season: str) -> int:
    return int(season.split("_")[0])


def season_dir(historical_dir: str, season: str) -> str:
    return os.path.join(historical_dir, season)


def season_path(historical_dir: str, season: str, name: str) -> str:
    return os.path.join(historical_dir, season, name)


def write_json(path: str, data: Any) -> str:
    """Atomically write JSON and return a content hash of the file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def duplicate_keys(matches: list[dict]) -> list[str]:
    """match_ids appearing more than once, preserving first-seen order."""
    seen: dict[str, int] = {}
    for m in matches:
        mid = m.get("match_id")
        if mid is not None:
            seen[mid] = seen.get(mid, 0) + 1
    return [mid for mid, count in seen.items() if count > 1]


# ══════════════════════════════ team-key resolution ══════════════════════════════

# Character folds applied after NFKD decomposition (other marks are removed
# by the decomposition itself; these code points do not decompose).
_SPECIAL_FOLDS: dict[str, str] = {
    "ß": "ss", "ø": "o", "æ": "ae", "œ": "oe",
    "ł": "l", "đ": "d", "ı": "i",
}
_TAG_RE = re.compile(r"\s*\([a-z]{3}\)\s*$")
_WS_RE = re.compile(r"\s+")


def _plain(text: str) -> str:
    return text.strip().lower()


def _normalize(text: str) -> str:
    s = text.strip().lower()
    s = _TAG_RE.sub("", s)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for src, dst in _SPECIAL_FOLDS.items():
        s = s.replace(src, dst)
    return _WS_RE.sub(" ", s).strip()


class TeamKeys:
    """Canonical team-key resolver for one competition.

    ``canonical()`` maps ANY source spelling to a single canonical key via
    ``data/team_aliases.json`` (case-insensitive reverse lookup), then an
    explicit curated table, then a normalisation fallback (country tag
    stripped, diacritics folded). Unmappable input raises :class:`KeyError`;
    callers catch it and fail loudly because unmapped teams are data errors.
    Tables are built once, pure and deterministic, at construction time.
    """

    __slots__ = ("ALIAS_REV", "CURATED_REV", "CANONICAL_KEYS", "NORM_REV",
                 "canonical_map")

    def __init__(self, aliases_file: str, curated: dict[str, str],
                 added_canonical_keys: tuple[str, ...] = (),
                 long_form: dict[str, str] | None = None) -> None:
        long_form = long_form or {}
        with open(aliases_file, encoding="utf-8") as f:
            raw = json.load(f)

        def prefer(orig: str, keys: list[str]) -> str:
            # An ambiguous alias resolves to its explicitly pinned long-form
            # production key when that key is a candidate; otherwise the
            # longest candidate (the production spelling) wins.
            pinned = long_form.get(orig)
            if pinned is not None and pinned in keys:
                return pinned
            return max(keys, key=len)

        alias_to_keys: dict[str, list[str]] = {}
        for canon in raw:
            # Identity: a canonical key is always a resolvable spelling of
            # itself, so the reverse lookup is direction-consistent even when
            # alias lists are asymmetric.
            alias_to_keys.setdefault(_plain(canon), []).append(canon)
            for alias in raw[canon]:
                alias_to_keys.setdefault(_plain(alias), []).append(canon)

        self.ALIAS_REV: dict[str, str] = {}
        for canon in raw:
            for alias in raw[canon]:
                self.ALIAS_REV[_plain(alias)] = prefer(alias, alias_to_keys[_plain(alias)])
            self.ALIAS_REV[_plain(canon)] = prefer(canon, alias_to_keys[_plain(canon)])

        self.CURATED_REV: dict[str, str] = {
            _plain(source): canon for source, canon in curated.items()
        }

        canonical_set: set[str] = set(self.ALIAS_REV.values()) | set(raw) | set(
            added_canonical_keys
        )
        self.CANONICAL_KEYS: list[str] = sorted(canonical_set)

        self.NORM_REV: dict[str, str] = {}
        for canon in self.CANONICAL_KEYS:
            self.NORM_REV.setdefault(_normalize(canon), canon)
        for canon in raw:
            for alias in raw[canon]:
                self.NORM_REV.setdefault(
                    _normalize(alias), prefer(alias, alias_to_keys[_plain(alias)])
                )
        for source, canon in curated.items():
            self.NORM_REV.setdefault(_normalize(source), canon)

        # Full source-name -> canonical table for provenance / reporting. Order
        # is stable: json aliases (in file order), then curated spellings, then
        # every canonical key itself.
        self.canonical_map: dict[str, str] = {}
        for canon in raw:
            for alias in raw[canon]:
                self.canonical_map[alias] = self.canonical(alias)
        for source, canon in curated.items():
            self.canonical_map[source] = canon
        for key in self.CANONICAL_KEYS:
            self.canonical_map[key] = self.canonical(key)

    def resolve(self, team: str) -> str | None:
        plain = _plain(team)
        if not plain:
            return None
        key = self.ALIAS_REV.get(plain)
        if key is not None:
            return key
        key = self.CURATED_REV.get(plain)
        if key is not None:
            return key
        norm = _normalize(team)
        if not norm:
            return None
        return self.NORM_REV.get(norm)

    def canonical(self, team: str) -> str:
        """Map an arbitrary source team spelling to its canonical key.

        Raises :class:`KeyError` if the team cannot be resolved.
        """
        if not isinstance(team, str) or not team.strip():
            raise KeyError(f"cannot canonicalise empty team key: {team!r}")
        key = self.resolve(team)
        if key is None:
            raise KeyError(f"unmapped team key: {team!r}")
        return key

    def is_known(self, team: str) -> bool:
        """True when *team* resolves to a canonical key (never raises)."""
        try:
            self.canonical(team)
        except KeyError:
            return False
        return True


# ══════════════════════════════ leak-free primitives ══════════════════════════════


class Harness(NamedTuple):
    """Competition-supplied leak-free replay primitives.

    ``competitions.<x>.src.historical`` owns these; they are injected so this
    module stays inside ``football_core`` layering. LaLiga re-exports the UCL
    implementations read-only, so both competitions share one audited set.
    """

    build_context: Callable[..., Any]        # build_context_for_match(m, matches, elo_ratings=elo)
    outcome_index: Callable[[dict], "int | None"]
    order_matches: Callable[[list[dict]], list[dict]]
    frequency_baseline: Callable[[list[dict]], dict[str, float]]
    replay_provider: Callable[..., Any]      # ReplayResultProvider
    load_replay_matches: Callable[[str], list[dict]]


def load_season(historical_dir: str, season: str, load_replay_matches) -> tuple[list[dict], dict[str, float]]:
    """Season matches + that season's frozen pre-match Elo snapshot."""
    matches = load_replay_matches(os.path.join(historical_dir, season, "matches.json"))
    with open(os.path.join(historical_dir, season, "elo_ratings.json")) as f:
        elo: dict[str, float] = json.load(f)
    return matches, elo


def renormalize(weights: dict[str, float], subset: list[str]) -> dict[str, float]:
    active = {s: w for s, w in weights.items() if s in subset and w > 0}
    total = sum(active.values())
    if total <= 0:
        return {}
    return {s: w / total for s, w in active.items()}


def signal_output(name: str, match: dict, ctx, season_matches: list[dict], harness: Harness):
    if name == "market_odds":
        return MarketOddsSignal().predict(match, ctx)
    if name == "refined_elo":
        return RefinedEloSignal().predict(match, ctx)
    if name == "rest_days":
        return RestDaysSignal().predict(match, ctx)
    if name == "rolling_form":
        return RollingFormSignal(
            result_provider=harness.replay_provider(harness.order_matches(season_matches))
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


def completed_indices(matches: list[dict], outcome_index) -> tuple[list[list[float]], list[int], list[dict]]:
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


def uniform_metrics(matches: list[dict], outcome_index) -> dict | None:
    probs, actuals, _ = completed_indices(matches, outcome_index)
    if not actuals:
        return None
    return {"uniform_log_loss": metrics_from(probs, actuals)["log_loss"],
            "uniform_brier": metrics_from(probs, actuals)["brier"],
            "n": len(actuals)}


def eval_config(matches: list[dict], elo: dict[str, float], engine: EnsembleEngine,
                harness: Harness) -> dict | None:
    probs: list[list[float]] = []
    actuals: list[int] = []
    for m in matches:
        idx = harness.outcome_index(m)
        if idx is None:
            continue
        ctx = harness.build_context(m, matches, elo_ratings=elo)
        bp = engine.evaluate(m, ctx)
        probs.append([bp.home_prob, bp.draw_prob, bp.away_prob])
        actuals.append(idx)
    if not actuals:
        return None
    return metrics_from(probs, actuals)


def signal_metrics(matches: list[dict], elo: dict[str, float], name: str,
                   harness: Harness) -> dict | None:
    probs: list[list[float]] = []
    actuals: list[int] = []
    for m in matches:
        idx = harness.outcome_index(m)
        if idx is None:
            continue
        ctx = harness.build_context(m, matches, elo_ratings=elo)
        out = signal_output(name, m, ctx, matches, harness)
        probs.append([out.home_prob, out.draw_prob, out.away_prob])
        actuals.append(idx)
    if not actuals:
        return None
    return metrics_from(probs, actuals)


def freq_metrics_on(freqs: dict[str, float], matches: list[dict], outcome_index) -> dict | None:
    probs, actuals, _ = completed_indices(matches, outcome_index)
    if not actuals:
        return None
    probs = [[freqs["home"], freqs["draw"], freqs["away"]]] * len(actuals)
    return metrics_from(probs, actuals)


def has_odds(m: dict) -> bool:
    return all(m.get(k) is not None for k in ("odds_home", "odds_draw", "odds_away"))


def first_date(matches: list[dict]) -> str:
    return min((m.get("event_date") or "") for m in matches)


def run_evaluation(out_path: str, historical_dir: str, seasons: list[str],
                   signal_order: list[str], prod_raw: dict[str, float],
                   dataset: str, harness: Harness) -> dict:
    """The full leak-free evaluation pass; writes ``out_path`` and returns it.

    Read-only with respect to the dataset: nothing under ``data/`` is modified.
    See the module docstring for the anti-leakage invariants this encodes.
    """
    out_dir = os.path.dirname(out_path)
    os.makedirs(out_dir, exist_ok=True)
    season_data = {s: load_season(historical_dir, s, harness.load_replay_matches)
                   for s in seasons}
    prod_renorm = renormalize(prod_raw, signal_order)

    results: dict = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dataset": dataset,
            "weights": {
                "production_raw": prod_raw,
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
    for s in seasons:
        matches, elo = season_data[s]
        provider = harness.replay_provider(harness.order_matches(matches))
        odds_matches = [m for m in matches if has_odds(m)]
        elo_matches = [m for m in matches if m.get("team_a") in elo and m.get("team_b") in elo]
        ref_engine = build_engine(signal_order, prod_renorm, provider)

        full_all = eval_config(matches, elo, ref_engine, harness)
        full_odds = eval_config(odds_matches, elo, ref_engine, harness) if odds_matches else None
        full_covered = eval_config(elo_matches, elo, ref_engine, harness) if elo_matches else None

        um = uniform_metrics(matches, harness.outcome_index)
        elo_only = signal_metrics(matches, elo, "refined_elo", harness)
        elo_only_covered = (signal_metrics(elo_matches, elo, "refined_elo", harness)
                            if elo_matches else None)
        market_only = (signal_metrics(odds_matches, elo, "market_odds", harness)
                       if odds_matches else None)

        # within-season chronological 70/30 window → freq baseline OOS
        ord_m = harness.order_matches(matches)
        split_at = max(1, int(round(len(ord_m) * 0.7)))
        fit_m, oos_m = ord_m[:split_at], ord_m[split_at:]
        freq = harness.frequency_baseline(fit_m)
        window = {
            "n_fit": len(fit_m),
            "n_eval": len(oos_m),
            "freq_dist": freq,
            "ensemble": eval_config(oos_m, elo, ref_engine, harness),
            "elo_only": signal_metrics(oos_m, elo, "refined_elo", harness),
            "freq": freq_metrics_on(freq, oos_m, harness.outcome_index),
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
        ens_odds_probs: list[list[float]] = []
        mkt_odds_probs: list[list[float]] = []
        odds_actuals: list[int] = []
        for s in seasons:
            matches, elo = season_data[s]
            eng = build_engine(signal_order, prod_renorm,
                               harness.replay_provider(harness.order_matches(matches)))
            for m in matches:
                if not match_filter(m, s, elo):
                    continue
                idx = harness.outcome_index(m)
                if idx is None:
                    continue
                ctx = harness.build_context(m, matches, elo_ratings=elo)
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
    ord_pool = harness.order_matches([m for s in seasons for m in season_data[s][0]])
    psplit = max(1, int(round(len(ord_pool) * 0.7)))
    pfit, poos = ord_pool[:psplit], ord_pool[psplit:]
    pfreq = harness.frequency_baseline(pfit)
    win = run_pool(lambda m, s, elo: id(m) in {id(x) for x in poos})
    overall["window"] = {
        "n_fit": len(pfit),
        "n_eval": len(poos),
        "freq_dist": pfreq,
        "ensemble": win["ensemble"],
        "elo_only": win["elo_only"],
        "uniform": win["uniform"],
        "freq": freq_metrics_on(pfreq, poos, harness.outcome_index),
    }
    results["overall"] = overall

    # ─────────────────────── leave-one-signal-out ───────────────────────
    configs = {
        "full": signal_order,
        "without_elo": [x for x in signal_order if x != "refined_elo"],
        "without_odds": [x for x in signal_order if x != "market_odds"],
        "without_form": [x for x in signal_order if x != "rolling_form"],
        "without_rest": [x for x in signal_order if x != "rest_days"],
    }
    for s in seasons:
        matches, elo = season_data[s]
        provider = harness.replay_provider(harness.order_matches(matches))
        row: dict = {"n": len(matches)}
        for cfg, sigs in configs.items():
            eng = build_engine(sigs, prod_renorm, provider)
            row[cfg] = eval_config(matches, elo, eng, harness)
        results["ablation"][s] = row

    pooled_abl: dict = {"n": len([m for s in seasons for m in season_data[s][0]])}
    for cfg, sigs in configs.items():
        probs_, actuals_ = [], []
        for s in seasons:
            matches, elo = season_data[s]
            eng = build_engine(sigs, prod_renorm,
                               harness.replay_provider(harness.order_matches(matches)))
            for m in matches:
                idx = harness.outcome_index(m)
                if idx is None:
                    continue
                ctx = harness.build_context(m, matches, elo_ratings=elo)
                bp = eng.evaluate(m, ctx)
                probs_.append([bp.home_prob, bp.draw_prob, bp.away_prob])
                actuals_.append(idx)
        if actuals_:
            pooled_abl[cfg] = metrics_from(probs_, actuals_)
    results["ablation"]["overall"] = pooled_abl

    # ─────────────────── learned weights by training window ───────────────────
    # Fitted on STRICTLY-prior seasons only — never on the season being
    # evaluated (that would be weight tuning on the eval set).
    learned: dict = {}
    for i, target in enumerate(seasons[1:], start=1):
        prior: list[tuple[list[dict], dict[str, float]]] = []
        for prev in seasons[:i]:
            pm, pe = season_data[prev]
            prior.append((pm, pe))

        # per-signal log-loss over the strictly-prior training pool
        sig_probs = {n: {"probs": [], "actuals": []} for n in signal_order}
        for pm, pe in prior:
            for m in pm:
                idx = harness.outcome_index(m)
                if idx is None:
                    continue
                ctx = harness.build_context(m, pm, elo_ratings=pe)
                for n in signal_order:
                    out = signal_output(n, m, ctx, pm, harness)
                    sig_probs[n]["probs"].append([out.home_prob, out.draw_prob, out.away_prob])
                    sig_probs[n]["actuals"].append(idx)
        sig_ll: dict[str, float] = {}
        for n in signal_order:
            data = sig_probs[n]
            if len(data["probs"]) >= 20:
                sig_ll[n] = round(multi_class_log_loss(data["probs"], data["actuals"]), 6)
        wts = compute_log_loss_weights(sig_ll) if sig_ll else {}

        tmatches, telo = season_data[target]
        eng = build_engine(signal_order, wts,
                           harness.replay_provider(harness.order_matches(tmatches)))
        ev = eval_config(tmatches, telo, eng, harness)
        ev["weights_source"] = f"train:{'+'.join(seasons[:i])} -> eval:{target}"
        learned[target] = {
            "train_pool_n": sum(len(p) for p, _ in prior),
            "signals_used": list(sig_ll.keys()),
            "per_signal_train_log_loss": sig_ll,
            "weights": wts,
            "evaluation": ev,
        }

    # stability across windows + vs production
    stability: dict = {"per_signal_min_max": {}, "window_to_window_shift": {}, "vs_production": {}}
    for n in signal_order:
        vals = [learned[s]["weights"].get(n, 0.0) for s in seasons[1:]]
        if vals:
            stability["per_signal_min_max"][n] = {
                "min": min(vals), "max": max(vals),
                "spread": round(max(vals) - min(vals), 6),
            }
    prev_w = None
    for s in seasons[1:]:
        cur_w = learned[s]["weights"]
        if prev_w is not None:
            allk = sorted(set(prev_w) | set(cur_w))
            stability["window_to_window_shift"][s] = {
                k: round(cur_w.get(k, 0.0) - prev_w.get(k, 0.0), 6) for k in allk
            }
        prev_w = cur_w
    # correlation of final-window weights with production renormalized
    final_w = learned[seasons[-1]]["weights"]
    keys = [k for k in signal_order if k in final_w or k in prod_renorm]
    if len(keys) >= 2:
        a = [final_w.get(k, 0.0) for k in keys]
        b = [prod_renorm.get(k, 0.0) for k in keys]
        mean_a, mean_b = sum(a) / len(a), sum(b) / len(b)
        num = sum((x - mean_a) * (y - mean_b) for x, y in zip(a, b))
        den = (sum((x - mean_a) ** 2 for x in a) * sum((y - mean_b) ** 2 for y in b)) ** 0.5
        stability["vs_production"]["pearson"] = round(num / den, 4) if den else None
    results["weights_learned"]["stability"] = stability
    results["weights_learned"]["per_season"] = learned

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"wrote {out_path}")
    return results


# ══════════════════════════════ build-time checks ══════════════════════════════


def validate_season(season: str, matches: list[dict], elo_map: dict[str, float]) -> dict:
    dup = duplicate_keys(matches)
    used_keys: set[str] = set()
    for m in matches:
        used_keys.add(m["team_a"])
        used_keys.add(m["team_b"])
    missing_elo = sorted(k for k in used_keys if k not in elo_map)
    return {
        "season": season,
        "n_matches": len(matches),
        "duplicate_match_ids": dup,
        "n_teams": len(used_keys),
        "elo_missing_teams": missing_elo,
        "n_odds": sum(
            1
            for m in matches
            if None not in (m.get("odds_home"), m.get("odds_draw"), m.get("odds_away"))
        ),
        "min_date": min(m["event_date"] for m in matches),
        "max_date": max(m["event_date"] for m in matches),
    }


def assert_season_clean(season: str, check: dict) -> None:
    """Fail on duplicate ids; warn (never fail) on missing Elo contributors."""
    if check["duplicate_match_ids"]:
        raise AssertionError(f"{season}: duplicate match ids {check['duplicate_match_ids']}")
    if check["elo_missing_teams"]:
        print(
            f"WARNING {season}: no ClubElo contributor for "
            f"{check['elo_missing_teams']} — recorded in PROVENANCE "
            "(RefinedEloSignal falls back to DEFAULT_ELO for these, "
            "matching production semantics); coverage maintained for the "
            "other participants"
        )


def used_elo_map(elo_map: dict[str, float], matches: list[dict]) -> dict[str, float]:
    """Trim the snapshot to the season's participants, in stable key order."""
    used_keys = {m["team_a"] for m in matches} | {m["team_b"] for m in matches}
    return {k: elo_map[k] for k in sorted(used_keys) if k in elo_map}


def write_season_dataset(historical_dir: str, season: str, label: str,
                         ordered: list[dict], elo_map_used: dict[str, float],
                         check: dict, sources: dict) -> dict:
    """Write matches.json / elo_ratings.json / PROVENANCE.json; return file hashes."""
    prov = {
        "schema": PROVENANCE_SCHEMA,
        "season": label,
        "storage_deviation": (
            "stored under data/historical instead of the approved "
            "data/seasons path because that path is the gitignored "
            "runtime season store"
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": check,
        "files": {
            "matches": write_json(
                season_path(historical_dir, season, "matches.json"),
                {"schema": PROVENANCE_SCHEMA, "season": label, "matches": ordered},
            ),
            "elo_ratings": write_json(
                season_path(historical_dir, season, "elo_ratings.json"), elo_map_used
            ),
        },
        "sources": sources,
    }
    write_json(season_path(historical_dir, season, "PROVENANCE.json"), prov)
    return prov["files"]


def summarize_replay(replay_matches: list[dict]) -> dict:
    total = len(replay_matches)
    total_odds = sum(
        1
        for m in replay_matches
        if None not in (m.get("odds_home"), m.get("odds_draw"), m.get("odds_away"))
    )
    return {
        "n_matches": total,
        "n_matches_with_odds": total_odds,
        "odds_coverage": round(total_odds / total, 4) if total else None,
    }


# ══════════════════════════ ClubElo snapshot adapter ══════════════════════════


def load_elo_frame(path: str):
    """ClubElo archive mirror -> tidy (club, elo, normalised date) frame."""
    import pandas as pd

    df = pd.read_csv(path, dtype={"club": str}, parse_dates=["date"])
    df["date"] = df["date"].dt.normalize()
    df = df.dropna(subset=["club", "elo"])
    df["club"] = df["club"].astype(str).str.strip()
    df["elo"] = df["elo"].astype(float)
    return df


def elo_snapshots(frame, seasons, first_match: Callable[[str], Any],
                  resolve: Callable[[str], "str | None"]):
    """``season -> {canonical team key: elo}`` snapshots, one per backfill season.

    The snapshot date is the latest ClubElo date STRICTLY before that season's
    first match, so the ratings are pre-match for every match of the season
    (the anti-leakage invariant). Clubs that do not resolve to a canonical key
    are logged, not raised — the archive holds thousands of non-participating
    clubs; build.py trims to the teams the fixtures actually use.

    Returns ``(snapshots, sorted_unresolved_club_names)``.
    """
    import pandas as pd

    all_dates = frame["date"].unique()
    snapshots: dict[str, dict[str, float]] = {}
    unresolved: list[str] = []

    print("season     first_match  snapshot      n_clubs  n_mapped  n_unresolved")

    for season in seasons:
        first = first_match(season)
        first_ts = pd.Timestamp(first)
        prior = all_dates[all_dates < first_ts]
        if prior.size == 0:
            raise RuntimeError(
                f"{season}: no ClubElo date strictly before {first}"
            )
        snapshot_ts = pd.Timestamp(prior.max())
        snapshot_date = snapshot_ts.date()

        rows = frame[frame["date"] == snapshot_ts]
        per_club = rows[["club", "elo"]].drop_duplicates(subset="club")
        per_club["key"] = per_club["club"].map(resolve)

        unres = set(per_club.loc[per_club["key"].isna(), "club"])
        resolved = per_club.dropna(subset=["key"])
        mapped = dict(
            resolved.drop_duplicates(subset="key", keep="first")[["key", "elo"]].to_numpy()
        )

        n_clubs = int(per_club["club"].nunique())
        n_unresolved = len(unres)
        n_mapped = n_clubs - n_unresolved
        unresolved.extend(sorted(unres))
        snapshots[season] = {k: float(v) for k, v in mapped.items()}

        print(
            f"{season:<10} {first.isoformat()}  {snapshot_date.isoformat()}  "
            f"{n_clubs:>7d}  {n_mapped:>7d}  {n_unresolved:>11d}"
        )
        print(f"    -> {len(mapped)} canonical teams in snapshot")

    return snapshots, sorted(set(unresolved))


# ══════════════════════════ bootstrap CI primitives ══════════════════════════


def per_match(probs, actuals) -> dict:
    """Per-match log-loss / brier / confidence / hit arrays for resampling."""
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


def cache_merge(cache: dict, name: str, probs, actuals) -> None:
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


def ece_points(conf, hit, n_bins: int = 10) -> float:
    """Confidence-vs-accuracy ECE on the same 10-bin convention as
    ``football_core.evaluation.multi_class_ece``."""
    ece = 0.0
    for b in range(n_bins):
        lo, hi = b / n_bins, (b + 1) / n_bins
        mask = ((conf >= lo) & (conf < hi)) | ((b == n_bins - 1) & (conf == 1.0))
        cnt = int(mask.sum())
        if cnt == 0:
            continue
        ece += (cnt / conf.size) * abs(float(conf[mask].mean()) - float(hit[mask].sum() / cnt))
    return ece
