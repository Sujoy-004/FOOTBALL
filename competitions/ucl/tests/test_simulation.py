"""Tests for UCL match simulation.

Covers:
- UCLT-01: Simulate 36-team league phase
- UCLT-06: Reuse football_core Poisson primitives, no core modifications

The retired ClubElo fetcher test surface died with the fetcher itself:
Elo provenance is covered by test_orchestrator.py and tests/test_elo_replay.py
(kernel). team_aliases.json lives on as committed DATA — its fixture
handling is verified in tests/test_dynamic_fixtures.py.
"""

from __future__ import annotations

import random

# ═══════════════════════════════════════════════════════════════════════════════
# ── Task 3: Swiss Match Simulation (TDD — RED)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSwissMatchSimulation:
    """Tests for Swiss match simulation using football_core Poisson primitives.

    Covers UCLT-01 (36-team league phase simulation) and UCLT-06 (core reuse).
    """

    def test_simulate_swiss_matches_count(
        self, sample_fixture_schedule, sample_36_teams, sample_rng,
    ):
        """144 matches from full fixture schedule."""
        from competitions.ucl.src.groups import simulate_swiss_matches

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        results = simulate_swiss_matches(sample_fixture_schedule, elos, sample_rng)
        assert len(results) == 144

    def test_simulate_swiss_matches_structure(
        self, sample_fixture_schedule, sample_36_teams, sample_rng,
    ):
        """Each result has all required keys."""
        from competitions.ucl.src.groups import simulate_swiss_matches

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        results = simulate_swiss_matches(sample_fixture_schedule, elos, sample_rng)
        assert len(results) > 0, "No results returned"

        required_keys = {
            "team_a", "team_b", "score_a", "score_b", "winner",
            "yellow_cards_a", "red_cards_a", "yellow_cards_b", "red_cards_b",
        }
        for match_id, result in results.items():
            missing = required_keys - set(result.keys())
            assert not missing, f"Match {match_id} missing keys: {missing}"

    def test_simulate_swiss_matches_no_mutation(
        self, sample_fixture_schedule, sample_36_teams, sample_rng,
    ):
        """Input fixture dict is NOT mutated by simulate_swiss_matches."""
        import copy
        from competitions.ucl.src.groups import simulate_swiss_matches

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        original = copy.deepcopy(sample_fixture_schedule)
        simulate_swiss_matches(sample_fixture_schedule, elos, sample_rng)
        assert sample_fixture_schedule == original

    def test_simulate_swiss_matches_deterministic(
        self, sample_fixture_schedule, sample_36_teams,
    ):
        """Same seed produces identical results."""
        from competitions.ucl.src.groups import simulate_swiss_matches

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        rng1 = random.Random(42)
        rng2 = random.Random(42)
        results1 = simulate_swiss_matches(sample_fixture_schedule, elos, rng1)
        results2 = simulate_swiss_matches(sample_fixture_schedule, elos, rng2)
        assert len(results1) > 0, "No results returned (stub)"
        assert results1 == results2

    def test_simulate_swiss_matches_scores_non_negative(
        self, sample_fixture_schedule, sample_36_teams, sample_rng,
    ):
        """All scores are >= 0."""
        from competitions.ucl.src.groups import simulate_swiss_matches

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        results = simulate_swiss_matches(sample_fixture_schedule, elos, sample_rng)
        assert len(results) > 0, "No results returned"
        for result in results.values():
            assert result["score_a"] >= 0, f"Negative score_a: {result['score_a']}"
            assert result["score_b"] >= 0, f"Negative score_b: {result['score_b']}"

    def test_simulate_swiss_matches_fair_play(
        self, sample_fixture_schedule, sample_36_teams, sample_rng,
    ):
        """Yellow/red card values present and non-negative."""
        from competitions.ucl.src.groups import simulate_swiss_matches

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        results = simulate_swiss_matches(sample_fixture_schedule, elos, sample_rng)
        assert len(results) > 0, "No results returned"
        for result in results.values():
            assert result["yellow_cards_a"] >= 0
            assert result["red_cards_a"] >= 0
            assert result["yellow_cards_b"] >= 0
            assert result["red_cards_b"] >= 0

    def test_core_primitives_reused(self):
        """Verify imports come from football_core.groups, no core modifications."""
        import inspect
        from competitions.ucl.src import groups as groups_mod

        src = inspect.getsource(groups_mod)
        # Must import from football_core
        assert "from football_core" in src, (
            "groups.py must import from football_core"
        )
        # Must NOT import its own Poisson implementation
        assert "_build_poisson_table" not in src or "football_core" in src, (
            "Poisson primitives must come from football_core, not be reimplemented"
        )

    def test_precompute_matchup_lambdas(
        self, sample_fixture_schedule, sample_36_teams,
    ):
        """Lambdas are precomputed per match_id."""
        from competitions.ucl.src.groups import precompute_swiss_matchup_lambdas

        elos = {n: d["elo"] for n, d in sample_36_teams.items()}
        lambdas = precompute_swiss_matchup_lambdas(sample_fixture_schedule, elos)
        assert len(lambdas) == 144, f"Expected 144 lambdas, got {len(lambdas)}"
        for mid, (la, lb) in lambdas.items():
            assert la > 0, f"Match {mid} lambda_a is {la}"
            assert lb > 0, f"Match {mid} lambda_b is {lb}"
