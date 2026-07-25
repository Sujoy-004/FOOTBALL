"""Simulation mode orchestrator for UCL.

Routes between simulate, replay, and live modes per D-05.
Each mode resolves played_matches from its source, then delegates
to the simulation engine which is mode-agnostic.

Extended in Phase 10 (Plan 02) to support Glicko-1 rating system
uncertainty propagation via the *rating_system* parameter.

Usage:
    from competitions.ucl.src.orchestrator import run_simulation
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from football_core.provider import FixtureSchedule

from competitions.ucl.result import SimulationResult
from competitions.ucl.src.calibrate import _EmptyResultProvider

logger = logging.getLogger(__name__)


def _get_config_dir() -> str:
    """Return absolute path to competitions/ucl/config/ directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
    )


def load_calibration() -> dict | None:
    """Load temperature calibration from config/calibration.json."""
    cal_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
        "calibration.json",
    )
    if not os.path.exists(cal_path):
        return None

    try:
        with open(cal_path) as f:
            data = json.load(f)
        result: dict = {}
        if "T" in data:
            result["T"] = float(data["T"])
        if "alpha" in data:
            result["alpha"] = float(data["alpha"])
            result.setdefault("T", 1.0 / result["alpha"])
        if "log_loss" in data and data["log_loss"] is not None:
            result["log_loss"] = float(data["log_loss"])
        if "log_loss_before" in data and data["log_loss_before"] is not None:
            result["log_loss_before"] = float(data["log_loss_before"])
        if "n_samples" in data:
            result["n_samples"] = int(data["n_samples"])
        if "ece" in data and data["ece"] is not None:
            result["ece"] = float(data["ece"])
        return result if "T" in result else None
    except (json.JSONDecodeError, KeyError, ValueError, ZeroDivisionError):
        pass

    return None


