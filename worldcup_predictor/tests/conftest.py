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


@pytest.fixture
def sample_group_matches_results():
    """Returns a pre-built simulated match results dict for Group A.

    Structure matches the output of simulate_group_matches() — 6 matches
    with deterministic fixed scores for testing standings computation.
    """
    return {
        "A": {
            "GS_A_01": {
                "team_a": "Mexico",
                "team_b": "South Africa",
                "score_a": 2,
                "score_b": 1,
                "winner": "Mexico",
                "yellow_cards_a": 0,
                "red_cards_a": 0,
                "yellow_cards_b": 0,
                "red_cards_b": 0,
            },
            "GS_A_02": {
                "team_a": "Mexico",
                "team_b": "South Korea",
                "score_a": 1,
                "score_b": 1,
                "winner": None,
                "yellow_cards_a": 0,
                "red_cards_a": 0,
                "yellow_cards_b": 0,
                "red_cards_b": 0,
            },
            "GS_A_03": {
                "team_a": "Mexico",
                "team_b": "Czech Republic",
                "score_a": 3,
                "score_b": 0,
                "winner": "Mexico",
                "yellow_cards_a": 0,
                "red_cards_a": 0,
                "yellow_cards_b": 0,
                "red_cards_b": 0,
            },
            "GS_A_04": {
                "team_a": "South Africa",
                "team_b": "South Korea",
                "score_a": 0,
                "score_b": 2,
                "winner": "South Korea",
                "yellow_cards_a": 0,
                "red_cards_a": 0,
                "yellow_cards_b": 0,
                "red_cards_b": 0,
            },
            "GS_A_05": {
                "team_a": "South Africa",
                "team_b": "Czech Republic",
                "score_a": 1,
                "score_b": 0,
                "winner": "South Africa",
                "yellow_cards_a": 0,
                "red_cards_a": 0,
                "yellow_cards_b": 0,
                "red_cards_b": 0,
            },
            "GS_A_06": {
                "team_a": "South Korea",
                "team_b": "Czech Republic",
                "score_a": 2,
                "score_b": 1,
                "winner": "South Korea",
                "yellow_cards_a": 0,
                "red_cards_a": 0,
                "yellow_cards_b": 0,
                "red_cards_b": 0,
            },
        }
    }


@pytest.fixture
def sample_groups():
    """Returns a minimal groups.json-like dict with just Group A.

    Contains 4 teams and 6 matches with null winners, matching the
    structure consumed by simulate_group_matches().
    """
    return {
        "groups": {
            "A": {
                "teams": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
                "matches": [
                    {"match_id": "GS_A_01", "team_a": "Mexico", "team_b": "South Africa", "winner": None, "score_a": None, "score_b": None},
                    {"match_id": "GS_A_02", "team_a": "Mexico", "team_b": "South Korea", "winner": None, "score_a": None, "score_b": None},
                    {"match_id": "GS_A_03", "team_a": "Mexico", "team_b": "Czech Republic", "winner": None, "score_a": None, "score_b": None},
                    {"match_id": "GS_A_04", "team_a": "South Africa", "team_b": "South Korea", "winner": None, "score_a": None, "score_b": None},
                    {"match_id": "GS_A_05", "team_a": "South Africa", "team_b": "Czech Republic", "winner": None, "score_a": None, "score_b": None},
                    {"match_id": "GS_A_06", "team_a": "South Korea", "team_b": "Czech Republic", "winner": None, "score_a": None, "score_b": None},
                ],
            }
        }
    }


@pytest.fixture
def sample_elo():
    """Returns Elo ratings for the sample group's 4 teams."""
    return {"Mexico": 1850.0, "South Africa": 1700.0, "South Korea": 1650.0, "Czech Republic": 1468.0}
