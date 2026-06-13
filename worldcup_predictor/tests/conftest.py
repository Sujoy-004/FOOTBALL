"""Shared pytest fixtures for World Cup predictor tests."""

import pytest


@pytest.fixture
def sample_teams():
    """Returns a dict of 5 test teams with Elo ratings."""
    return {
        "Argentina": {"elo": 2115},
        "France": {"elo": 2063},
        "Nigeria": {"elo": 1830},
        "Mexico": {"elo": 1850},
        "Japan": {"elo": 1900},
    }


@pytest.fixture
def sample_bracket():
    """Returns a list of 4 matches with a valid R16→QF→SF DAG structure."""
    return [
        {"match_id": "R16_1", "round": "R16", "team_a": "Argentina", "team_b": "Nigeria", "source_matches": None, "winner": None},
        {"match_id": "R16_2", "round": "R16", "team_a": "France", "team_b": "Mexico", "source_matches": None, "winner": None},
        {"match_id": "R16_3", "round": "R16", "team_a": "Brazil", "team_b": "Japan", "source_matches": None, "winner": None},
        {"match_id": "R16_4", "round": "R16", "team_a": "Spain", "team_b": "Senegal", "source_matches": None, "winner": None},
        {"match_id": "QF_1", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["R16_1", "R16_2"], "winner": None},
        {"match_id": "QF_2", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["R16_3", "R16_4"], "winner": None},
        {"match_id": "SF_1", "round": "SF", "team_a": None, "team_b": None, "source_matches": ["QF_1", "QF_2"], "winner": None},
    ]


@pytest.fixture
def sample_played():
    """Returns an empty played matches dict."""
    return {}
