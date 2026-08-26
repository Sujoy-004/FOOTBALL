"""Simulation mode orchestrator for UCL.

Routes between simulate and live/results modes. Each mode resolves
played_matches from its source, then delegates to the simulation engine
which is mode-agnostic.

Usage:
    from competitions.ucl.src.orchestrator import run_simulation
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_core.domain import DataAvailability, load_json_store
from football_core.provider import FixtureSchedule
from football_core.signal import PredictionContext

from competitions.ucl.result import SimulationResult
from competitions.ucl.src.calibrate import _EmptyResultProvider

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SimulationResultWithState(SimulationResult):
    """SimulationResult plus the canonical sim-state payload.

    The extra ``sim_state_payload`` field carries the clean Monte Carlo
    bracket snapshot shaped exactly for
    :func:`competitions.ucl.src.state.build_competition_state` with
    ``mode="simulation"``. Subclassing keeps every existing attribute
    consumer (report.py, web/ucl_app.py what-if) working unchanged.
    """

    sim_state_payload: dict = field(default_factory=dict)


def _top_champion_probs(teams: dict[str, dict]) -> dict[str, float]:
    """Champion-probability counts for the UI projected-champion banner.

    Only teams with a nonzero probability are kept; ordering is
    deterministic (probability descending, then team name) so the payload
    serialises identically across runs with the same seed.
    """
    probs = {
        name: td.get("champion_prob", 0.0)
        for name, td in (teams or {}).items()
        if td.get("champion_prob")
    }
    return {name: probs[name] for name in sorted(probs, key=lambda n: (-probs[n], n))}


def _tie_legs(tie: dict) -> list[dict] | None:
    """Normalise a two-legged tie result into canonical leg rows.

    Each row reports the ACTUAL host of that leg first: the engine plays
    leg 1 with ``team_a`` at home and leg 2 with ``team_b`` at home
    (D-03/D-05), while its raw ``leg2`` dict repeats the leg-1 ordering.
    No winner-based reordering happens anywhere.
    """
    legs = []
    for idx in (1, 2):
        leg = tie.get(f"leg{idx}")
        if not isinstance(leg, dict):
            continue
        if idx == 1:
            home, away = leg.get("team_a"), leg.get("team_b")
            home_score, away_score = leg.get("score_a"), leg.get("score_b")
        else:
            home, away = leg.get("team_b"), leg.get("team_a")
            home_score, away_score = leg.get("score_b"), leg.get("score_a")
        legs.append({
            "leg": idx,
            "home": home,
            "away": away,
            "home_score": home_score,
            "away_score": away_score,
        })
    return legs or None


def _winner_first_tie_fields(tie: dict, winner: str | None) -> dict:
    """Re-map aggregate/ET/penalty scores onto a winner-first basis.

    Engine results score from team_a's perspective (leg-1 host); display
    ties present winner as team_a, so per-side numbers swap whenever the
    leg-1 host lost.
    """
    agg_a, agg_b = tie.get("aggregate_a", 0), tie.get("aggregate_b", 0)
    full_a, full_b = tie.get("agg_a_full"), tie.get("agg_b_full")
    et_a, et_b = tie.get("et_a", 0), tie.get("et_b", 0)
    pen_a, pen_b = tie.get("penalty_a", 0), tie.get("penalty_b", 0)
    engine_team_a = (tie.get("leg1") or {}).get("team_a")
    if winner is not None and engine_team_a is not None and winner != engine_team_a:
        agg_a, agg_b = agg_b, agg_a
        full_a, full_b = full_b, full_a
        et_a, et_b = et_b, et_a
        pen_a, pen_b = pen_b, pen_a
    return {
        "aggregate_a": agg_a,
        "aggregate_b": agg_b,
        "agg_a_full": full_a if full_a is not None else agg_a,
        "agg_b_full": full_b if full_b is not None else agg_b,
        "et_played": bool(tie.get("et_played")),
        "et_a": et_a,
        "et_b": et_b,
        "penalties_played": bool(tie.get("penalties_played")),
        "penalty_a": pen_a,
        "penalty_b": pen_b,
    }


def _sim_playoff_entries(
    playoff_ties: dict[int, dict],
    playoff_winners: dict[int, str],
) -> list[dict]:
    """Flat playoff-tie entries keyed by ``tie_num`` (state.py contract)."""
    entries = []
    for tie_num in sorted(playoff_ties):
        tie = playoff_ties[tie_num]
        winner = playoff_winners.get(tie_num, tie.get("winner"))
        loser = tie.get("loser")
        entry = {
            "tie_num": tie_num,
            "team_a": winner,
            "team_b": loser,
            "winner": winner,
            "loser": loser,
        }
        entry.update(_winner_first_tie_fields(tie, winner))
        entry["legs"] = _tie_legs(tie)
        entries.append(entry)
    return entries


def _sim_bracket_entry(match: dict) -> dict:
    """One knockout-round entry in the state.py bracket contract.

    Identity fields live at top level; the raw engine result blob rides
    under ``result`` (state flattens it). The blob is copied so the
    engine-owned dicts are never mutated, and penalty attribution is made
    explicit for coherent ``played_pens`` status downstream.
    """
    result_blob = dict(match.get("result") or {})
    winner = match.get("winner")
    if result_blob.get("penalties_played") and winner:
        result_blob.setdefault("penalty_winner", winner)
    entry = {
        "match_id": match["match_id"],
        "round": match.get("round"),
        "quarter": match.get("quarter"),
        "team_a": match.get("team_a"),
        "team_b": match.get("team_b"),
        "winner": winner,
        "source_matches": match.get("source_matches"),
        # Explicit canonical legs (true per-leg hosts) so state never has
        # to re-derive them from the raw engine blob.
        "legs": _tie_legs(result_blob),
        "result": result_blob,
    }
    return entry


def _sim_final_entry(match: dict) -> dict:
    """Single-match FINAL entry (state.py ``_build_final_node`` shape)."""
    blob = match.get("result") or {}
    winner = match.get("winner")
    penalties_played = bool(blob.get("penalties_played"))
    pen_a, pen_b = blob.get("penalty_a", 0), blob.get("penalty_b", 0)
    return {
        "match_id": match["match_id"],
        "round": "FINAL",
        "team_a": match.get("team_a"),
        "team_b": match.get("team_b"),
        "winner": winner,
        "score": {"home": blob.get("score_a"), "away": blob.get("score_b")},
        "et_played": bool(blob.get("et_played")),
        "et_a": blob.get("et_a", 0),
        "et_b": blob.get("et_b", 0),
        "penalties_played": penalties_played,
        "penalty_winner": winner if penalties_played else None,
        "penalty_score": f"{pen_a}-{pen_b}" if penalties_played else None,
        "source_matches": match.get("source_matches"),
    }


def build_sim_state_payload(
    playoff_ties: dict[int, dict],
    playoff_winners: dict[int, str],
    bracket_rounds: dict[str, list[dict]],
    champion_probs: dict[str, float] | None = None,
) -> dict:
    """Assemble the clean simulation payload for the canonical state layer.

    Shaped EXACTLY for
    :func:`competitions.ucl.src.state.build_competition_state` with
    ``mode="simulation"``:

    - ``playoff``: list of flat per-tie entries (``tie_num``, teams,
      legs, aggregates, ET/penalty detail, winner);
    - ``playoff_winners``: ``{tie_number: winning team}``;
    - ``bracket_rounds``: ``{R16|QF|SF|FINAL: [entries]}`` with stable
      ``match_id`` values (from bracket_rules.json), resolved team names
      for every completed match, leg-level ``result`` blobs, and
      ``source_matches`` on QF..FINAL;
    - ``champion_probs``: optional champion-probability passthrough.

    Deterministic: same inputs produce an identical JSON serialisation.
    """
    rounds_out: dict[str, list[dict]] = {}
    for round_name in ("R16", "QF", "SF", "FINAL"):
        matches = bracket_rounds.get(round_name) or []
        if round_name == "FINAL":
            rounds_out[round_name] = [_sim_final_entry(m) for m in matches]
        else:
            rounds_out[round_name] = [_sim_bracket_entry(m) for m in matches]
    payload = {
        "playoff_winners": {
            tie_num: playoff_winners[tie_num]
            for tie_num in sorted(playoff_winners)
        },
        "playoff": _sim_playoff_entries(playoff_ties, playoff_winners),
        "bracket_rounds": rounds_out,
    }
    if champion_probs:
        payload["champion_probs"] = dict(champion_probs)
    return payload


def _resolve_elo_ratings(team_names: list[str]) -> dict[str, float]:
    """Snapshot-safe Elo resolution.

    Snapshot mode guarantees ZERO live requests, so ClubElo is skipped and
    coefficient-derived ratings are used directly. Live mode attempts the
    real fetch and degrades to coefficients on failure.
    """
    from web.startup import is_snapshot_mode

    if not is_snapshot_mode():
        from competitions.ucl.src.elo_fetcher import fetch_team_elos
        ratings = fetch_team_elos(team_names)
        if ratings:
            return ratings
    # Coefficient fallback (also the offline path for live mode failures).
    return {}



def _get_config_dir() -> str:
    """Return absolute path to competitions/ucl/config/ directory."""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config",
    )


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

    squad_values_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "squad_values.json",
    )
    signals = [
        RefinedEloSignal(),
        MarketOddsSignal(),
        RollingFormSignal(
            result_provider=_ReplayResultProvider(results_file) if results_file and os.path.exists(results_file)
            else _EmptyResultProvider()
        ),
        SquadValueSignal(data_path=squad_values_path),
        RestDaysSignal(),
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
    progress_cb: callable | None = None,
) -> SimulationResult:
    """Run MC simulation + one representative bracket iteration, return SimulationResult."""
    fixtures_dict = {"schedule": asdict(fixtures)}

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
    from competitions.ucl.src.simulation import simulate_league_phase
    standings = simulate_league_phase(fixtures_dict, elo_ratings, rng, played_matches=played_matches)

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
        standings, elo_ratings, rng,
        pairings_data=pairings_data,
    )
    bracket = build_r16_bracket(
        standings, playoff_result,
        bracket_data=bracket_data,
        rng=rng,
    )
    tree_result = simulate_knockout_tree(bracket, elo_ratings, rng)
    stages = track_knockout_stages(standings, tree_result)

    sim_state_payload = build_sim_state_payload(
        playoff_result["ties"],
        playoff_result["winners"],
        tree_result["rounds"],
        champion_probs=_top_champion_probs(mc_result["teams"]),
    )

    return SimulationResultWithState(
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
        sim_state_payload=sim_state_payload,
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
) -> object:
    """Orchestrate the full simulation: resolve mode, run MC, return result."""
    played_matches = resolve_played_matches(args, data_dir, fixtures_schedule)

    return build_simulation_result(
        fixtures_schedule, elo_ratings, seed, n_iterations,
        played_matches=played_matches,
    )


_PHASE_LABELS = {
    "not_started": "Not Started",
    "league_stage": "League Phase",
    "league_stage_complete": "League Phase Complete",
    "knockout_playoffs": "Knockout Playoffs",
    "knockout": "Knockout",
    "completed": "Completed",
}


def compute_competition_phase(data_dir: str | Path) -> dict:
    """Authoritative competition-phase report for UCL (competition brain).

    Derived from on-disk evidence only; the frontend must render this instead
    of inferring stage from payload shapes. ``stores`` carries DataAvailability
    values so 'phase not reached' and 'data unavailable' stay distinguishable.
    """
    results_path = Path(data_dir)
    _, league_availability, _ = load_json_store(results_path / "results.json")
    league_rows: list = []
    if league_availability is DataAvailability.AVAILABLE:
        payload, _, _ = load_json_store(results_path / "results.json")
        league_rows = payload.get("matches", payload) if isinstance(payload, dict) else payload
        if not isinstance(league_rows, list):
            league_rows = []
    n_league = sum(
        1 for m in league_rows
        if isinstance(m, dict) and m.get("home_score") is not None
    )

    _, ko_availability, _ = load_json_store(results_path / "knockout_results.json")
    ko_state: dict = {}
    if ko_availability is DataAvailability.AVAILABLE:
        payload, _, _ = load_json_store(results_path / "knockout_results.json")
        ko_state = payload.get("matches", {}) if isinstance(payload, dict) else {}
        if not isinstance(ko_state, dict):
            ko_state = {}
    ko_rounds = ko_state.get("rounds", {}) or {}
    n_playoff = len(ko_state.get("playoff", []) or [])
    n_ko_matches = sum(len(v or []) for v in ko_rounds.values())
    champion = ko_state.get("champion") or None

    if champion:
        phase = "completed"
    elif n_ko_matches > 0:
        phase = "knockout"
    elif n_playoff > 0:
        phase = "knockout_playoffs"
    elif n_league >= 144:
        phase = "league_stage_complete"
    elif n_league > 0:
        phase = "league_stage"
    else:
        phase = "not_started"

    return {
        "phase": phase,
        "label": _PHASE_LABELS[phase],
        "champion": champion,
        "progress": {"played": n_league, "total": 144},
        "stores": {
            "league_results": league_availability.value,
            "knockout_results": ko_availability.value,
        },
    }


def resolve_compute_mode(data_dir: str | Path) -> tuple[str, str]:
    """Decide 'results' vs 'simulation' from on-disk evidence.

    Results mode requires a readable, non-empty ``results.json`` only.
    Knockout data is NOT required: its availability is reported separately
    so the UI can say "unavailable" instead of fabricating a whole season
    over real league results (Exchange 1 architecture fix — previously a
    missing knockout file flipped Reset/Refresh into simulation mode).

    Returns ``(mode, reason)`` where mode is ``results``, ``simulation``
    or ``error`` (results.json exists but cannot be read).
    """
    payload, availability, detail = load_json_store(Path(data_dir) / "results.json")
    if availability is DataAvailability.AVAILABLE:
        return "results", "real results present"
    if availability is DataAvailability.EMPTY:
        return "simulation", "results.json present but contains no matches"
    if availability is DataAvailability.MISSING:
        return "simulation", "results.json absent"
    return "error", detail or "results.json unreadable"


def _load_league_played_pairs(
    data_dir: str | Path,
) -> dict[tuple[str, str], tuple[int, int]] | None:
    """Convert results.json into pair-keyed immutable facts for the MC engine.

    Both orientations are stored, matching the MatchResultProvider
    convention used by the simulation layer.
    """
    payload, availability, _ = load_json_store(Path(data_dir) / "results.json")
    if availability is not DataAvailability.AVAILABLE:
        return None
    entries = payload.get("matches", payload) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return None
    pairs: dict[tuple[str, str], tuple[int, int]] = {}
    for m in entries:
        try:
            home_goals = int(m["home_score"])
            away_goals = int(m["away_score"])
            team_a, team_b = m["team_a"], m["team_b"]
        except (KeyError, TypeError, ValueError):
            continue
        pairs[(team_a, team_b)] = (home_goals, away_goals)
        pairs[(team_b, team_a)] = (away_goals, home_goals)
    return pairs or None


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
    )
    from web.common import ts, boot_step

    boot: list[dict] = []

    def _step(name, fn):
        return boot_step(name, fn, boot)

    results = _step("Load real results", lambda: load_results(data_dir))
    if not results:
        return {"error": "results.json not found", "boot": boot}

    knockout = _step("Load knockout results", lambda: load_knockout_results(data_dir))
    _, ko_availability, ko_detail = load_json_store(
        Path(data_dir) / "knockout_results.json"
    )
    if not knockout:
        # Knockout data is unavailable (missing, empty, or unreadable):
        # standings and odds remain computable from real league results,
        # and the availability report tells the frontend to say so instead
        # of guessing a stage.
        knockout = {"playoff": [], "rounds": {"R16": [], "QF": [], "SF": [], "FINAL": []}}
        if ko_availability is DataAvailability.MISSING:
            ko_msg = "[info] knockout_results.json absent — knockout data unavailable; bracket left empty"
        elif ko_availability is DataAvailability.EMPTY:
            ko_msg = "[info] knockout_results.json present but empty — knockout data unavailable; bracket left empty"
        else:
            ko_msg = f"[warn] knockout_results.json unreadable ({ko_detail}) — bracket left empty"
        boot.append({"step": "Load knockout results", "status": "ok", "elapsed": 0.0,
                     "output": ko_msg})

    from competitions.ucl.src.provider import RepoFixtureProvider

    fixtures_path = os.path.join(data_dir, "fixtures.json")
    provider = _step("Load fixtures", lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load())
    if not provider:
        return {"error": "fixtures load failed", "boot": boot}

    team_names = [t.name for t in provider.teams]
    from competitions.ucl.src.elo_fetcher import fetch_team_elos

    elo_ratings = _step("Fetch Elo ratings", lambda: _resolve_elo_ratings(team_names))
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot.append({"step": "Elo fallback (coefficients)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Elo fallback"})

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

    signal_stats = _step("Evaluate signals", lambda: compute_signal_eval(results, engine, elo_ratings))

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
        "availability": {
            "league_results": DataAvailability.AVAILABLE.value,
            "knockout_results": ko_availability.value,
        },
        "phase": compute_competition_phase(data_dir),
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
    seed, snapshot_date, show_ci.
    """
    from web.common import ts, boot_step

    boot: list[dict] = []

    def _step(name, fn):
        return boot_step(name, fn, boot)

    results_path = os.path.join(data_dir, "results.json")

    mode, mode_reason = resolve_compute_mode(data_dir)

    if mode == "results":
        return run_deterministic_compute(data_dir, bsd_api_key, team_aliases=team_aliases)
    if mode == "error":
        return {"error": f"results.json unreadable: {mode_reason}", "boot": boot}

    # Simulation fallback. Real league results remain immutable facts even
    # when knockout data is unavailable — a simulated season must never be
    # rendered over unconditioned real results.
    played_matches = _load_league_played_pairs(results_path)

    from competitions.ucl.src.provider import RepoFixtureProvider
    from competitions.ucl.src.elo_fetcher import fetch_team_elos

    fixtures_path = os.path.join(data_dir, "fixtures.json")
    provider = _step("Load fixtures", lambda: RepoFixtureProvider(fixtures_path=fixtures_path).load())
    if not provider:
        return {"error": "fixtures load failed", "boot": boot}

    team_names = [t.name for t in provider.teams]
    elo_ratings = _step("Fetch Elo ratings", lambda: _resolve_elo_ratings(team_names))
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
    if not elo_ratings:
        elo_ratings = {}
        coefficients = {t.name: t.coefficient for t in provider.teams}
        max_coeff = max(coefficients.values()) if coefficients else 100
        for t in team_names:
            c = coefficients.get(t, 50)
            elo_ratings[t] = 1400.0 + (c / max_coeff) * 400.0
        boot.append({"step": "Elo fallback (coefficients)", "status": "ok", "elapsed": 0.0, "output": f"[{ts()}] Elo fallback"})

    # Run MC simulation (played league matches are injected as fixed facts)
    result = _step(
        "Monte Carlo simulation",
        lambda: build_simulation_result(provider, elo_ratings, seed, n_iterations, played_matches=played_matches),
    )
    if not result:
        return {"error": "simulation failed", "boot": boot}

    engine = _step("Build signal engine", lambda: build_signal_engine(elo_ratings))

    # Exchange 2 unification: one clean payload (built inside
    # build_simulation_result) feeds both the canonical state layer and
    # the legacy display keys below — no duplicate enrichment here.
    payload = result.sim_state_payload
    playoff_display = payload["playoff"]
    enriched_bracket = payload["bracket_rounds"]

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

    _, league_availability, _ = load_json_store(Path(results_path))
    _, ko_availability, _ = load_json_store(
        Path(data_dir) / "knockout_results.json")
    return {
        "mode": "simulation",
        "availability": {
            "league_results": league_availability.value,
            "knockout_results": ko_availability.value,
            "simulated": True,
        },
        "phase": compute_competition_phase(data_dir),
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
        "sim_state_payload": payload,
        "odds": odds_display,
        "signals": signal_stats,
        "elo_ratings": elo_ratings,
        "show_ci": "auto",
        "league_matchdays": {},
        "boot": boot,
        "_signal_engine": engine,
    }
