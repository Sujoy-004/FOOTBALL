"""Tests for football_core.providers.player — player data parsing."""

from football_core.providers.player import parse_players, PlayerProfile


class TestParsePlayers:
    def test_empty_list(self):
        result = parse_players([])
        assert result == {}

    def test_single_player(self):
        raw = [
            {
                "name": "Kylian Mbappe",
                "team": {"name": "France"},
                "position": "Forward",
                "rating": 91.0,
                "availability": "available",
                "injury_risk": "Low",
                "market_value_eur": 180000000.0,
            }
        ]
        result = parse_players(raw)
        assert "France" in result
        assert len(result["France"]) == 1
        player = result["France"][0]
        assert player.name == "Kylian Mbappe"
        assert player.rating == 91.0
        assert player.availability == "available"
        assert player.injury_risk == "Low"

    def test_single_player_with_team_map(self):
        raw = [
            {
                "name": "Kylian Mbappe",
                "national_team_id": 10,
                "position": "Forward",
                "rating": 91.0,
                "availability": "available",
                "injury_risk": "Low",
                "market_value_eur": 180000000.0,
            }
        ]
        team_map = {10: "France"}
        result = parse_players(raw, team_map=team_map)
        assert "France" in result
        assert len(result["France"]) == 1
        player = result["France"][0]
        assert player.name == "Kylian Mbappe"
        assert player.rating == 91.0
        assert player.availability == "available"

    def test_multiple_teams(self):
        raw = [
            {"name": "A", "team": {"name": "France"}, "rating": 90.0},
            {"name": "B", "team": {"name": "France"}, "rating": 85.0},
            {"name": "C", "team": {"name": "Brazil"}, "rating": 88.0},
        ]
        result = parse_players(raw)
        assert len(result["France"]) == 2
        assert len(result["Brazil"]) == 1

    def test_multiple_teams_with_team_map(self):
        raw = [
            {"name": "A", "national_team_id": 1, "rating": 90.0},
            {"name": "B", "national_team_id": 1, "rating": 85.0},
            {"name": "C", "national_team_id": 2, "rating": 88.0},
        ]
        team_map = {1: "France", 2: "Brazil"}
        result = parse_players(raw, team_map=team_map)
        assert len(result["France"]) == 2
        assert len(result["Brazil"]) == 1

    def test_unknown_team_skipped(self):
        raw = [{"name": "Orphan", "rating": 50.0}]
        result = parse_players(raw)
        assert result == {}

    def test_unknown_team_skipped_with_team_map(self):
        raw = [{"name": "Orphan", "national_team_id": 999, "rating": 50.0}]
        team_map = {1: "France"}
        result = parse_players(raw, team_map=team_map)
        assert result == {}

    def test_missing_fields_default(self):
        raw = [{"name": "X", "team": {"name": "Test"}}]
        result = parse_players(raw)
        assert result["Test"][0].rating == 0.0
        assert result["Test"][0].availability == "available"
        assert result["Test"][0].injury_risk == "Low"


class TestPlayerProfile:
    def test_profile_creation(self):
        p = PlayerProfile(name="X", team="Y", position="GK", rating=85.0)
        assert p.name == "X"
        assert p.team == "Y"
        assert p.position == "GK"
        assert p.rating == 85.0

    def test_default_values(self):
        p = PlayerProfile(name="X", team="Y")
        assert p.availability == "available"
        assert p.injury_risk == "Low"
        assert p.market_value_eur == 0.0
