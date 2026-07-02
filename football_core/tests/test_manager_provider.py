"""Tests for football_core.providers.manager — manager data parsing."""

from football_core.providers.manager import parse_managers, ManagerProfile


class TestParseManagers:
    def test_empty_list(self):
        result = parse_managers([])
        assert result == {}

    def test_single_manager(self):
        raw = [
            {
                "name": "Didier Deschamps",
                "current_team": {"name": "France"},
                "id": 1,
                "win_pct": 0.65,
                "avg_goals_scored": 2.1,
                "avg_goals_conceded": 0.8,
                "avg_xg_for": 2.0,
                "avg_xg_against": 0.7,
                "clean_sheet_pct": 0.45,
                "btts_pct": 0.35,
                "over_25_pct": 0.55,
                "avg_possession": 58.0,
                "preferred_formation": "4-3-3",
                "formations_used": ["4-3-3", "4-2-3-1", "3-4-3"],
                "team_style": "balanced",
                "pressing_intensity": "Medium",
                "defensive_line": "High",
                "profile": "attacking",
            }
        ]
        result = parse_managers(raw)
        assert "France" in result
        profile = result["France"]
        assert profile.name == "Didier Deschamps"
        assert profile.win_pct == 0.65
        assert profile.clean_sheet_pct == 0.45
        assert profile.preferred_formation == "4-3-3"
        assert len(profile.formations_used) == 3

    def test_team_as_string(self):
        raw = [
            {
                "name": "Lionel Scaloni",
                "current_team": "Argentina",
                "win_pct": 0.7,
            }
        ]
        result = parse_managers(raw)
        assert "Argentina" in result
        assert result["Argentina"].name == "Lionel Scaloni"

    def test_unknown_team_skipped(self):
        raw = [{"name": "Unknown", "win_pct": 0.5}]
        result = parse_managers(raw)
        assert result == {}

    def test_missing_fields_default_to_zero(self):
        raw = [{"name": "Test", "current_team": {"name": "Testland"}}]
        result = parse_managers(raw)
        assert result["Testland"].win_pct == 0.0
        assert result["Testland"].avg_xg_against == 0.0
        assert result["Testland"].clean_sheet_pct == 0.0


class TestManagerProfile:
    def test_profile_creation(self):
        p = ManagerProfile(name="Test", team="Testland", win_pct=0.6)
        assert p.name == "Test"
        assert p.team == "Testland"
        assert p.win_pct == 0.6

    def test_default_values(self):
        p = ManagerProfile(name="X", team="Y")
        assert p.win_pct == 0.0
        assert p.formations_used == []
        assert p.team_style == ""
