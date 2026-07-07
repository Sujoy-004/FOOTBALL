"""Tests for elo_updater.py — incremental Elo updates and ClubElo sync edge cases."""

from unittest.mock import patch

import pytest

from competitions.ucl.src.elo_updater import apply_elo_update, sync_elo_from_clubelo


class TestApplyEloUpdate:

    def setup_method(self):
        self.elo_ratings = {"Arsenal": 1850.0, "Chelsea": 1720.0}
        self.elo_applied = []

    def test_home_win_updates_elo(self):
        match = {"match_id": "M1", "home_team": "Arsenal", "away_team": "Chelsea",
                 "home_score": 2, "away_score": 0, "winner": "Arsenal"}
        result = apply_elo_update(match, self.elo_ratings, self.elo_applied)
        assert result is not None
        assert result["delta_home"] > 0
        assert result["delta_away"] < 0
        assert self.elo_ratings["Arsenal"] > 1850.0
        assert self.elo_ratings["Chelsea"] < 1720.0
        assert "M1" in self.elo_applied

    def test_away_win_updates_elo(self):
        match = {"match_id": "M2", "home_team": "Arsenal", "away_team": "Chelsea",
                 "home_score": 1, "away_score": 3, "winner": "Chelsea"}
        result = apply_elo_update(match, self.elo_ratings, self.elo_applied)
        assert result is not None
        assert result["delta_away"] > 0
        assert "M2" in self.elo_applied

    def test_draw_updates_elo(self):
        match = {"match_id": "M3", "home_team": "Arsenal", "away_team": "Chelsea",
                 "home_score": 1, "away_score": 1, "winner": None, "is_draw": True}
        result = apply_elo_update(match, self.elo_ratings, self.elo_applied)
        assert result is not None
        assert "M3" in self.elo_applied

    def test_missing_team_returns_none(self):
        match = {"match_id": "M4", "home_team": "Arsenal", "away_team": "NonExistent",
                 "home_score": 2, "away_score": 0, "winner": "Arsenal"}
        result = apply_elo_update(match, self.elo_ratings, self.elo_applied)
        assert result is None
        assert "M4" not in self.elo_applied

    def test_already_applied_returns_none(self):
        self.elo_applied.append("M5")
        match = {"match_id": "M5", "home_team": "Arsenal", "away_team": "Chelsea",
                 "home_score": 2, "away_score": 0, "winner": "Arsenal"}
        result = apply_elo_update(match, self.elo_ratings, self.elo_applied)
        assert result is None

    def test_goal_difference_impact(self):
        match_blowout = {"match_id": "M6", "home_team": "Arsenal", "away_team": "Chelsea",
                         "home_score": 5, "away_score": 0, "winner": "Arsenal"}
        match_narrow = {"match_id": "M7", "home_team": "Arsenal", "away_team": "Chelsea",
                        "home_score": 1, "away_score": 0, "winner": "Arsenal"}
        self.elo_ratings["Arsenal"] = 1850.0
        self.elo_ratings["Chelsea"] = 1720.0
        elo_before = dict(self.elo_ratings)
        result_blowout = apply_elo_update(match_blowout, self.elo_ratings, self.elo_applied)
        self.elo_ratings["Arsenal"] = 1850.0
        self.elo_ratings["Chelsea"] = 1720.0
        result_narrow = apply_elo_update(match_narrow, self.elo_ratings, [])
        assert abs(result_blowout["delta_home"]) > abs(result_narrow["delta_home"])

    def test_elo_delta_calculation(self):
        match = {"match_id": "M8", "home_team": "Arsenal", "away_team": "Chelsea",
                 "home_score": 2, "away_score": 0, "winner": "Arsenal"}
        result = apply_elo_update(match, self.elo_ratings, self.elo_applied)
        assert "elo_before" in result["home"]
        assert "elo_after" in result["home"]
        assert abs(result["delta_home"] - (result["home"]["elo_after"] - result["home"]["elo_before"])) < 0.01


class TestSyncEloFromClubelo:

    def test_network_failure_returns_empty(self):
        with patch("competitions.ucl.src.elo_updater.fetch_eloratings_tsv", return_value=None):
            corrections = sync_elo_from_clubelo({"Arsenal": {"elo": 1850.0}}, [], None)
        assert corrections == []

    def test_drift_tolerance_ignored(self):
        teams = {"Arsenal": {"elo": 1850.0}}
        tsv = "1\tArsenal\tEngland\t1852.0\n"
        with patch("competitions.ucl.src.elo_updater.fetch_eloratings_tsv", return_value=tsv):
            with patch("competitions.ucl.src.elo_updater.parse_eloratings_tsv",
                       return_value=[("Arsenal", 1852.0)]):
                with patch("competitions.ucl.src.elo_updater.apply_graduated_correction",
                           return_value=[]):
                    corrections = sync_elo_from_clubelo(teams, [], None)
        assert corrections == []