def load_cache_ttls(data_dir: str) -> dict[str, int]:
    """Load per-signal cache TTLs from config/cache_ttls.json."""
    config_path = os.path.join(data_dir, "..", "config", "cache_ttls.json")
    try:
        with open(config_path) as f:
            return dict(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return {"odds": 12, "catboost": 24}


class _ReplayResultProvider:
    """Reads UCL results.json and provides per-team results for RollingFormSignal.

    Maps the UCL results format (team_a, team_b, home_score, away_score, winner, match_id)
    to the MatchResultProvider protocol expected by RollingFormSignal.
    """

    def __init__(self, path: str) -> None:
        with open(path) as f:
            data = json.load(f)
        self._results = data if isinstance(data, list) else data.get("matches", data.get("results", []))

    def get_team_results(self, team: str, before_date: str, limit: int = 10) -> list[dict]:
        results = []
        for m in self._results:
            if m.get("team_a") == team or m.get("team_b") == team:
                if before_date and m.get("match_id", "") >= before_date:
                    continue
                is_team_a = m["team_a"] == team
                winner = m.get("winner")
                results.append({
                    "event_date": m.get("match_id", ""),
                    "is_draw": winner is None or m.get("is_draw", False),
                    "winner": winner,
                    "team_a": m["team_a"],
                    "team_b": m["team_b"],
                })
        results.sort(key=lambda r: r["event_date"], reverse=True)
        return results[:limit]


def build_signal_engine(
    elo_ratings: dict[str, float],
    weights_override: dict[str, float] | None = None,
    results_file: str | None = None,
) -> Any:
    """Build EnsembleEngine with 8 pre-configured signals and calibrated weights."""
    from football_core.blender import EnsembleEngine
    from football_core.signals.refined_elo import RefinedEloSignal
    from football_core.signals.market_odds import MarketOddsSignal
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signals.squad_value import SquadValueSignal
    from football_core.signals.rest_days import RestDaysSignal
    from football_core.signals.availability import AvailabilitySignal
    from football_core.signals.manager_effect import ManagerEffectSignal
    from football_core.signals.defensive_quality import DefensiveQualitySignal
    from football_core.signals.player_form import PlayerFormSignal
    from football_core.signals.team_synergy import TeamSynergySignal

    signals = [
        RefinedEloSignal(),
        MarketOddsSignal(),
        RollingFormSignal(
            result_provider=_ReplayResultProvider(results_file) if results_file and os.path.exists(results_file)
            else _EmptyResultProvider()
        ),
        SquadValueSignal(),
        RestDaysSignal(),
        AvailabilitySignal(),
        ManagerEffectSignal(),
        DefensiveQualitySignal(),
        PlayerFormSignal(),
        TeamSynergySignal(),
    ]

    logger.debug("Building ensemble engine with %d signals: %s",
                 len(signals), [s.name for s in signals])

    weights_path = os.path.join(
        _get_config_dir(),
        "signal_weights.json",
    )

    if weights_override is not None:
        logger.debug("Using direct weight override: %s", weights_override)
        return EnsembleEngine(signals, weights=weights_override)
    if os.path.exists(weights_path):
        logger.debug("Loading weights from: %s", weights_path)
        return EnsembleEngine(signals, weights_path=weights_path)
    logger.debug("No weights found — using uniform fallback")
    return EnsembleEngine(signals)


def build_simulation_result(
    fixtures: FixtureSchedule,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
    played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
    rating_system=None,
    progress_cb: callable | None = None,
) -> SimulationResult:
    """Run MC simulation + one representative bracket iteration, return SimulationResult."""
    fixtures_dict = {"schedule": asdict(fixtures)}

    using_glicko = rating_system is not None
    if using_glicko:
        from competitions.ucl.src.simulation import run_monte_carlo_glicko
        mc_result = run_monte_carlo_glicko(
            fixtures_dict,
            rating_system,
            n_iterations=n_iterations,
            seed=seed,
            played_matches=played_matches,
            progress_cb=progress_cb,
        )
    else:
        from competitions.ucl.src.simulation import run_monte_carlo
        mc_result = run_monte_carlo(
            fixtures_dict,
            elo_ratings=elo_ratings,
            n_iterations=n_iterations,
            seed=seed,
            played_matches=played_matches,
            progress_cb=progress_cb,
        )

    rng = random.Random(seed)
    bracket_elos = rating_system.to_elo_dict() if using_glicko else elo_ratings
    from competitions.ucl.src.simulation import simulate_league_phase
    standings = simulate_league_phase(fixtures_dict, bracket_elos, rng, played_matches=played_matches)

    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
    )
    pairings_path = os.path.join(data_dir, "playoff_pairings.json")
    bracket_path = os.path.join(data_dir, "bracket_rules.json")

    with open(pairings_path) as f:
        pairings_data = json.load(f)
    with open(bracket_path) as f:
        bracket_data = json.load(f)

    from competitions.ucl.src.knockout import (
        build_r16_bracket, simulate_playoff_round,
        simulate_knockout_tree, track_knockout_stages,
    )

    playoff_result = simulate_playoff_round(
        standings, bracket_elos, rng,
        pairings_data=pairings_data,
    )
    bracket = build_r16_bracket(
        standings, playoff_result,
        bracket_data=bracket_data,
        rng=rng,
    )
    tree_result = simulate_knockout_tree(bracket, bracket_elos, rng)
    stages = track_knockout_stages(standings, tree_result)

    return SimulationResult(
        snapshot_date=mc_result["snapshot_date"],
        n_iterations=mc_result["n_iterations"],
        seed=mc_result["seed"],
        standings=standings,
        teams=mc_result["teams"],
        playoff_ties=playoff_result["ties"],
        playoff_winners=playoff_result["winners"],
        bracket_rounds=tree_result["rounds"],
        bracket_champion=tree_result["champion"],
        stages=stages,
    )


