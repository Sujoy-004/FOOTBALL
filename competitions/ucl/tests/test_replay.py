"""Tests for replay mode: played_matches injection."""

from __future__ import annotations

import random

import pytest

from competitions.ucl.src.simulation import (
    aggregate_mc_results,
    run_monte_carlo,
    simulate_league_phase,
)


class TestPlayedMatchesInjection:
    """Verify played_matches override works correctly."""

    def test_single_played_match_injected(
        self, sample_fixture_schedule, sample_elo_dict, sample_rng,
    ):
        played = {("Man City", "Bayern"): (5, 0)}
        standings = simulate_league_phase(
            sample_fixture_schedule, sample_elo_dict, sample_rng,
            played_matches=played,
        )
        city_entry = next(s for s in standings if s["team"] == "Man City")
        bayern_entry = next(s for s in standings if s["team"] == "Bayern")
        assert city_entry["gs"] >= 5
        assert bayern_entry["gs"] >= 0
        assert city_entry["gd"] >= 5

    def test_replay_mode_mc_output(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        played = {("Man City", "Bayern"): (3, 1)}
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=5, seed=42,
            played_matches=played,
        )
        assert "teams" in result
        assert result["n_iterations"] == 5
        assert "snapshot_date" in result
        assert len(result["teams"]) == 36

    def test_all_matches_played(
        self, sample_fixture_schedule, sample_elo_dict, sample_rng,
    ):
        fixtures_schedule = sample_fixture_schedule["schedule"]
        played = {}
        for md in fixtures_schedule["matchdays"]:
            for match in md:
                played[(match["team_a"], match["team_b"])] = (1, 0)
        standings = simulate_league_phase(
            sample_fixture_schedule, sample_elo_dict, sample_rng,
            played_matches=played,
        )
        for entry in standings:
            if entry["team"] in [t["name"] for t in fixtures_schedule["teams"]]:
                assert entry["wins"] == 4
                assert entry["pts"] == 12
                assert entry["gs"] == 4

    def test_bidirectional_lookup(
        self, sample_fixture_schedule, sample_elo_dict, sample_rng,
    ):
        played = {("Bayern", "Man City"): (2, 1)}
        standings = simulate_league_phase(
            sample_fixture_schedule, sample_elo_dict, sample_rng,
            played_matches=played,
        )
        city_entry = next(s for s in standings if s["team"] == "Man City")
        bayern_entry = next(s for s in standings if s["team"] == "Bayern")
        assert city_entry["gd"] <= -1
        assert bayern_entry["gd"] >= 1


class TestPlayedMatchesDeterminism:
    """Verify played_matches doesn't break deterministic behavior."""

    def test_same_seed_same_replay_output(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        played = {("Man City", "Bayern"): (1, 1)}
        result1 = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=5, seed=42,
            played_matches=played,
        )
        result2 = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=5, seed=42,
            played_matches=played,
        )
        assert result1["teams"] == result2["teams"]

    def test_played_matches_immutable_during_mc(
        self, sample_fixture_schedule, sample_elo_dict,
    ):
        played = {("Man City", "Bayern"): (3, 0)}
        before_keys = set(played.keys())
        _ = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=10, seed=42,
            played_matches=played,
        )
        assert set(played.keys()) == before_keys


class TestReplayDataLoading:
    """Tests for ReplayMatchResultProvider."""

    def test_loads_replay_json(self, tmp_path):
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider
        import json
        data = {"matches": [
            {"team_a": "Man City", "team_b": "Bayern",
             "home_score": 3, "away_score": 1},
            {"team_a": "Real Madrid", "team_b": "PSG",
             "home_score": 2, "away_score": 0},
        ]}
        path = tmp_path / "replay.json"
        with open(path, "w") as f:
            json.dump(data, f)
        provider = ReplayMatchResultProvider(str(path))
        result = provider.load()
        assert ("Man City", "Bayern") in result
        assert result[("Man City", "Bayern")] == (3, 1)
        assert ("Bayern", "Man City") in result
        assert result[("Bayern", "Man City")] == (3, 1)

    def test_missing_file_raises(self):
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider
        with pytest.raises(FileNotFoundError):
            ReplayMatchResultProvider("/nonexistent/path.json").load()

    def test_protocol_runtime_checkable(self):
        from football_core.provider import MatchResultProvider
        from competitions.ucl.src.result_provider import ReplayMatchResultProvider, BSDMatchResultProvider
        assert isinstance(ReplayMatchResultProvider("dummy"), MatchResultProvider)
        assert isinstance(BSDMatchResultProvider("key", {}, {}), MatchResultProvider)
