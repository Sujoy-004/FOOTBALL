"""LaLiga league championship simulation — engine-compliant rules.

Real played results are immutable facts keyed by ``match_id``; only the
unplayed fixtures are sampled each run. Sampling reuses the shared Poisson
kernel (``football_core.groups.expected_goals`` + the cached Poisson CDF
table), so the score model is identical to the other brains.

Why not ``football_core.groups.simulate_league_matches``: its played-match
lookup is keyed by team *pair* and synthesizes reverse orientations, which
is exactly wrong for a double round-robin where the (A,B) and (B,A) legs
are distinct real fixtures. This rules object keys facts by the derived
fixture id per slot instead.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from football_core import constants as core_constants
from football_core.groups import expected_goals, _build_poisson_table
from football_core.signal import PredictionContext
from football_core.simulation import (
    MonteCarloEngine,
    PositionHistogram,
    RunContext,
    SimulationRequest,
    ValueCounter,
)

from competitions.laliga.src.constants import GLOBAL_AVG_ELO, N_TEAMS
from competitions.laliga.src.groups import compute_laliga_standings

_TABLE_BITS = core_constants.POISSON_TABLE_BITS
_BASE_RATE = core_constants.EXPECTED_GOALS_BASE_RATE


def sample_match_score(
    elo_home: float, elo_away: float, rng: random.Random
) -> tuple[int, int]:
    lam_home = expected_goals(elo_home, elo_away, _BASE_RATE)
    lam_away = expected_goals(elo_away, elo_home, _BASE_RATE)
    table_bits = _TABLE_BITS
    getrandbits = rng.getrandbits
    score_home = 0 if lam_home <= 0.0 else _build_poisson_table(lam_home)[getrandbits(table_bits)]
    score_away = 0 if lam_away <= 0.0 else _build_poisson_table(lam_away)[getrandbits(table_bits)]
    return score_home, score_away


@dataclass
class LeagueSimulationRules:
    """``SimulationRules`` realization for a 20-team round-robin league."""

    team_names: list[str]
    playable: list[dict] = field(default_factory=list)
    played: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    elo_ratings: Mapping[str, float] = field(default_factory=dict)
    rules_version: str = "laliga-league-v1"

    def declare_aggregations(self) -> Mapping[str, Callable[[], Any]]:
        return {
            "champion": lambda: ValueCounter("champion"),
            "positions": lambda: PositionHistogram("standings"),
        }

    def simulate_one(self, context: RunContext) -> Mapping[str, Any]:
        rng = context.rng
        sim_results: dict[str, dict] = dict(self.played)
        elo = dict(self.elo_ratings)
        for f in self.playable:
            ta, tb = f["team_a"], f["team_b"]
            sh, sa = sample_match_score(
                elo.get(ta, GLOBAL_AVG_ELO), elo.get(tb, GLOBAL_AVG_ELO), rng
            )
            sim_results[f["match_id"]] = {
                "team_a": ta, "team_b": tb, "score_a": sh, "score_b": sa,
            }
        rows = compute_laliga_standings(sim_results, elo)
        positions = {row["team"]: row["position"] for row in rows}
        return {"champion": positions and rows[0]["team"], "standings": positions}

    def provenance_attestation(self) -> Mapping[str, Any]:
        return {
            "simulated_matches_only": True,
            "real_results_preserved_as_facts": True,
            "n_played_facts": len(self.played),
            "n_unplayed_sampled": len(self.playable),
        }


def build_schedule(team_names: list[str], fixtures: list[dict]) -> dict:
    """Group flat fixtures into matchday buckets (copies, no mutation)."""
    matchdays: dict[int, list[dict]] = {}
    for f in fixtures:
        md = int(f.get("matchday") or 0)
        matchdays.setdefault(md, []).append(dict(f))
    return {
        "teams": list(team_names),
        "matchdays": [matchdays[md] for md in sorted(matchdays) if md],
    }


def run_mc_simulation(
    data_dir,
    n_iterations: int = 10000,
    seed: int | None = None,
    weights: dict[str, float] | None = None,
    show_ci: str = "auto",
    progress_cb=None,
    elo_ratings_override: dict[str, float] | None = None,
    played_map: dict[str, dict] | None = None,
    playable_fixtures: list[dict] | None = None,
    team_names: list[str] | None = None,
    season: str = "2026/27",
) -> dict:
    """Full Monte Carlo pipeline for the LaLiga championship.

    Returns the parity-shaped dict consumed by the web sim cache:
    mode/teams/all_teams/n_teams/n_iterations/seed/snapshot_date/
    champion/standings/odds/signals/elo_ratings/show_ci/_meta.
    Does NOT write to disk or the web cache.
    """
    from competitions.laliga.src.pipeline import (
        load_elo_ratings,
        load_fixtures,
        load_played_flat,
        load_team_names,
        build_signal_engine,
    )

    if progress_cb:
        progress_cb(0, 100, "Loading fixtures...")

    team_names = team_names or load_team_names(data_dir)
    if playable_fixtures is not None:
        fixtures = list(playable_fixtures)
    else:
        fixtures = [
            {"match_id": f["match_id"],
             "team_a": f.get("team_a") or f.get("home_team"),
             "team_b": f.get("team_b") or f.get("away_team"),
             "matchday": f.get("matchday"), "status": f.get("status")}
            for f in load_fixtures(data_dir) if f.get("status") != "finished"
        ]
    played = played_map if played_map is not None else load_played_flat(data_dir)
    if progress_cb:
        progress_cb(10, 100, "Resolving Elo ratings...")

    elo_ratings = (
        dict(elo_ratings_override)
        if elo_ratings_override
        else load_elo_ratings(data_dir)
    )

    rules = LeagueSimulationRules(
        team_names=list(team_names),
        playable=[dict(f) for f in fixtures],
        played=dict(played),
        elo_ratings=dict(elo_ratings),
    )
    request = SimulationRequest(
        competition_id="laliga", season=season, n_simulations=n_iterations, seed=seed
    )
    if progress_cb:
        progress_cb(20, 100, "Running Monte Carlo...")

        def _mc(c: int, total: int) -> None:
            progress_cb(c, total)

        progress = _mc
    else:
        progress = None

    result = MonteCarloEngine().run(request, rules, progress_cb=progress)
    aggregates = result.aggregates
    n = aggregates.get("n_simulations", 0) or 1

    champion_counts = aggregates.get("champion", {}).get("counts", {})
    positions_hist = aggregates.get("positions", {}) or {}

    odds_display = []
    for team in sorted(champion_counts, key=lambda t: (-champion_counts[t], t)):
        buckets = positions_hist.get(team, {})
        total = sum(buckets.values()) or 0
        avg_pos = (
            sum(p * c for p, c in buckets.items()) / total if total else float("nan")
        )
        top_6 = sum(c for p, c in buckets.items() if p <= 6) / n
        mid = sum(c for p, c in buckets.items() if 7 <= p <= 10) / n
        bottom = sum(c for p, c in buckets.items() if p > 10) / n
        odds_display.append({
            "rank": len(odds_display) + 1,
            "team": team,
            "champion_prob": round(champion_counts[team] / n, 4),
            "top_6_prob": round(top_6, 4),
            "mid_table_prob": round(mid, 4),
            "bottom_prob": round(bottom, 4),
            "avg_position": round(avg_pos, 2),
        })

    if progress_cb:
        progress_cb(85, n_iterations)

    engine = build_signal_engine(elo_ratings, weights_override=weights)
    signal_stats = _signal_stats(engine, elo_ratings, fixtures)

    if progress_cb:
        progress_cb(95, n_iterations)
        progress_cb(100, n_iterations)

    return {
        "mode": "simulation",
        "teams": odds_display[: min(4, len(odds_display))],
        "all_teams": odds_display,
        "n_teams": len(team_names),
        "n_iterations": n,
        "seed": aggregates.get("seed"),
        "snapshot_date": "",
        "season": season,
        "champion": max(champion_counts, key=champion_counts.get) if champion_counts else None,
        "standings": [],
        "odds": odds_display,
        "signals": signal_stats,
        "elo_ratings": dict(elo_ratings),
        "show_ci": show_ci,
        "_meta": {
            "n_simulations": n,
            "seed": aggregates.get("seed"),
            "engine_version": "monte-carlo-v1",
            "provenance": rules.provenance_attestation(),
        },
    }


def _signal_stats(engine, elo_ratings: dict, fixtures: list[dict]) -> dict:
    from football_core.blender import EnsembleEngine

    if not isinstance(engine, EnsembleEngine):
        return {}
    ctx = PredictionContext(
        fixtures=[{"team_a": f.get("team_a") or f.get("home_team"),
                   "team_b": f.get("team_b") or f.get("away_team"),
                   "match_id": f["match_id"]}
                  for f in fixtures if f.get("status") != "finished"],
        elo_ratings=elo_ratings,
    )
    blobs = [engine.evaluate(m, ctx) for m in ctx.fixtures]
    sig_data: dict[str, dict] = {}
    for bp in blobs:
        for sig, sd in bp.signal_breakdown.items():
            bucket = sig_data.setdefault(sig, {"probs": [], "n": 0, "available": 0})
            bucket["n"] += 1
            bucket["available"] += 1
            if sd.get("weight", 0) > 0:
                bucket["probs"].append(sd.get("home", 0.5))
    out = {}
    for sig, sd in sorted(sig_data.items()):
        probs = [p for p in sd["probs"] if p is not None]
        out[sig] = {
            "n_matches": sd["n"],
            "available": sd["available"],
            "available_pct": round(sd["available"] / sd["n"] * 100, 1) if sd["n"] else 0.0,
            "avg_probability": round(sum(probs) / len(probs), 4) if probs else 0.0,
            "weight": round(engine.weights.get(sig, 0), 4),
        }
    return out