def run_validation(
    simulation_result: SimulationResult,
    real_matches: list[dict],
    elo_ratings: dict[str, float],
) -> dict:
    """Cross-check simulation predictions against real match outcomes."""
    from football_core.evaluation import compute_metrics, calibration_curve
    from football_core.elo import expected_score

    predictions: list[float] = []
    actuals: list[float] = []
    odds_predictions: list[float] = []
    odds_actuals: list[float] = []

    for match in real_matches:
        team_a = match["team_a"]
        team_b = match["team_b"]

        home_elo = elo_ratings.get(team_a, 1500.0)
        away_elo = elo_ratings.get(team_b, 1500.0)
        pred_home_win = expected_score(home_elo, away_elo)

        if match.get("is_draw"):
            actual = 0.5
        elif match.get("winner") == team_a:
            actual = 1.0
        elif match.get("winner") == team_b:
            actual = 0.0
        else:
            continue

        predictions.append(pred_home_win)
        actuals.append(actual)

        if "odds" in match:
            odds_predictions.append(match["odds"]["home"])
            odds_actuals.append(actual)

    prediction_metrics = compute_metrics(predictions, actuals)
    calibration = calibration_curve(predictions, actuals)

    result: dict = {
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "n_matches_fetched": len(real_matches),
        "n_matches_matched": len(predictions),
        "n_odds_available": len(odds_predictions),
        "prediction_metrics": {
            "brier": round(prediction_metrics["brier"], 6),
            "log_loss": round(prediction_metrics["log_loss"], 6),
            "accuracy": round(prediction_metrics["accuracy"], 6),
            "n": prediction_metrics["n"],
        },
        "calibration": calibration,
    }

    if odds_predictions:
        odds_metrics = compute_metrics(odds_predictions, odds_actuals)
        result["market_odds_metrics"] = {
            "brier": round(odds_metrics["brier"], 6),
            "log_loss": round(odds_metrics["log_loss"], 6),
            "n": odds_metrics["n"],
        }

    return result


def resolve_played_matches(
    args,
    data_dir: str,
    fixtures_schedule: FixtureSchedule,
) -> dict[tuple[str, str], tuple[int, int]] | None:
    """Resolve played_matches based on CLI mode."""
    if args.mode == "replay":
        if not args.replay_data:
            logger.error("--replay-data PATH required for replay mode")
            sys.exit(1)
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider
        provider = ReplayMatchResultProvider(args.replay_data)
        return provider.load()

    elif args.mode == "live":
        api_key = args.api_key or os.environ.get("BSD_API_KEY")
        if not api_key:
            logger.error("BSD_API_KEY required for live mode")
            sys.exit(1)
        from competitions.ucl.src.result_provider import BSDMatchResultProvider
        team_aliases_path = os.path.join(data_dir, "team_aliases.json")
        with open(team_aliases_path) as f:
            team_aliases = json.load(f)
        provider = BSDMatchResultProvider(
            api_key, team_aliases, asdict(fixtures_schedule),
        )
        return provider.load()

    results_path = os.path.join(data_dir, "results.json")
    if os.path.exists(results_path):
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider
        provider = ReplayMatchResultProvider(results_path)
        return provider.load()

    return None


def run_simulation(
    fixtures_schedule: FixtureSchedule,
    elo_ratings: dict[str, float],
    seed: int,
    n_iterations: int,
    args,
    data_dir: str,
    rating_system=None,
) -> object:
    """Orchestrate the full simulation: resolve mode, run MC, return result."""
    played_matches = resolve_played_matches(args, data_dir, fixtures_schedule)

    return build_simulation_result(
        fixtures_schedule, elo_ratings, seed, n_iterations,
        played_matches=played_matches,
        rating_system=rating_system,
    )


