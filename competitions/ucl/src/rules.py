"""UCL TournamentRules adapter for the generic simulation engine.

The competition brain owns everything format-specific here: the 36-team
Swiss league phase, UEFA tiebreaking (via compute_swiss_standings), Top-8 /
playoff qualification, the playoff draw ceremony, the bracket_rules-driven
knockout tree, and champion determination. Real played league matches enter
as immutable pair-keyed facts that are substituted verbatim every iteration.

The generic engine (football_core.simulation.MonteCarloEngine) owns
validation, RNG isolation, repetition, aggregation, provenance, and error
semantics. Nothing in this module may be imported by football_core.
"""

from __future__ import annotations

import json
import os
from typing import Any, Callable, Mapping

from football_core.constants import EXPECTED_GOALS_BASE_RATE
from football_core.simulation import (
    LadderCounter,
    PositionHistogram,
    RunContext,
    TeamStatsAverages,
    ValueCounter,
)

from competitions.ucl.src.groups import compute_swiss_standings
from competitions.ucl.src.knockout import (
    build_r16_bracket,
    simulate_knockout_tree,
    simulate_playoff_round,
    track_knockout_stages,
)
from competitions.ucl.src.simulation import (
    STAGE_ORDER,
    precompute_swiss_matchup_lambdas,
    simulate_league_phase,
)


class UCLRules:
    """One complete UCL season realization per simulate_one() call."""

    def __init__(
        self,
        fixtures: dict,
        elo_ratings: dict[str, float],
        uefa_coefficients: dict[str, float] | None = None,
        played_matches: dict[tuple[str, str], tuple[int, int]] | None = None,
        pairings_data: dict | None = None,
        bracket_rules_data: dict | None = None,
    ) -> None:
        # Read-only competition inputs — never mutated by this adapter.
        self._fixtures = fixtures
        self._elo_ratings = elo_ratings or {}
        self._coefficients = uefa_coefficients or {}
        self._played_matches = played_matches or {}
        if pairings_data is None:
            pairings_data = self._load_data_file("playoff_pairings.json")
        if bracket_rules_data is None:
            bracket_rules_data = self._load_data_file("bracket_rules.json")
        # Draw steps work on copies; keep the originals untouched.
        self._pairings_data = {
            "pairings": [dict(p) for p in pairings_data.get("pairings", [])]
        }
        self._bracket_data = {
            "matches": [dict(m) for m in bracket_rules_data.get("matches", [])]
        }
        # Expensive setup runs once per REQUEST, not once per iteration.
        self._matchup_lambdas = precompute_swiss_matchup_lambdas(
            fixtures, self._elo_ratings, EXPECTED_GOALS_BASE_RATE,
        )
        self._elo_for_knockout = dict(self._elo_ratings)

    @staticmethod
    def _load_data_file(filename: str) -> dict:
        data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
        )
        with open(os.path.join(data_dir, filename)) as f:
            return json.load(f)

    # ── SimulationRules protocol ────────────────────────────────────────

    def declare_aggregations(self) -> Mapping[str, Callable[[], Any]]:
        return {
            "positions": lambda: PositionHistogram("positions"),
            "stats": lambda: TeamStatsAverages("stats"),
            "champion": lambda: ValueCounter("champion"),
            "ladder": lambda: LadderCounter("ladder", STAGE_ORDER),
        }

    def simulate_one(self, context: RunContext) -> Mapping[str, Any]:
        rng = context.rng

        standings = simulate_league_phase(
            self._fixtures, self._elo_ratings, rng,
            uefa_coefficients=self._coefficients,
            matchup_lambdas=self._matchup_lambdas,
            played_matches=self._played_matches,
        )

        playoff_result = simulate_playoff_round(
            standings, self._elo_for_knockout, rng,
            pairings_data=self._pairings_data,
        )
        bracket = build_r16_bracket(
            standings, playoff_result,
            bracket_data=self._bracket_data,
            rng=rng,
        )
        tree_result = simulate_knockout_tree(bracket, self._elo_for_knockout, rng)
        stages = track_knockout_stages(standings, tree_result)

        positions: dict[str, int] = {}
        stats: dict[str, dict[str, float]] = {}
        ladder: dict[str, str] = {}
        for entry in standings:
            team = entry["team"]
            positions[team] = entry["position"]
            stats[team] = {
                "pts": entry["pts"], "gd": entry["gd"], "gs": entry["gs"],
                "away_gs": entry["away_gs"], "wins": entry["wins"],
                "away_wins": entry["away_wins"],
            }
            ladder[team] = stages.get(team, "eliminated")

        return {
            "positions": positions,
            "stats": stats,
            "ladder": ladder,
            "champion": tree_result.get("champion"),
        }

    def provenance_attestation(self) -> Mapping[str, Any]:
        return {
            "real_results_preserved": True,
            "simulated_matches_only": True,
            "conditioned_real_results": {
                "league_matches": len(self._played_matches) // 2,
                "knockout_results": 0,
            },
        }
