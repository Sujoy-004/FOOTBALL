"""Tests for defensive quality signal — rating computation and match probability."""

import pytest

from football_core.signals.defensive_quality import (
    compute_defensive_rating,
    compute_defensive_probability,
    compute_defensive_signal_for_match,
    compute_defensive_signal,
    DEFAULT_CS_WEIGHT, DEFAULT_XGA_WEIGHT, DEFAULT_MAX_XGA,
)


class TestComputeDefensiveRating:
    def test_perfect_defense(self):
        profile = {"clean_sheet_pct": 1.0, "avg_xg_against": 0.0}
        rating = compute_defensive_rating(profile)
        assert rating == pytest.approx(1.0)

    def test_porous_defense(self):
        profile = {"clean_sheet_pct": 0.0, "avg_xg_against": 3.0}
        rating = compute_defensive_rating(profile)
        assert rating == pytest.approx(0.0)

    def test_mixed(self):
        profile = {"clean_sheet_pct": 0.5, "avg_xg_against": 1.5}
        rating = compute_defensive_rating(profile)
        expected = DEFAULT_CS_WEIGHT * 0.5 + DEFAULT_XGA_WEIGHT * (1.0 - 1.5 / DEFAULT_MAX_XGA)
        assert rating == pytest.approx(expected)

    def test_xga_above_max_saturates(self):
        profile = {"clean_sheet_pct": 0.0, "avg_xg_against": 5.0}
        rating = compute_defensive_rating(profile)
        assert rating == pytest.approx(0.0)

    def test_missing_fields_default_neutral(self):
        profile = {}
        rating = compute_defensive_rating(profile)
        assert rating == pytest.approx(0.5)


class TestComputeDefensiveProbability:
    def test_equal_ratings(self):
        p = compute_defensive_probability(0.5, 0.5)
        assert p == pytest.approx(0.5)

    def test_home_better(self):
        p = compute_defensive_probability(0.8, 0.2)
        assert p > 0.5

    def test_away_better(self):
        p = compute_defensive_probability(0.2, 0.8)
        assert p < 0.5

    def test_extreme_difference(self):
        p = compute_defensive_probability(1.0, 0.0)
        assert p > 0.88

    def test_custom_k(self):
        p_default = compute_defensive_probability(0.6, 0.4)
        p_sharper = compute_defensive_probability(0.6, 0.4, k=5.0)
        assert p_sharper > p_default


class TestComputeDefensiveSignalForMatch:
    def test_both_teams_have_manager_data(self):
        manager_data = {
            "France": {"clean_sheet_pct": 0.5, "avg_xg_against": 1.0},
            "Brazil": {"clean_sheet_pct": 0.3, "avg_xg_against": 1.5},
        }
        result = compute_defensive_signal_for_match("France", "Brazil", manager_data)
        assert result["available"] is True
        assert 0 < result["probability"] < 1

    def test_missing_team(self):
        manager_data = {"France": {"clean_sheet_pct": 0.5, "avg_xg_against": 1.0}}
        result = compute_defensive_signal_for_match("France", "Brazil", manager_data)
        assert result["available"] is False
        assert result["probability"] is None

    def test_no_manager_data(self):
        result = compute_defensive_signal_for_match("France", "Brazil", {})
        assert result["available"] is False


class TestComputeDefensiveSignal:
    def test_group_matches(self):
        manager_data = {"France": {"clean_sheet_pct": 0.5, "avg_xg_against": 1.0}}
        groups = {
            "groups": {
                "A": {
                    "matches": [
                        {"match_id": "GS_A_01", "team_a": "France", "team_b": "Brazil"},
                    ]
                }
            }
        }
        result = compute_defensive_signal(manager_data, groups)
        assert "GS_A_01" in result["matches"]

    def test_bracket_matches(self):
        manager_data = {
            "France": {"clean_sheet_pct": 0.5, "avg_xg_against": 1.0},
            "Brazil": {"clean_sheet_pct": 0.3, "avg_xg_against": 1.5},
        }
        groups = {"groups": {}}
        bracket = [
            {"match_id": "M73", "team_a": "France", "team_b": "Brazil"},
        ]
        result = compute_defensive_signal(manager_data, groups, bracket=bracket)
        assert "M73" in result["matches"]
        assert result["matches"]["M73"]["available"] is True

    def test_cache_dict_structure(self):
        result = compute_defensive_signal({}, {"groups": {}})
        assert "fetched_at" in result
        assert "expires_at" in result
        assert "matches" in result