def run_deterministic_compute(
    data_dir: str,
    bsd_api_key: str = "",
    football_data_org_key: str = "",
    team_aliases: dict[str, str] | None = None,
) -> dict:
    """Deterministic computation from real results — pure logic, no web globals.

    Returns dict with keys: mode, teams, all_teams, standings, playoff,
    bracket_rounds, league_matchdays, odds, signals, elo_ratings, champion,
    boot, _results, _signal_engine, n_teams, n_iterations, n_total_matches,
    seed, snapshot_date.
    """
    from competitions.ucl.src.pipeline import (
        load_results, load_knockout_results, compute_deterministic_standings,
        build_deterministic_bracket, build_league_matchdays, compute_signal_eval,
        fetch_ucl_managers,
    )
    from web.common import ts, boot_step

    boot: list[dict] = []

    def _step(name, fn):
        return boot_step(name, fn, boot)

    results = _step("Load real results", lambda: load_results(data_dir))
    if not results:
        return {"error": "results.json not found", "boot": boot}

    knockout = _step("Load knockout results", lambda: load_knockout_results(data_dir))
    if not knockout:
        return {"error": "knockout_results.json not found", "boot": boot}

    from competitions.ucl.src.provider import RepoFixtureProvider

    fixtures_path = os.path.join(data_dir, "fixtures.json")
    provider = _step("Load fixtures", lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load())
    if not provider:
        return {"error": "fixtures load failed", "boot": boot}

    team_names = [t.name for t in provider.teams]
    from competitions.ucl.src.elo_fetcher import fetch_team_elos

    elo_ratings = _step("Fetch Elo ratings", lambda: fetch_team_elos(team_names))
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot.append({"step": "Elo fallback (coefficients)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Elo fallback"})

    bsd_manager_data = _step("Fetch BSD managers", lambda: fetch_ucl_managers(bsd_api_key, team_aliases=team_aliases))
    standings = _step("Compute standings", lambda: compute_deterministic_standings(results))
    if not standings:
        return {"error": "standings computation failed", "boot": boot}

    bracket_data = _step("Build bracket", lambda: build_deterministic_bracket(knockout, standings, data_dir))

    import tempfile

    _results_tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    json.dump(results, _results_tmp)
    _results_tmp.close()
    engine = _step("Build signal engine", lambda: build_signal_engine(elo_ratings, results_file=_results_tmp.name))
    os.unlink(_results_tmp.name)

    signal_stats = _step("Evaluate signals", lambda: compute_signal_eval(results, engine, elo_ratings, bsd_manager_data))

    def _was_in_semis(t: str) -> bool:
        for m in knockout.get("rounds", {}).get("SF", []):
            if t in (m.get("team_a"), m.get("team_b")):
                return True
        return False

    def _was_in_qf(t: str) -> bool:
        for m in knockout.get("rounds", {}).get("QF", []):
            if t in (m.get("team_a"), m.get("team_b")):
                return True
        return False

    odds_display = []
    champ = knockout.get("champion", "")
    for i, entry in enumerate(standings, start=1):
        is_champ = entry["team"] == champ
        odds_display.append({
            "rank": i, "team": entry["team"],
            "champion_prob": 1.0 if is_champ else 0.0,
            "final_prob": 1.0 if is_champ else 0.0,
            "sf_prob": 1.0 if is_champ or _was_in_semis(entry["team"]) else 0.0,
            "qf_prob": 1.0 if is_champ or _was_in_qf(entry["team"]) else 0.0,
            "top_8_prob": 1.0 if entry.get("position", 99) <= 8 else 0.0,
            "playoff_prob": 1.0 if entry.get("zone") == "playoff" else 0.0,
            "avg_position": float(entry.get("position", 36)),
        })
    odds_display.sort(key=lambda x: (0 if x["team"] == champ else 1, x["rank"]))

    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]
    enriched_bracket: dict[str, list[dict]] = {}
    for round_name, matches in bracket_data.get("bracket_rounds", {}).items():
        enriched_bracket[round_name] = matches

    n_total_matches = len(results)
    n_matchdays = len({m.get("match_id", "").split("_")[0] for m in results if "_" in m.get("match_id", "")}) or 1

    return {
        "mode": "results",
        "teams": top4,
        "all_teams": odds_display,
        "n_teams": len(standings),
        "n_iterations": n_matchdays,
        "n_total_matches": n_total_matches,
        "seed": 0,
        "snapshot_date": "2025/26 Season — Real Results",
        "champion": champ,
        "standings": standings,
        "playoff": bracket_data.get("playoff", []),
        "bracket_rounds": enriched_bracket,
        "league_matchdays": build_league_matchdays(results),
        "odds": odds_display,
        "signals": signal_stats,
        "elo_ratings": elo_ratings,
        "_results": results,
        "_signal_engine": engine,
        "boot": boot,
        "bsd_manager_data": bsd_manager_data,
    }


