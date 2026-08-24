"""Compute pipeline — extracted from web.wc_app for reuse and testability.

Phase 1 of the architectural refactoring extracts 7 functions from
``web/wc_app.py`` into this pipeline module. Each function is self-contained
(receives all dependencies as parameters, no module-level globals).

Phase 2 will extract ``compute_signal_eval``, ``compute_full_bracket``, etc.
Phase 3 moved ``_build_engine_from_caches`` (renamed to ``build_engine_from_caches``)
into ``src.engine`` and ``compute_team_strengths_from_predictions`` into ``src.evaluation``.
``web.engine_helpers`` was deleted.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from src import constants
from src.constants import (
    ODDS_CACHE_FILE,
    REST_DAYS_CACHE_FILE,
    ROLLING_FORM_CACHE_FILE,
    SQUAD_VALUE_CACHE_FILE,
)
from src.knockout import run_full_simulation, resolve_knockout_slot_teams
from src.state import (
    load_annex_c,
    load_groups,
    save_signal_cache,
)
from football_core.signal import PredictionContext  # type: ignore[import-untyped]

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────


# Surviving ensemble signal keys (canonical roster).
SURVIVING_SIGNALS = ("elo", "market_odds", "rolling_form", "squad_value", "rest_days")


def build_blend_params(engine_predictions: list, all_matches: list[dict], engine) -> dict:
    """Build the simulation blend payload from canonical EnsembleEngine output.

    This is the single blending path: EnsembleEngine blended probabilities
    become per-match win probabilities for the Monte Carlo simulation.
    """
    match_probs: dict[str, float] = {}
    for bp, m in zip(engine_predictions, all_matches):
        mid = m.get("match_id", "")
        if mid:
            match_probs[mid] = bp.home_prob
    return {
        "match_probs": match_probs,
        "blend_weights": dict(engine.weights),
    }


# ── Function 1: fetch_live_data ──────────────────────────────────────────


def fetch_live_data(
    bsd_api_key: str,
    football_data_org_key: str,
    data_dir: Path,
) -> None:
    """Fetch live match data + signal caches from the configured provider.

    Match results flow through the provider selected by ``DATA_PROVIDER`` env var
    (or auto-detected from available API keys). BSD-dependent signals are still
    fetched via BSD API when the key is present; they degrade gracefully when
    unavailable (see Phase 4 of the provider-swap plan).
    """
    from web.common import get_data_provider
    provider = get_data_provider(bsd_api_key, football_data_org_key, constants.DEFAULT_LEAGUE_ID)
    if provider is None:
        logger.warning("fetch_live_data: no data provider configured, skipping")
        return

    try:
        teams = json.loads((data_dir / "teams.json").read_text(encoding="utf-8"))
        groups = json.loads((data_dir / "groups.json").read_text(encoding="utf-8"))
        bracket_raw = json.loads(
            (data_dir / "bracket.json").read_text(encoding="utf-8")
        )
        aliases = json.loads(
            (data_dir / "team_aliases.json").read_text(encoding="utf-8")
        )
    except Exception as e:
        logger.warning("fetch_live_data: failed to load data files: %s", e)
        return

    # 1. Fetch and process match results via provider
    try:
        from src.fetcher import process_group_matches, process_matches

        raw_matches = provider.fetch_matches(competition_id="WC")
        if not raw_matches:
            logger.warning("fetch_live_data: provider returned no matches")
            return

        played_groups_path = data_dir / "played_groups.json"
        played_groups = (
            json.loads(played_groups_path.read_text(encoding="utf-8"))
            if played_groups_path.exists()
            else {}
        )
        played_group_ids = set(played_groups.keys())
        new_grp = process_group_matches(
            raw_matches, teams, groups, aliases, played_group_ids, set()
        )
        for m in new_grp:
            played_groups[m["match_id"]] = m
        played_groups_path.write_text(
            json.dumps(played_groups, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        annex_c = load_annex_c(data_dir)
        played_path = data_dir / "played.json"
        played = (
            json.loads(played_path.read_text(encoding="utf-8"))
            if played_path.exists()
            else {}
        )

        # Multi-pass: resolve, match, save — repeat up to 3 times.
        # Downstream bracket slots (SF, TPP, FINAL) depend on winners
        # from earlier rounds, which only become known after each pass.
        for _ in range(3):
            known_winners = {
                mid: d["winner"] for mid, d in played.items() if d.get("winner")
            }
            slot_teams = resolve_knockout_slot_teams(
                groups,
                teams,
                played_groups,
                bracket_raw,
                annex_c,
                known_winners,
            )
            resolved_bracket = [
                {"match_id": mid, "team_a": st["team_a"], "team_b": st["team_b"]}
                for mid, st in slot_teams.items()
                if st.get("team_a") and st.get("team_b")
            ]
            played_ids = set(played.keys())
            new_ko = process_matches(
                raw_matches, teams, resolved_bracket, aliases, played_ids
            )
            if not new_ko:
                break
            for m in new_ko:
                played[m["match_id"]] = m
            played_path.write_text(
                json.dumps(played, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception as e:
        logger.warning("fetch_live_data: match fetch failed: %s", e)

    # 2. Fetch and cache signal predictors
    #    BSD-dependent signals degrade gracefully (Phase 4) when BSD_API_KEY
    #    is missing or the network blocks sports.bzzoiro.com.
    try:
        from src.predictors.odds import fetch_and_cache_odds
        from src.predictors.rest_days import compute_rest_days_signal
        from src.predictors.rolling_form import compute_rolling_form_signal
        from src.predictors.squad_value import compute_squad_value_signal

        odds_cache = fetch_and_cache_odds(
            bsd_api_key, raw_matches, aliases, groups, bracket=bracket_raw
        )
        save_signal_cache(odds_cache, ODDS_CACHE_FILE, data_dir)

        rolling_form_cache = compute_rolling_form_signal(
            teams, groups, bracket=bracket_raw
        )
        save_signal_cache(
            rolling_form_cache, ROLLING_FORM_CACHE_FILE, data_dir
        )

        squad_value_cache = compute_squad_value_signal(
            groups, bracket=bracket_raw
        )
        save_signal_cache(squad_value_cache, SQUAD_VALUE_CACHE_FILE, data_dir)

        rest_days_cache = compute_rest_days_signal(
            groups, bracket=bracket_raw
        )
        save_signal_cache(rest_days_cache, REST_DAYS_CACHE_FILE, data_dir)
    except Exception as e:
        logger.warning("fetch_live_data: signal fetch failed: %s", e)


# ── Function 2: build_chronological_matches ──────────────────────────────


def build_chronological_matches(data_dir: Path) -> dict:
    """Build chronological match listing grouped by round.

    Returns: {rounds: [{round_name, round_type, matches}]}
    """
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups = load_groups(data_dir, teams=teams_raw)
    groups_data = (
        groups.get("groups", groups) if isinstance(groups, dict) else groups
    )
    groups_data = groups_data if isinstance(groups_data, dict) else {}
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    played_groups_raw = (
        json.loads(
            (data_dir / "played_groups.json").read_text(encoding="utf-8")
        )
        if (data_dir / "played_groups.json").exists()
        else {}
    )
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )

    rounds: list[dict] = []

    for gk in sorted(groups_data.keys()):
        g = groups_data[gk]
        matches = []
        for m in g.get("matches", []):
            mid = m["match_id"]
            r = played_groups_raw.get(mid, {})
            matches.append(
                {
                    "match_id": mid,
                    "date": r.get("completed_at"),
                    "team_a": m["team_a"],
                    "team_b": m["team_b"],
                    "home_score": r.get("home_score"),
                    "away_score": r.get("away_score"),
                    "winner": r.get("winner"),
                    "played": mid in played_groups_raw,
                    "status": "played" if mid in played_groups_raw else "tbd",
                    "matchday": m.get("matchday"),
                }
            )
        if matches:
            rounds.append(
                {
                    "round_name": "Group " + gk,
                    "round_type": "group",
                    "matches": matches,
                }
            )

    KO_ROUND_TYPES = {
        "R32": "r32",
        "R16": "r16",
        "QF": "qf",
        "SF": "sf",
        "TPP": "tpp",
        "FINAL": "final",
    }
    ko_rounds_order = ["R32", "R16", "QF", "SF", "TPP", "FINAL"]
    for round_name in ko_rounds_order:
        matches = []
        for be in bracket_raw:
            if be.get("round") != round_name:
                continue
            mid = be["match_id"]
            r = played_raw.get(mid, {})
            matches.append(
                {
                    "match_id": mid,
                    "date": r.get("completed_at"),
                    "team_a": r.get("team_a"),
                    "team_b": r.get("team_b"),
                    "home_score": r.get("home_score"),
                    "away_score": r.get("away_score"),
                    "winner": r.get("winner"),
                    "played": mid in played_raw,
                    "status": "played" if mid in played_raw else "tbd",
                    "source_matches": be.get("source_matches"),
                }
            )
        if matches:
            rounds.append(
                {
                    "round_name": round_name,
                    "round_type": KO_ROUND_TYPES.get(round_name, "ko"),
                    "matches": matches,
                }
            )

    return {"rounds": rounds}


# ── Function 3: build_knockout_tree ──────────────────────────────────────


def build_knockout_tree(data_dir: Path) -> dict:
    """Build knockout tree structure with resolved teams for all rounds.

    Returns: {round_name: [{match_id, team_a, team_b, score, winner, played, source_matches}]}
    """
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups = load_groups(data_dir, teams=teams_raw)
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    annex_c = load_annex_c(data_dir)
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )
    played_groups_raw = (
        json.loads(
            (data_dir / "played_groups.json").read_text(encoding="utf-8")
        )
        if (data_dir / "played_groups.json").exists()
        else {}
    )

    # Lazy import to avoid circular dependency — web.wc_app is fully loaded
    # by the time this function is called at runtime.
    from web.wc_app import compute_full_bracket  # noqa: PLC0415

    fb = compute_full_bracket(
        groups, teams_raw, bracket_raw, annex_c, played_raw, played_groups_raw
    )
    return fb.get("rounds", {})


# ── Function 4: collect_downstream_matches ───────────────────────────────


def collect_downstream_matches(
    target_id: str,
    bracket_raw: list[dict],
) -> list[str]:
    """Collect all downstream matches reachable from target_id via source_matches."""
    children_of: dict[str, list[str]] = {}
    for be in bracket_raw:
        for sm in be.get("source_matches") or []:
            children_of.setdefault(sm, []).append(be["match_id"])

    downstream: list[str] = []
    queue = [target_id]
    visited: set[str] = set()
    while queue:
        mid = queue.pop(0)
        for child in children_of.get(mid, []):
            if child not in visited:
                visited.add(child)
                downstream.append(child)
                queue.append(child)
    return downstream


# ── Function 5: simulate_from_match ──────────────────────────────────────


def simulate_from_match(
    match_id: str,
    data_dir: Path,
    iterations: int = 10000,
) -> dict:
    """Run a full simulation and extract probabilities for target + downstream matches."""
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups_raw = load_groups(data_dir, teams=teams_raw)
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    annex_c = load_annex_c(data_dir)
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )
    played_groups_raw = (
        json.loads(
            (data_dir / "played_groups.json").read_text(encoding="utf-8")
        )
        if (data_dir / "played_groups.json").exists()
        else {}
    )

    # Lazy import — build_engine_from_caches lives in src.engine (consolidated from web.engine_helpers).
    from src.engine import build_engine_from_caches  # noqa: PLC0415

    engine = build_engine_from_caches()
    elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
    groups_data = (
        groups_raw.get("groups", groups_raw)
        if isinstance(groups_raw, dict)
        else groups_raw
    )
    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket_raw:
        all_matches.append(m)

    engine_predictions = []
    context = PredictionContext(
        fixtures=all_matches,
        elo_ratings=elo_ratings,
        played_results=list(played_raw.values())
        + list(played_groups_raw.values()),
    )
    for m in all_matches:
        bp = engine.evaluate(m, context)
        engine_predictions.append(bp)
    blend_params = build_blend_params(engine_predictions, all_matches, engine)

    def _noop_progress(current: int, total: int) -> None:
        pass

    sim_result = run_full_simulation(
        teams_raw,
        groups_raw,
        bracket_raw,
        annex_c,
        played_raw,
        iterations=iterations,
        played_groups=played_groups_raw,
        blend_params=blend_params,
        progress_cb=_noop_progress,
    )

    bracket_entry = None
    for be in bracket_raw:
        if be["match_id"] == match_id:
            bracket_entry = be
            break

    downstream_ids = collect_downstream_matches(match_id, bracket_raw)
    simulated: list[dict] = []
    for mid in downstream_ids:
        probs: dict[str, list[dict]] = {}
        for team_name, pdata in sim_result.items():
            for stage in ("champion", "final", "sf", "qf", "r16", "r32"):
                prob = pdata.get(stage, 0)
                if prob > 0.001:
                    probs.setdefault(stage, []).append(
                        {"name": team_name, "probability": prob}
                    )
        sorted_probs = {
            k: sorted(v, key=lambda x: x["probability"], reverse=True)[:3]
            for k, v in probs.items()
        }
        simulated.append(
            {
                "match_id": mid,
                "top_teams": sorted(
                    [
                        {"name": name, **pdata}
                        for name, pdata in sim_result.items()
                    ],
                    key=lambda t: t.get("champion", 0),
                    reverse=True,
                )[:5],
            }
        )

    target_probs: dict[str, dict[str, float]] = {}
    target_round = bracket_entry.get("round", "?") if bracket_entry else "?"
    for team_name, pdata in sim_result.items():
        target_probs[team_name] = {
            stage: pdata.get(stage, 0)
            for stage in ("champion", "final", "sf", "qf", "r16", "r32")
        }
    top_target = sorted(
        target_probs.items(),
        key=lambda x: x[1].get("champion", 0),
        reverse=True,
    )[:4]

    return {
        "match_id": match_id,
        "round": target_round,
        "predictions": [
            {"name": name, **probs}
            for name, probs in top_target
            if probs.get("champion", 0) > 0
        ],
        "downstream": simulated,
    }


# ── Function 6: run_simulation_compute ───────────────────────────────────


def run_simulation_compute(
    data_dir: Path,
    iterations: int = 50000,
    seed: int | None = None,
    weights: dict[str, float] | None = None,
    bsd_api_key: str = "",
    football_data_org_key: str = "",
    progress_cb: callable | None = None,  # noqa: UP035
) -> dict:
    """Core simulation computation — returns results dict (no side effects on cache).

    The caller (web layer) is responsible for:
    * Managing ``active_simulations`` state
    * Updating the global ``cache`` with ``overview`` + meta
    * Writing the ``snapshot`` to disk
    """
    if progress_cb is None:
        progress_cb = lambda pct, stage: None  # noqa: E731

    fetch_live_data(bsd_api_key, football_data_org_key, data_dir)

    progress_cb(0, "Loading data files...")
    teams_raw = json.loads(
        (data_dir / "teams.json").read_text(encoding="utf-8")
    )
    groups_raw = load_groups(data_dir, teams=teams_raw)
    bracket_raw = json.loads(
        (data_dir / "bracket.json").read_text(encoding="utf-8")
    )
    annex_c = load_annex_c(data_dir)
    played_raw = (
        json.loads((data_dir / "played.json").read_text(encoding="utf-8"))
        if (data_dir / "played.json").exists()
        else {}
    )
    played_groups_raw = (data_dir / "played_groups.json").read_text(
        encoding="utf-8"
    )
    played_groups = (
        json.loads(played_groups_raw) if played_groups_raw.strip() else {}
    )

    progress_cb(5, "Building prediction engine...")
    from src.engine import build_engine_from_caches  # noqa: PLC0415

    engine = build_engine_from_caches(weights=weights)

    progress_cb(10, "Computing engine predictions...")
    elo_ratings = {n: d["elo"] for n, d in teams_raw.items()}
    groups_data = (
        groups_raw.get("groups", groups_raw)
        if isinstance(groups_raw, dict)
        else groups_raw
    )
    all_matches: list[dict] = []
    for g in groups_data.values():
        for m in g.get("matches", []):
            all_matches.append(m)
    for m in bracket_raw:
        all_matches.append(m)

    # Canonical ensemble — blended match probabilities feed the simulation.
    # No silent fallback: an ensemble failure fails the simulation request.
    context = PredictionContext(
        fixtures=all_matches,
        elo_ratings=elo_ratings,
        played_results=list(played_raw.values())
        + list(played_groups.values()),
    )
    engine_predictions = [engine.evaluate(m, context) for m in all_matches]
    blend_params = build_blend_params(engine_predictions, all_matches, engine)

    progress_cb(15, "Running Monte Carlo simulation...")

    def _sim_progress(current: int, total: int) -> None:
        pct = 15 + (current / max(total, 1) * 75)
        progress_cb(pct, f"Simulating match {current} of {total}")

    sim_result = run_full_simulation(
        teams_raw,
        groups_raw,
        bracket_raw,
        annex_c,
        played_raw,
        iterations=iterations,
        seed=seed if seed is not None else int(time.time()),
        played_groups=played_groups,
        blend_params=blend_params,
        progress_cb=_sim_progress,
    )

    progress_cb(92, "Computing top team rankings...")
    top_teams = sorted(
        [
            {"name": name, **probs}
            for name, probs in sim_result.items()
        ],
        key=lambda t: t.get("champion", 0),
        reverse=True,
    )

    progress_cb(95, "Evaluating prediction accuracy...")
    # Phase 2 will move compute_signal_eval out of web.wc_app.
    from web.wc_app import compute_signal_eval  # noqa: PLC0415

    eval_metrics = compute_signal_eval(
        teams_raw,
        played_raw,
        played_groups,
        engine_predictions,
        all_matches,
    )

    progress_cb(97, "Building full bracket tree...")
    from web.wc_app import (  # noqa: PLC0415
        compute_full_bracket,
        compute_overview,
    )

    full_bracket = compute_full_bracket(
        groups_raw,
        teams_raw,
        bracket_raw,
        annex_c,
        played_raw,
        played_groups,
        engine_predictions,
    )

    # Enrich unplayed bracket matches with predicted scores from simulation
    from football_core.knockout import simulate_single_match
    _score_rng = random.Random(42)
    for _round_name, _matches in full_bracket.get("rounds", {}).items():
        for _m in _matches:
            if not _m.get("played") and _m.get("team_a") and _m.get("team_b"):
                _ta, _tb = _m["team_a"], _m["team_b"]
                if _ta in elo_ratings and _tb in elo_ratings:
                    _result = simulate_single_match(_ta, _tb, elo_ratings, _score_rng)
                    _m["predicted_score"] = {"home": _result["score_a"], "away": _result["score_b"]}

    overview = compute_overview()

    snapshot = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "iterations": iterations,
        "seed": seed,
        "weights": weights,
        "n_teams": overview.get("n_teams", 0),
        "n_played": overview.get("n_played", 0),
        "top_teams": top_teams[:20],
        "standings": overview.get("standings", []),
        "bracket": overview.get("bracket", {}),
        "signal_eval": eval_metrics,
        "signals_meta": overview.get(
            "signals_meta", {"signals": [], "n_total": 0}
        ),
        "governance": overview.get("governance", {}),
    }

    progress_cb(100, "Complete")

    return {
        "overview": overview,
        "top_teams": top_teams,
        "eval_metrics": eval_metrics,
        "full_bracket": full_bracket,
        "sim_result": sim_result,
        "snapshot": snapshot,
    }


# ── Function 7: run_calibration_compute ──────────────────────────────────


def run_calibration_compute(
    data_dir: Path,
    bsd_api_key: str = "",
    football_data_org_key: str = "",
    progress_cb: callable | None = None,  # noqa: UP035
) -> dict:
    """Fit ensemble weights by inverse log-loss on recorded prediction history.

    The single canonical weight-fitting method (football_core.compute_log_loss_weights).
    Writes competitions/worldcup/config/signal_weights.json with provenance metadata
    when enough labeled history exists; reports ``insufficient_data`` otherwise —
    never invents weights.
    """
    if progress_cb is None:
        progress_cb = lambda pct, stage: None  # noqa: E731

    import math
    from datetime import datetime, timezone

    from football_core.blender import compute_log_loss_weights

    progress_cb(10, "Loading prediction history...")
    from src.state import load_prediction_history

    history = load_prediction_history(data_dir)

    progress_cb(40, "Collecting per-signal outcomes...")
    per_signal: dict[str, list[tuple[float, float]]] = {}
    for entry in history or []:
        actual = entry.get("actual")
        signals = entry.get("signals", {})
        if actual is None or not isinstance(signals, dict):
            continue
        for sig, sv in signals.items():
            if sig not in SURVIVING_SIGNALS or not isinstance(sv, dict):
                continue
            if not sv.get("available", True):
                continue
            p = sv.get("probability")
            if p is None:
                continue
            per_signal.setdefault(sig, []).append((float(p), float(actual)))

    progress_cb(70, "Fitting weights...")
    threshold = constants.COLD_START_THRESHOLD
    eps = 1e-15
    fitted_ll: dict[str, float] = {}
    n_map: dict[str, int] = {}
    for sig in SURVIVING_SIGNALS:
        pairs = per_signal.get(sig, [])
        n_map[sig] = len(pairs)
        if len(pairs) < threshold:
            continue
        ll = 0.0
        for p, a in pairs:
            p_c = min(max(p, eps), 1 - eps)
            # Soft-label binary cross-entropy vs actual ∈ {0.0 (loss), 0.5 (draw), 1.0 (win)}
            ll += -(a * math.log(p_c) + (1 - a) * math.log(1 - p_c))
        fitted_ll[sig] = ll / len(pairs)

    if not fitted_ll:
        progress_cb(100, "Insufficient data")
        return {
            "status": "insufficient_data",
            "threshold": threshold,
            "n_matches_per_signal": n_map,
            "message": (
                f"Fewer than {threshold} labeled predictions per signal — "
                "keeping current weights (uniform fallback until real data accrues)."
            ),
        }

    weights = compute_log_loss_weights(fitted_ll)

    payload = {
        "weights": weights,
        "fitted_at": datetime.now(timezone.utc).isoformat(),
        "method": "inverse_log_loss",
        "source": "prediction_history",
        "threshold": threshold,
        "per_signal": {
            s: {"log_loss": round(fitted_ll[s], 6), "n_matches": n_map[s]}
            for s in sorted(fitted_ll)
        },
    }
    out_path = Path(__file__).resolve().parent.parent / "config" / "signal_weights.json"
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    progress_cb(100, "Complete")
    return {
        "status": "ok",
        "weights": weights,
        "weights_file": str(out_path),
        "per_signal": payload["per_signal"],
    }
