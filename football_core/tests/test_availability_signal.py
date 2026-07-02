"""Tests for availability signal — team unavailability and match probability."""

import pytest

from football_core.signals.availability import (
    compute_team_unavailability,
    compute_availability_probability,
    compute_availability_signal_for_match,
    compute_availability_signal,
    POSITION_WEIGHTS,
)


class TestComputeTeamUnavailability:
    def test_all_available(self):
        players = [
            {"rating": 90.0, "position": "Forward", "availability": "available", "injury_risk": "Low"},
            {"rating": 85.0, "position": "Midfielder", "availability": "available", "injury_risk": "Low"},
        ]
        score = compute_team_unavailability(players)
        assert score == pytest.approx(0.0)

    def test_one_injured(self):
        players = [
            {"rating": 90.0, "position": "Forward", "availability": "injured", "injury_risk": "Low"},
            {"rating": 85.0, "position": "Midfielder", "availability": "available", "injury_risk": "Low"},
        ]
        score = compute_team_unavailability(players)
        assert score > 0.0
        assert score < 1.0

    def test_all_unavailable(self):
        players = [
            {"rating": 90.0, "position": "Forward", "availability": "injured", "injury_risk": "Low"},
            {"rating": 85.0, "position": "Midfielder", "availability": "suspended", "injury_risk": "Low"},
        ]
        score = compute_team_unavailability(players)
        assert score == pytest.approx(1.0)

    def test_high_injury_risk_counts_as_unavailable(self):
        players = [
            {"rating": 90.0, "position": "Forward", "availability": "available", "injury_risk": "High"},
            {"rating": 85.0, "position": "Midfielder", "availability": "available", "injury_risk": "Low"},
        ]
        score = compute_team_unavailability(players)
        assert score > 0.0

    def test_positional_weighting(self):
        gk_weight = POSITION_WEIGHTS.get("Goalkeeper", 1.0)
        forward_weight = POSITION_WEIGHTS.get("Forward", 1.0)
        assert gk_weight > forward_weight

    def test_no_players_returns_zero(self):
        score = compute_team_unavailability([])
        assert score == pytest.approx(0.0)

    def test_zero_rating_players(self):
        players = [
            {"rating": 0.0, "position": "", "availability": "injured", "injury_risk": "Low"},
        ]
        score = compute_team_unavailability(players)
        assert score == pytest.approx(0.0)


class TestComputeAvailabilityProbability:
    def test_equal_unavailability(self):
        p = compute_availability_probability(0.1, 0.1)
        assert p == pytest.approx(0.5)

    def test_home_more_available(self):
        p = compute_availability_probability(0.0, 0.3)
        assert p > 0.5

    def test_home_less_available(self):
        p = compute_availability_probability(0.3, 0.0)
        assert p < 0.5

    def test_custom_k(self):
        p = compute_availability_probability(0.0, 0.5, k=2.0)
        assert p > 0.5


class TestComputeAvailabilitySignalForMatch:
    def test_both_teams_have_players(self):
        player_data = {
            "France": [
                {"rating": 90.0, "position": "Forward", "availability": "available", "injury_risk": "Low"},
                {"rating": 85.0, "position": "Midfielder", "availability": "available", "injury_risk": "Low"},
            ],
            "Brazil": [
                {"rating": 88.0, "position": "Forward", "availability": "available", "injury_risk": "Low"},
            ],
        }
        result = compute_availability_signal_for_match("France", "Brazil", player_data)
        assert result["available"] is True
        assert 0 < result["probability"] < 1

    def test_missing_team(self):
        player_data = {"France": []}
        result = compute_availability_signal_for_match("France", "Brazil", player_data)
        assert result["available"] is False

    def test_no_data(self):
        result = compute_availability_signal_for_match("France", "Brazil", {})
        assert result["available"] is False


class TestComputeAvailabilitySignal:
    def test_group_matches(self):
        player_data = {
            "France": [{"rating": 90.0, "position": "Forward", "availability": "available", "injury_risk": "Low"}],
            "Brazil": [{"rating": 88.0, "position": "Forward", "availability": "available", "injury_risk": "Low"}],
        }
        groups = {
            "groups": {
                "A": {
                    "matches": [
                        {"match_id": "GS_A_01", "team_a": "France", "team_b": "Brazil"},
                    ]
                }
            }
        }
        result = compute_availability_signal(player_data, groups)
        assert "GS_A_01" in result["matches"]

    def test_cache_dict_structure(self):
        result = compute_availability_signal({}, {"groups": {}})
        assert "fetched_at" in result
        assert "expires_at" in result
        assert "matches" in result