def run_compute_all(
    data_dir: str,
    bsd_api_key: str = "",
    seed: int = 42,
    n_iterations: int = 10000,
    team_aliases: dict[str, str] | None = None,
) -> dict:
    """Compute all results or run simulation — pure logic, no web globals.

    Returns dict with keys: mode, teams, all_teams, standings, playoff,
    bracket_rounds, league_matchdays, odds, signals, elo_ratings, champion,
    boot, _results, _signal_engine, n_teams, n_iterations, n_total_matches,
    seed, snapshot_date, bsd_manager_data, calibration, show_ci.
    """
    from web.common import ts, boot_step

    boot: list[dict] = []

    def _step(name, fn):
        return boot_step(name, fn, boot)

    results_path = os.path.join(data_dir, "results.json")
    ko_path = os.path.join(data_dir, "knockout_results.json")

    use_results_mode = os.path.exists(results_path) and os.path.exists(ko_path)

    if use_results_mode:
        return run_deterministic_compute(data_dir, bsd_api_key, team_aliases=team_aliases)

    # Simulation mode
    from competitions.ucl.src.pipeline import (
        fetch_ucl_managers,
    )
    from competitions.ucl.src.provider import RepoFixtureProvider
    from competitions.ucl.src.elo_fetcher import fetch_team_elos

    fixtures_path = os.path.join(data_dir, "fixtures.json")
    provider = _step("Load fixtures", lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load())
    if not provider:
        return {"error": "fixtures load failed", "boot": boot}

    team_names = [t.name for t in provider.teams]
    elo_ratings = _step("Fetch Elo ratings", lambda: fetch_team_elos(team_names))
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot.append({"step": "Elo fallback (coefficients)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Elo fallback"})

    bsd_manager_data = _step("Fetch BSD managers", lambda: fetch_ucl_managers(bsd_api_key, team_aliases=team_aliases))

    if bsd_manager_data and elo_ratings:
        blended_count = 0
        for t in team_names:
            base = elo_ratings.get(t, 1400.0)
            mgr = bsd_manager_data.get(t)
            if mgr:
                win_pct = mgr.get("win_pct", 0.0) / 100.0
                if win_pct > 0:
                    mgr_elo = 1400.0 + (win_pct - 0.5) * 400.0
                    elo_ratings[t] = round(base * 0.7 + mgr_elo * 0.3, 1)
                    blended_count += 1
        if blended_count > 0:
            boot.append({"step": "Elo blend (BSD managers)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Blended manager win% into Elo for {blended_count} teams"})

    # Run MC simulation
    result = _step("Monte Carlo simulation", lambda: build_simulation_result(provider, elo_ratings, seed, n_iterations))
    if not result:
        return {"error": "simulation failed", "boot": boot}

    engine = _step("Build signal engine", lambda: build_signal_engine(elo_ratings))

    bracket_rules_path = os.path.join(data_dir, "bracket_rules.json")
    bracket_rules = {}
    try:
        bracket_rules = json.loads(Path(bracket_rules_path).read_text(encoding="utf-8"))
    except Exception:
        pass

    source_map = {}
    for m in bracket_rules.get("matches", []):
        if m.get("source_matches"):
            source_map[m["match_id"]] = m["source_matches"]

    enriched_bracket = {}
    for round_name, matches in result.bracket_rounds.items():
        enriched_bracket[round_name] = []
        for m in matches:
            entry = dict(m)
            if m["match_id"] in source_map:
                entry["source_matches"] = source_map[m["match_id"]]
            enriched_bracket[round_name].append(entry)

    playoff_display = []
    for tie_num in sorted(result.playoff_ties):
        tie = result.playoff_ties[tie_num]
        winner = result.playoff_winners.get(tie_num, "?")
        loser = tie.get("loser", "?")
        playoff_display.append({
            "tie_num": tie_num, "team_a": winner, "team_b": loser,
            "winner": winner, "aggregate_a": tie.get("aggregate_a", 0),
            "aggregate_b": tie.get("aggregate_b", 0),
            "et_played": tie.get("et_played", False),
            "penalties_played": tie.get("penalties_played", False),
            "et_a": tie.get("et_a", 0), "et_b": tie.get("et_b", 0),
            "penalty_a": tie.get("penalty_a", 0), "penalty_b": tie.get("penalty_b", 0),
        })

    sorted_teams = sorted(result.teams.items(), key=lambda x: (-x[1].get("champion_prob", 0.0), x[0]))
    odds_display = []
    for rank, (name, td) in enumerate(sorted_teams, start=1):
        odds_display.append({
            "rank": rank, "team": name,
            "champion_prob": td.get("champion_prob", 0.0),
            "final_prob": td.get("stage_final_prob", 0.0),
            "sf_prob": td.get("stage_sf_prob", 0.0),
            "qf_prob": td.get("stage_qf_prob", 0.0),
            "top_8_prob": td.get("top_8_prob", 0.0),
            "playoff_prob": td.get("playoff_prob", 0.0),
            "avg_position": td.get("avg_position", 0.0),
        })
    standings_display = []
    for entry in result.standings:
        zone = entry.get("zone", "eliminated")
        standings_display.append({
            "position": entry.get("position"), "team": entry.get("team"),
            "pts": entry.get("pts"), "gd": entry.get("gd"),
            "gs": entry.get("gs"), "zone": zone,
        })
    top4 = [odds_display[i] for i in range(min(4, len(odds_display)))]

    # Build signal stats
    signal_stats = {}
    try:
        signal_matches = []
        for md in provider.matchdays:
            for m in md:
                signal_matches.append({"team_a": m.team_a, "team_b": m.team_b, "match_id": m.match_id})
        signal_context = PredictionContext(
            fixtures=signal_matches, elo_ratings=elo_ratings,
            played_results=[], manager_data=bsd_manager_data,
        )
        blended = [engine.evaluate(m, signal_context) for m in signal_matches]
        sig_data = {}
        for bp in blended:
            for sig, sd in bp.signal_breakdown.items():
                if sig not in sig_data:
                    sig_data[sig] = {"probs": [], "n": 0, "available": 0}
                sig_data[sig]["n"] += 1
                if sd.get("available", True):
                    sig_data[sig]["available"] += 1
                if sd.get("weight", 0) > 0:
                    sig_data[sig]["probs"].extend([sd.get("home", 0.5), sd.get("draw", 0), sd.get("away", 0)])
        for sig, sd in sorted(sig_data.items()):
            probs = [p for p in sd["probs"] if p is not None]
            avg = sum(probs) / len(probs) if probs else 0
            signal_stats[sig] = {
                "n_matches": sd["n"], "available": sd["available"],
                "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0,
                "avg_probability": round(avg, 4),
                "weight": round(engine.weights.get(sig, 0), 4),
            }
    except Exception:
        signal_stats = {}

    calib = load_calibration()

    return {
        "mode": "simulation",
        "teams": top4,
        "all_teams": odds_display,
        "n_teams": len(result.teams),
        "n_iterations": result.n_iterations,
        "seed": result.seed,
        "snapshot_date": result.snapshot_date,
        "champion": result.bracket_champion,
        "standings": standings_display,
        "playoff": playoff_display,
        "bracket_rounds": enriched_bracket,
        "odds": odds_display,
        "signals": signal_stats,
        "elo_ratings": elo_ratings,
        "calibration": calib,
        "show_ci": "auto",
        "league_matchdays": {},
        "boot": boot,
        "_signal_engine": engine,
        "bsd_manager_data": bsd_manager_data,
    }
