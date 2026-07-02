"""Tests for manager effect signal — rating computation and match probability."""

import pytest

from football_core.signals.manager_effect import (
    compute_manager_rating,
    compute_manager_probability,
    compute_manager_signal_for_match,
    compute_manager_signal,
    FORMATION_BONUS_PER, STYLE_MODIFIERS,
)


class TestComputeManagerRating:
    def test_only_win_pct(self):
        profile = {"win_pct": 0.6, "formations_used": [], "team_style": "balanced"}
        rating = compute_manager_rating(profile)
        assert rating == pytest.approx(0.6)

    def test_with_formation_bonus(self):
        profile = {"win_pct": 0.6, "formations_used": ["4-3-3", "4-2-3-1"], "team_style": "balanced"}
        rating = compute_manager_rating(profile)
        assert rating == pytest.approx(0.6 + 2 * FORMATION_BONUS_PER)

    def test_attacking_style_modifier(self):
        profile = {"win_pct": 0.5, "formations_used": [], "team_style": "attacking"}
        rating = compute_manager_rating(profile)
        assert rating == pytest.approx(0.5 + STYLE_MODIFIERS["attacking"])

    def test_defensive_style_modifier(self):
        profile = {"win_pct": 0.5, "formations_used": [], "team_style": "defensive"}
        rating = compute_manager_rating(profile)
        assert rating == pytest.approx(0.5 + STYLE_MODIFIERS["defensive"])

    def test_missing_fields_default(self):
        profile = {}
        rating = compute_manager_rating(profile)
        assert rating == pytest.approx(0.0)

    def test_non_list_formations(self):
        profile = {"win_pct": 0.5, "formations_used": "4-3-3", "team_style": "balanced"}
        rating = compute_manager_rating(profile)
        assert rating == pytest.approx(0.5)


class TestComputeManagerProbability:
    def test_equal_ratings(self):
        p = compute_manager_probability(0.5, 0.5)
        assert p == pytest.approx(0.5)

    def test_home_better(self):
        p = compute_manager_probability(0.7, 0.3)
        assert p > 0.5

    def test_away_better(self):
        p = compute_manager_probability(0.3, 0.7)
        assert p < 0.5

    def test_custom_k(self):
        p = compute_manager_probability(0.6, 0.4, k=3.0)
        assert p > 0.5


class TestComputeManagerSignalForMatch:
    def test_both_teams_have_data(self):
        manager_data = {
            "France": {"win_pct": 0.65, "formations_used": ["4-3-3"], "team_style": "balanced"},
            "Brazil": {"win_pct": 0.60, "formations_used": ["4-3-3"], "team_style": "attacking"},
        }
        result = compute_manager_signal_for_match("France", "Brazil", manager_data)
        assert result["available"] is True
        assert 0 < result["probability"] < 1

    def test_missing_team(self):
        manager_data = {"France": {"win_pct": 0.65, "formations_used": [], "team_style": "balanced"}}
        result = compute_manager_signal_for_match("France", "Brazil", manager_data)
        assert result["available"] is False

    def test_no_data(self):
        result = compute_manager_signal_for_match("France", "Brazil", {})
        assert result["available"] is False


class TestComputeManagerSignal:
    def test_group_matches(self):
        manager_data = {
            "France": {"win_pct": 0.65, "formations_used": [], "team_style": "balanced"},
            "Brazil": {"win_pct": 0.60, "formations_used": [], "team_style": "balanced"},
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
        result = compute_manager_signal(manager_data, groups)
        assert "GS_A_01" in result["matches"]

    def test_cache_dict_structure(self):
        result = compute_manager_signal({}, {"groups": {}})
        assert "fetched_at" in result
        assert "expires_at" in result
        assert "matches" in result
