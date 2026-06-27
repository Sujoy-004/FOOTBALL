"""Tests for the full tournament simulation pipeline."""

import json

import pytest

from src.knockout import (
    _build_round_map,
    _simulate_r32_resolved,
    run_full_simulation,
)

DATA_DIR = "data"


@pytest.fixture
def full_data():
    """Load production data for integration tests."""
    with open(f"{DATA_DIR}/teams.json", encoding="utf-8") as f:
        teams = json.load(f)
    with open(f"{DATA_DIR}/groups.json", encoding="utf-8") as f:
        groups = json.load(f)
    with open(f"{DATA_DIR}/bracket.json", encoding="utf-8") as f:
        bracket = json.load(f)
    with open(f"{DATA_DIR}/annex_c.json", encoding="utf-8") as f:
        annex_c = json.load(f)
    return teams, groups, bracket, annex_c


@pytest.fixture
def small_teams():
    return {
        "Argentina": {"elo": 2115},
        "Mexico": {"elo": 1850},
        "France": {"elo": 2063},
        "Nigeria": {"elo": 1830},
    }


class TestKnockoutBuildRoundMap:
    def test_skips_r32(self, full_data):
        """_build_round_map excludes R32 matches."""
        _, _, bracket, _ = full_data
        round_map = _build_round_map(bracket)
        assert "R32" not in round_map

    def test_includes_r16(self, full_data):
        """R16 matches are included in round_map."""
        _, _, bracket, _ = full_data
        round_map = _build_round_map(bracket)
        assert "R16" in round_map
        assert len(round_map["R16"]) == 8

    def test_includes_tpp(self, full_data):
        """TPP round is included in round_map."""
        _, _, bracket, _ = full_data
        round_map = _build_round_map(bracket)
        assert "TPP" in round_map

    def test_includes_final(self, full_data):
        """FINAL round is included in round_map."""
        _, _, bracket, _ = full_data
        round_map = _build_round_map(bracket)
        assert "FINAL" in round_map

    def test_exact_round_counts(self, full_data):
        """Verify exact match counts per round in round_map."""
        _, _, bracket, _ = full_data
        round_map = _build_round_map(bracket)
        assert len(round_map["R16"]) == 8
        assert len(round_map["QF"]) == 4
        assert len(round_map["SF"]) == 2
        assert len(round_map["TPP"]) == 1
        assert len(round_map["FINAL"]) == 1


class TestSimulateR32Resolved:
    def test_basic_simulation(self):
        """R32 resolved matchups produce winners."""
        r32_matchups = {
            "M73": {"match_id": "M73", "team_a": "Argentina", "team_b": "Mexico"},
            "M74": {"match_id": "M74", "team_a": "France", "team_b": "Nigeria"},
        }
        elo_ratings = {
            "Argentina": 2115,
            "Mexico": 1850,
            "France": 2063,
            "Nigeria": 1830,
        }
        import random
        rng = random.Random(42)
        result = _simulate_r32_resolved(r32_matchups, {}, elo_ratings, rng)
        assert len(result) == 2
        assert "M73" in result
        assert "M74" in result
        assert result["M73"] in ("Argentina", "Mexico")

    def test_respects_played(self):
        """Already-played R32 match winner is respected."""
        r32_matchups = {
            "M73": {"match_id": "M73", "team_a": "Argentina", "team_b": "Mexico"},
        }
        elo_ratings = {"Argentina": 2115, "Mexico": 1850}
        played = {"M73": {"winner": "Argentina"}}
        import random
        rng = random.Random(42)
        result = _simulate_r32_resolved(r32_matchups, played, elo_ratings, rng)
        assert result["M73"] == "Argentina"

    def test_deterministic_with_seed(self):
        """Same seed produces identical R32 results."""
        r32_matchups = {
            "M73": {"match_id": "M73", "team_a": "Argentina", "team_b": "Mexico"},
            "M74": {"match_id": "M74", "team_a": "France", "team_b": "Nigeria"},
        }
        elo_ratings = {
            "Argentina": 2115,
            "Mexico": 1850,
            "France": 2063,
            "Nigeria": 1830,
        }
        import random
        r1 = _simulate_r32_resolved(r32_matchups, {}, elo_ratings, random.Random(42))
        r2 = _simulate_r32_resolved(r32_matchups, {}, elo_ratings, random.Random(42))
        assert r1 == r2


class TestRunFullSimulation:
    def test_runs_with_production_data(self, full_data):
        """Full simulation runs without error on production data."""
        teams, groups, bracket, annex_c = full_data
        result = run_full_simulation(
            teams, groups, bracket, annex_c, {},
            iterations=100, seed=42,
        )
        assert len(result) == 48
        for team in result:
            assert set(result[team].keys()) == {"qf", "sf", "final", "champion"}

    def test_champion_probs_sum_to_one(self, full_data):
        """Champion probabilities sum to ~100%."""
        teams, groups, bracket, annex_c = full_data
        result = run_full_simulation(
            teams, groups, bracket, annex_c, {},
            iterations=1000, seed=42,
        )
        total = sum(p["champion"] for p in result.values())
        assert abs(total - 1.0) <= 0.001

    def test_deterministic_with_seed(self, full_data):
        """Same seed produces identical results."""
        teams, groups, bracket, annex_c = full_data
        r1 = run_full_simulation(
            teams, groups, bracket, annex_c, {},
            iterations=100, seed=42,
        )
        r2 = run_full_simulation(
            teams, groups, bracket, annex_c, {},
            iterations=100, seed=42,
        )
        assert r1 == r2

    def test_different_seeds_different(self, full_data):
        """Different seeds produce different results."""
        teams, groups, bracket, annex_c = full_data
        r1 = run_full_simulation(
            teams, groups, bracket, annex_c, {},
            iterations=100, seed=42,
        )
        r2 = run_full_simulation(
            teams, groups, bracket, annex_c, {},
            iterations=100, seed=99,
        )
        assert r1 != r2

    def test_probabilities_in_range(self, full_data):
        """All probabilities are between 0 and 1."""
        teams, groups, bracket, annex_c = full_data
        result = run_full_simulation(
            teams, groups, bracket, annex_c, {},
            iterations=100, seed=42,
        )
        for team in result:
            for key in ("qf", "sf", "final", "champion"):
                assert 0.0 <= result[team][key] <= 1.0
