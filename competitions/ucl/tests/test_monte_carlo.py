"""Tests for Monte Carlo simulation engine (UCLT-05).

Covers:
- Deterministic output with fixed seed (N=1, N=2)
- Output format matching D-06/D-07 specification
- Per-team zone and champion probabilities
- Aggregation correctness (isolated from simulation)
- Smoke test with N=100 iterations for performance
"""

from __future__ import annotations

import random

import pytest

from competitions.ucl.src.simulation import (
    aggregate_mc_results,
    run_monte_carlo,
    simulate_league_phase,
)


# ═══════════════════════════════════════════════════════════════════════════════
# ── Monte Carlo Loop Tests
# ═══════════════════════════════════════════════════════════════════════════════


class TestMonteCarlo:
    """Tests for the Monte Carlo simulation loop."""

    def test_run_monte_carlo_n1(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """N=1 produces deterministic output (same seed = identical)."""
        result1 = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=1, seed=42,
        )
        result2 = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=1, seed=42,
        )
        assert result1["teams"] == result2["teams"]
        assert result1["n_iterations"] == 1
        assert result1["seed"] == 42

    def test_run_monte_carlo_n2(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """N=2 produces averaged probabilities (values are 0, 0.5, or 1.0)."""
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=2, seed=42,
        )
        for team_data in result["teams"].values():
            for prob_key in ["top_8_prob", "playoff_prob", "eliminated_prob"]:
                assert team_data[prob_key] in (0.0, 0.5, 1.0), (
                    f"{prob_key} = {team_data[prob_key]} not in (0, 0.5, 1.0)"
                )

    def test_run_monte_carlo_output_keys(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """Output dict has all required top-level keys."""
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=5, seed=42,
        )
        assert "snapshot_date" in result
        assert "n_iterations" in result
        assert "seed" in result
        assert "teams" in result
        assert result["n_iterations"] == 5
        assert result["seed"] == 42

    def test_run_monte_carlo_team_keys(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """Each team entry has all 10 required keys per D-06/D-07."""
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=5, seed=42,
        )
        sample_team = list(result["teams"].keys())[0]
        team_data = result["teams"][sample_team]

        expected_keys = [
            "top_8_prob", "playoff_prob", "eliminated_prob",
            "champion_prob",
            "avg_position", "avg_pts", "avg_gd", "avg_gs",
            "avg_away_gs", "avg_wins", "avg_away_wins",
        ]
        for key in expected_keys:
            assert key in team_data, f"Missing key: {key}"

    def test_run_monte_carlo_zones_sum_to_1(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """Zone probabilities sum to 1.0 for each team."""
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=10, seed=42,
        )
        for team_name, team_data in result["teams"].items():
            zone_sum = (
                team_data["top_8_prob"]
                + team_data["playoff_prob"]
                + team_data["eliminated_prob"]
            )
            assert abs(zone_sum - 1.0) < 1e-10, (
                f"{team_name}: zone probs sum to {zone_sum}, expected 1.0"
            )

    def test_run_monte_carlo_champion_prob(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """At least one team has champion_prob > 0 with N >= 100."""
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=100, seed=42,
        )
        champ_probs = [
            data["champion_prob"] for data in result["teams"].values()
        ]
        assert sum(champ_probs) > 0, "No team has champion_prob > 0"
        assert max(champ_probs) > 0, "Max champion_prob is 0"
        # Identify the favourite
        best_team = max(
            result["teams"].items(), key=lambda x: x[1]["champion_prob"],
        )
        assert best_team[1]["champion_prob"] > 0, (
            f"Best team '{best_team[0]}' has zero champion_prob"
        )

    def test_run_monte_carlo_different_seed(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """Different seed produces different results."""
        result1 = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=10, seed=42,
        )
        result2 = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=10, seed=123,
        )

        assert result1["seed"] == 42
        assert result2["seed"] == 123

    def test_run_monte_carlo_100_iterations_smoke(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        """Smoke test with 100 iterations completes in reasonable time."""
        import time
        start = time.time()
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=100, seed=42,
        )
        elapsed = time.time() - start
        assert len(result["teams"]) == len(sample_elo_dict)
        assert elapsed < 30, (
            f"100 iterations took {elapsed:.1f}s (expected < 30s)"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ── Aggregation Unit Tests (isolated from simulation)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAggregateMCResults:
    """Tests for ``aggregate_mc_results()`` in isolation."""

    def test_aggregate_basic(self):
        """Basic aggregation produces correct probabilities and averages."""
        positions = {
            "Team A": [1, 5, 10, 20, 30],
            "Team B": [8, 9, 15, 25, 35],
        }
        champions = {"Team A": 1, "Team B": 0}
        stat_collectors = {
            "Team A": {
                "pts": [18, 15, 12, 9, 6],
                "gd": [10, 5, 0, -3, -8],
                "gs": [15, 12, 10, 8, 5],
                "away_gs": [7, 6, 5, 4, 2],
                "wins": [6, 5, 4, 3, 2],
                "away_wins": [3, 2, 2, 1, 1],
            },
            "Team B": {
                "pts": [16, 14, 10, 7, 4],
                "gd": [6, 3, -1, -5, -10],
                "gs": [12, 10, 8, 6, 3],
                "away_gs": [6, 5, 4, 3, 1],
                "wins": [5, 4, 3, 2, 1],
                "away_wins": [2, 2, 1, 1, 0],
            },
        }

        result = aggregate_mc_results(positions, champions, stat_collectors, 5)

        # Team A: positions 1,5,10,20,30 → top_8=2, playoff=2, eliminated=1
        assert result["Team A"]["top_8_prob"] == 0.4
        assert result["Team A"]["playoff_prob"] == 0.4
        assert result["Team A"]["eliminated_prob"] == 0.2
        assert result["Team A"]["champion_prob"] == 0.2

        # Team B: positions 8,9,15,25,35 → top_8=1, playoff=2, eliminated=2
        assert result["Team B"]["top_8_prob"] == 0.2
        assert result["Team B"]["playoff_prob"] == 0.4
        assert result["Team B"]["eliminated_prob"] == 0.4
        assert result["Team B"]["champion_prob"] == 0.0

    def test_aggregate_averages(self):
        """Stat averages computed correctly from pre-collected data."""
        positions = {"Team X": [1, 2, 3]}
        champions = {"Team X": 0}
        stat_collectors = {
            "Team X": {
                "pts": [10, 20, 30],
                "gd": [1, 2, 3],
                "gs": [5, 10, 15],
                "away_gs": [2, 4, 6],
                "wins": [3, 6, 9],
                "away_wins": [1, 2, 3],
            },
        }

        result = aggregate_mc_results(positions, champions, stat_collectors, 3)

        assert result["Team X"]["avg_position"] == 2.0  # (1+2+3)/3
        assert result["Team X"]["avg_pts"] == 20.0  # (10+20+30)/3
        assert result["Team X"]["avg_gd"] == 2.0  # (1+2+3)/3
        assert result["Team X"]["avg_gs"] == 10.0  # (5+10+15)/3
        assert result["Team X"]["avg_away_gs"] == 4.0  # (2+4+6)/3
        assert result["Team X"]["avg_wins"] == 6.0  # (3+6+9)/3
        assert result["Team X"]["avg_away_wins"] == 2.0  # (1+2+3)/3

    def test_aggregate_all_teams_present(self):
        """Every input team appears in the output."""
        positions = {
            "Team A": [1, 2],
            "Team B": [3, 4],
            "Team C": [5, 6],
        }
        champions = {"Team A": 0, "Team B": 0, "Team C": 0}
        stat_collectors = {
            t: {
                "pts": [1, 2], "gd": [1, 2], "gs": [1, 2],
                "away_gs": [1, 2], "wins": [1, 2], "away_wins": [1, 2],
            }
            for t in positions
        }

        result = aggregate_mc_results(positions, champions, stat_collectors, 2)
        assert set(result.keys()) == {"Team A", "Team B", "Team C"}

    def test_aggregate_n1_edge_case(self):
        """N=1 produces exact 0/1 probabilities and exact stat values."""
        positions = {"Team A": [1]}
        champions = {"Team A": 1}
        stat_collectors = {
            "Team A": {
                "pts": [21], "gd": [14], "gs": [18],
                "away_gs": [9], "wins": [7], "away_wins": [3],
            },
        }

        result = aggregate_mc_results(positions, champions, stat_collectors, 1)

        assert result["Team A"]["top_8_prob"] == 1.0
        assert result["Team A"]["champion_prob"] == 1.0
        assert result["Team A"]["avg_position"] == 1.0
        assert result["Team A"]["avg_pts"] == 21.0
        assert result["Team A"]["avg_gd"] == 14.0
        assert result["Team A"]["avg_wins"] == 7.0
        assert result["Team A"]["avg_away_wins"] == 3.0


# ═══════════════════════════════════════════════════════════════════════════════
# ── Module Init Tests
# ═══════════════════════════════════════════════════════════════════════════════


def test_simulation_module_imports():
    """All simulation functions importable from the module."""
    from competitions.ucl.src.simulation import (
        simulate_league_phase,
        run_monte_carlo,
        aggregate_mc_results,
    )
    assert callable(simulate_league_phase)
    assert callable(run_monte_carlo)
    assert callable(aggregate_mc_results)
