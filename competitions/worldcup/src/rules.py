"""World Cup TournamentRules adapter for the generic simulation engine.

The competition brain owns everything format-specific here: groups and
points, the 12-group/third-place/Annex-C qualification chain, knockout slot
resolution over the bracket DAG, TPP loser routing, and FIFA-specific
tiebreakers. Real played matches (groups + knockout) enter as immutable
facts that override sampling.

The generic engine (football_core.simulation.MonteCarloEngine) owns
validation, RNG isolation, repetition, aggregation, provenance, and error
semantics. Nothing in this module may be imported by football_core.
"""

from __future__ import annotations

import random
from typing import Any, Callable, Mapping

from football_core.groups import (
    precompute_matchup_lambdas,
    simulate_group_matches,
)
from football_core.knockout import (
    _build_round_map,
    _get_blended_prob,
    _simulate_knockout_round,
)
from football_core.simulation import RunContext, TeamListCounter, ValueCounter

from competitions.worldcup.src import constants
from competitions.worldcup.src.groups import (
    compute_standings,
    rank_third_placed,
    resolve_r32_matchups,
    select_advancers,
)

_ROUND_ORDER = ["R16", "QF", "SF", "FINAL"]
_STAGE_KEYS = {"QF": "qf", "SF": "sf", "FINAL": "final"}


class WorldCupRules:
    """One complete World Cup realization per simulate_one() call."""

    def __init__(
        self,
        teams: dict[str, dict],
        groups: dict,
        bracket: list[dict],
        annex_c: dict,
        played: dict[str, dict],
        played_groups: dict[str, dict],
        blend_params: dict | None = None,
        xg_overrides: dict[str, tuple[float, float]] | None = None,
    ) -> None:
        # Read-only competition inputs — never mutated by this adapter.
        self._teams = teams
        self._groups = groups
        self._bracket = bracket
        self._annex_c = annex_c
        self._played = played or {}
        self._played_groups = played_groups or {}
        self._blend_params = blend_params
        self._elo_ratings = {name: data["elo"] for name, data in teams.items()}
        self._round_map = _build_round_map(bracket)
        # Expensive setup runs once per REQUEST, not once per iteration.
        self._matchup_lambdas = precompute_matchup_lambdas(
            groups, self._elo_ratings,
            base_rate=constants.EXPECTED_GOALS_BASE_RATE,
            xg_overrides=xg_overrides,
        )

    # ── SimulationRules protocol ────────────────────────────────────────

    def declare_aggregations(self) -> Mapping[str, Callable[[], Any]]:
        return {
            "champion": lambda: ValueCounter("champion"),
            "qf": lambda: TeamListCounter("qf"),
            "sf": lambda: TeamListCounter("sf"),
            "final": lambda: TeamListCounter("final"),
        }

    def simulate_one(self, context: RunContext) -> Mapping[str, Any]:
        rng: random.Random = context.rng
        winner_progression: dict[str, str] = {}
        sf_losers: dict[str, str | None] = {}

        results = simulate_group_matches(
            self._groups, self._teams, self._elo_ratings, rng,
            fair_play=False, matchup_lambdas=self._matchup_lambdas,
            played_groups=self._played_groups,
            base_rate=constants.EXPECTED_GOALS_BASE_RATE,
        )
        standings = compute_standings(results, self._elo_ratings)
        third_ranked = rank_third_placed(standings)
        advancers = select_advancers(standings, third_ranked)
        r32_matchups = resolve_r32_matchups(
            advancers, standings, third_ranked, self._annex_c)

        winner_progression.update(self._play_r32(r32_matchups, rng))
        self._play_from_round_map("R16", winner_progression, sf_losers, rng)
        for round_name in ("QF", "SF"):
            _simulate_knockout_round(
                self._round_map, round_name, self._played,
                winner_progression, sf_losers, rng,
                self._elo_ratings, self._blend_params)
        self._play_tpp(winner_progression, sf_losers, rng)
        _simulate_knockout_round(
            self._round_map, "FINAL", self._played,
            winner_progression, None, rng, self._elo_ratings, self._blend_params)

        stage_teams: dict[str, list[str]] = {"qf": [], "sf": [], "final": []}
        for round_name in _ROUND_ORDER:
            stage = _STAGE_KEYS.get(round_name)
            if not stage:
                continue
            for match in self._round_map.get(round_name, []):
                sources = match.get("source_matches")
                if not sources:
                    continue
                for src in sources:
                    team = winner_progression.get(src)
                    if team is not None:
                        stage_teams[stage].append(team)

        return {
            "champion": winner_progression.get("FINAL"),
            **stage_teams,
        }

    def provenance_attestation(self) -> Mapping[str, Any]:
        return {
            "real_results_preserved": True,
            "simulated_matches_only": True,
            "conditioned_real_results": {
                "groups": len(self._played_groups),
                "knockout": len(self._played),
            },
        }

    # ── format-specific helpers (WC brain logic) ────────────────────────

    def _play_r32(
        self,
        r32_matchups: dict[str, dict],
        rng: random.Random,
    ) -> dict[str, str]:
        winners: dict[str, str] = {}
        for mid, match in r32_matchups.items():
            real = self._played.get(mid)
            if real is not None and real.get("winner") is not None:
                winners[mid] = real["winner"]
                continue
            team_a, team_b = match["team_a"], match["team_b"]
            p_a = _get_blended_prob(mid, team_a, team_b, self._blend_params,
                                    self._elo_ratings)
            winners[mid] = team_a if rng.random() < p_a else team_b
        return winners

    def _play_from_round_map(
        self,
        round_name: str,
        winner_progression: dict[str, str | None],
        sf_losers: dict[str, str | None],
        rng: random.Random,
    ) -> None:
        for match in self._round_map.get(round_name, []):
            mid = match["match_id"]
            real = self._played.get(mid)
            if real is not None:
                winner_progression[mid] = real.get("winner")
                continue
            sources = match["source_matches"]
            teams_in_match = [winner_progression.get(s) for s in sources]
            if any(t is None for t in teams_in_match):
                continue
            if len(teams_in_match) == 1:
                winner_progression[mid] = teams_in_match[0]
                continue
            team_a, team_b = teams_in_match[0], teams_in_match[1]
            p_a = _get_blended_prob(mid, team_a, team_b, self._blend_params,
                                    self._elo_ratings)
            winner_progression[mid] = team_a if rng.random() < p_a else team_b

    def _play_tpp(
        self,
        winner_progression: dict[str, str | None],
        sf_losers: dict[str, str | None],
        rng: random.Random,
    ) -> None:
        for match in self._round_map.get("TPP", []):
            mid = match["match_id"]
            real = self._played.get(mid)
            if real is not None:
                winner_progression[mid] = real.get("winner")
                continue
            sources = match["source_matches"]
            teams_in_match = [sf_losers.get(s) for s in sources]
            if None in teams_in_match or len(teams_in_match) < 2:
                continue
            team_a, team_b = teams_in_match[0], teams_in_match[1]
            p_a = _get_blended_prob(mid, team_a, team_b, self._blend_params,
                                    self._elo_ratings)
            winner_progression[mid] = team_a if rng.random() < p_a else team_b
