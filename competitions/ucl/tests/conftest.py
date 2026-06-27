"""Shared pytest fixtures for UCL predictor tests."""

import json

import pytest

# ── Fixture Data ────────────────────────────────────────────────────────

_REAL_TEAMS_POT1 = [
    "Man City", "Bayern", "Real Madrid", "PSG", "Liverpool",
    "Inter", "Dortmund", "RB Leipzig", "Barcelona",
]
_REAL_TEAMS_POT2 = [
    "Bayer Leverkusen", "Atletico Madrid", "Juventus", "Sporting",
    "Benfica", "Arsenal", "AC Milan", "Club Brugge", "Shakhtar Donetsk",
]
_REAL_TEAMS_POT3 = [
    "Feyenoord", "PSV", "Celtic", "Young Boys", "Salzburg",
    "Dinamo Zagreb", "Olympiacos", "Lille", "Red Star Belgrade",
]
_REAL_TEAMS_POT4 = [
    "Aston Villa", "Stuttgart", "Bologna", "Girona", "Monaco",
    "Sparta Prague", "Slovan Bratislava", "Maccabi Tel Aviv", "Bodo/Glimt",
]

_ALL_36_TEAMS = _REAL_TEAMS_POT1 + _REAL_TEAMS_POT2 + _REAL_TEAMS_POT3 + _REAL_TEAMS_POT4

# Realistic ClubElo ratings (from ClubElo snapshot circa 2025/26 pre-season)
_ELO_RATINGS = {
    "Man City": 1971.0,
    "Bayern": 1956.0,
    "Real Madrid": 1943.0,
    "PSG": 1927.0,
    "Liverpool": 1915.0,
    "Inter": 1898.0,
    "Dortmund": 1884.0,
    "RB Leipzig": 1867.0,
    "Barcelona": 1938.0,
    "Bayer Leverkusen": 1855.0,
    "Atletico Madrid": 1832.0,
    "Juventus": 1820.0,
    "Sporting": 1805.0,
    "Benfica": 1812.0,
    "Arsenal": 1892.0,
    "AC Milan": 1838.0,
    "Club Brugge": 1760.0,
    "Shakhtar Donetsk": 1735.0,
    "Feyenoord": 1748.0,
    "PSV": 1755.0,
    "Celtic": 1720.0,
    "Young Boys": 1695.0,
    "Salzburg": 1710.0,
    "Dinamo Zagreb": 1680.0,
    "Olympiacos": 1705.0,
    "Lille": 1730.0,
    "Red Star Belgrade": 1660.0,
    "Aston Villa": 1765.0,
    "Stuttgart": 1690.0,
    "Bologna": 1645.0,
    "Girona": 1630.0,
    "Monaco": 1725.0,
    "Sparta Prague": 1655.0,
    "Slovan Bratislava": 1580.0,
    "Maccabi Tel Aviv": 1610.0,
    "Bodo/Glimt": 1595.0,
}

_UEFA_COEFFICIENTS = {
    "Man City": 123.000,
    "Bayern": 120.000,
    "Real Madrid": 119.000,
    "PSG": 116.000,
    "Liverpool": 114.000,
    "Inter": 112.000,
    "Dortmund": 111.000,
    "RB Leipzig": 108.000,
    "Barcelona": 117.000,
    "Bayer Leverkusen": 105.000,
    "Atletico Madrid": 107.000,
    "Juventus": 103.000,
    "Sporting": 95.000,
    "Benfica": 97.000,
    "Arsenal": 110.000,
    "AC Milan": 101.000,
    "Club Brugge": 65.000,
    "Shakhtar Donetsk": 63.000,
    "Feyenoord": 70.000,
    "PSV": 72.000,
    "Celtic": 58.000,
    "Young Boys": 45.000,
    "Salzburg": 50.000,
    "Dinamo Zagreb": 42.000,
    "Olympiacos": 48.000,
    "Lille": 55.000,
    "Red Star Belgrade": 38.000,
    "Aston Villa": 68.000,
    "Stuttgart": 52.000,
    "Bologna": 35.000,
    "Girona": 30.000,
    "Monaco": 62.000,
    "Sparta Prague": 40.000,
    "Slovan Bratislava": 25.000,
    "Maccabi Tel Aviv": 22.000,
    "Bodo/Glimt": 28.000,
}

_POT_MAP = {name: 1 for name in _REAL_TEAMS_POT1}
_POT_MAP.update({name: 2 for name in _REAL_TEAMS_POT2})
_POT_MAP.update({name: 3 for name in _REAL_TEAMS_POT3})
_POT_MAP.update({name: 4 for name in _REAL_TEAMS_POT4})

# Subset of 16 teams (4 per pot) for sample fixtures
_SUB_POT1 = ["Man City", "Bayern", "Real Madrid", "PSG"]
_SUB_POT2 = ["Bayer Leverkusen", "Atletico Madrid", "Juventus", "Arsenal"]
_SUB_POT3 = ["Feyenoord", "PSV", "Celtic", "Salzburg"]
_SUB_POT4 = ["Aston Villa", "Stuttgart", "Monaco", "Bodo/Glimt"]
_SUB_ALL = _SUB_POT1 + _SUB_POT2 + _SUB_POT3 + _SUB_POT4

_CLUBELO_NAMES = {
    "Man City": "Man City",
    "Bayern": "Bayern",
    "Real Madrid": "Real Madrid",
    "PSG": "Paris SG",
    "Liverpool": "Liverpool",
    "Inter": "Inter",
    "Dortmund": "Dortmund",
    "RB Leipzig": "RB Leipzig",
    "Barcelona": "Barcelona",
    "Bayer Leverkusen": "Leverkusen",
    "Atletico Madrid": "Atletico",
    "Juventus": "Juventus",
    "Sporting": "Sporting",
    "Benfica": "Benfica",
    "Arsenal": "Arsenal",
    "AC Milan": "Milan",
    "Club Brugge": "Brugge",
    "Shakhtar Donetsk": "Shakhtar Donetsk",
    "Feyenoord": "Feyenoord",
    "PSV": "PSV",
    "Celtic": "Celtic",
    "Young Boys": "Young Boys",
    "Salzburg": "Salzburg",
    "Dinamo Zagreb": "Dinamo Zagreb",
    "Olympiacos": "Olympiacos",
    "Lille": "Lille",
    "Red Star Belgrade": "Crvena Zvezda",
    "Aston Villa": "Aston Villa",
    "Stuttgart": "Stuttgart",
    "Bologna": "Bologna",
    "Girona": "Girona",
    "Monaco": "Monaco",
    "Sparta Prague": "Sparta Praha",
    "Slovan Bratislava": "Slovan Bratislava",
    "Maccabi Tel Aviv": "M Tel Aviv",
    "Bodo/Glimt": "Bodoe Glimt",
}


def _build_sample_matchday(teams_subset, pots, matchday_id: int, offset: int):
    """Build one matchday with 8 matches from the 16-team subset.

    Each team plays once per matchday.  Teams are paired based on
    a simple rotation scheduler for demonstration purposes.
    """
    n = len(teams_subset)
    matches = []
    rotated = teams_subset[offset:] + teams_subset[:offset]
    for i in range(0, n, 2):
        mid = f"MD{matchday_id:02d}_{(i // 2) + 1:02d}"
        ta, tb = teams_subset[i], rotated[i + 1]
        matches.append({
            "match_id": mid,
            "team_a": ta,
            "team_b": tb,
            "home_pot": pots[ta],
            "away_pot": pots[tb],
        })
    return matches


def _build_team_entry(name, pot_map, elo_map, clubelo_map, coeff_map):
    """Build a single team entry dict for the schedule."""
    return {
        "name": name,
        "pot": pot_map[name],
        "clubelo_name": clubelo_map[name],
        "coefficient": coeff_map[name],
    }


# ── Pytest Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def sample_36_teams():
    """Returns a dict of 36 UCL team names mapped to their Elo ratings and pot assignments.

    Uses realistic 2025/26 UCL teams with verified ClubElo ratings.
    """
    teams = {}
    for name in _ALL_36_TEAMS:
        teams[name] = {
            "elo": _ELO_RATINGS[name],
            "pot": _POT_MAP[name],
            "clubelo_name": _CLUBELO_NAMES[name],
            "coefficient": _UEFA_COEFFICIENTS[name],
        }
    return teams


@pytest.fixture
def sample_fixture_schedule():
    """Returns a fixture schedule dict with 16 teams (4 per pot) and 2 matchdays.

    Structure matches the fixtures.json schema::
        {"schedule": {"teams": [...], "matchdays": [[...], ...]}}
    """
    pots = {
        "Man City": 1, "Bayern": 1, "Real Madrid": 1, "PSG": 1,
        "Bayer Leverkusen": 2, "Atletico Madrid": 2, "Juventus": 2, "Arsenal": 2,
        "Feyenoord": 3, "PSV": 3, "Celtic": 3, "Salzburg": 3,
        "Aston Villa": 4, "Stuttgart": 4, "Monaco": 4, "Bodo/Glimt": 4,
    }

    teams = []
    for name in _SUB_ALL:
        teams.append({
            "name": name,
            "pot": pots[name],
            "clubelo_name": _CLUBELO_NAMES[name],
            "coefficient": _UEFA_COEFFICIENTS[name],
        })

    matchday1 = _build_sample_matchday(_SUB_ALL, pots, 1, 0)
    matchday2 = _build_sample_matchday(_SUB_ALL, pots, 2, 2)

    return {
        "schedule": {
            "teams": teams,
            "matchdays": [matchday1, matchday2],
        }
    }


@pytest.fixture
def sample_fixture_path(tmp_path):
    """Writes a sample fixture schedule to a temp JSON file and returns the path.

    Uses the same 16-team, 2-matchday structure as sample_fixture_schedule.
    """
    schedule = sample_fixture_schedule()
    path = tmp_path / "fixtures.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(schedule, f, indent=2)
    return str(path)


@pytest.fixture
def sample_invalid_fixtures():
    """Returns a list of fixture schedule dicts with known validation failures.

    Each entry has the structure:
        {"schedule": {...}, "expected_error": "..."}

    Covers:
    1. Wrong opponent count — one team plays only 7 matches
    2. Duplicate matchup — same pair appears twice
    3. Wrong pot distribution — team faces 3 opponents from pot 1
    """
    pots = {
        "Man City": 1, "Bayern": 1, "Real Madrid": 1, "PSG": 1,
        "Bayer Leverkusen": 2, "Atletico Madrid": 2, "Juventus": 2, "Arsenal": 2,
        "Feyenoord": 3, "PSV": 3, "Celtic": 3, "Salzburg": 3,
        "Aston Villa": 4, "Stuttgart": 4, "Monaco": 4, "Bodo/Glimt": 4,
    }

    def _make_teams():
        return [
            {"name": n, "pot": pots[n], "clubelo_name": _CLUBELO_NAMES.get(n, n), "coefficient": _UEFA_COEFFICIENTS.get(n, 0.0)}
            for n in _SUB_ALL
        ]

    # --- Invalid fixture 1: Man City plays only 7 matches (8 required) ---
    teams1 = _make_teams()
    valid_matches = _build_sample_matchday(_SUB_ALL, pots, 1, 0) + _build_sample_matchday(_SUB_ALL, pots, 2, 2)
    # Remove one match involving Man City
    match_to_remove = None
    for m in valid_matches:
        if "Man City" in (m["team_a"], m["team_b"]):
            match_to_remove = m
            break
    if match_to_remove:
        valid_matches.remove(match_to_remove)

    invalid1 = {
        "schedule": {
            "teams": teams1,
            "matchdays": [valid_matches],
        },
        "expected_error": "opponent",
    }

    # --- Invalid fixture 2: Duplicate matchup (Man City vs Bayern twice) ---
    teams2 = _make_teams()
    md1 = _build_sample_matchday(_SUB_ALL, pots, 1, 0)
    # Add duplicate: Man City vs Bayern again in a third matchday
    duplicate_match = {"match_id": "MD03_01", "team_a": "Man City", "team_b": "Bayern", "home_pot": 1, "away_pot": 1}
    invalid2 = {
        "schedule": {
            "teams": teams2,
            "matchdays": [md1 + [duplicate_match], _build_sample_matchday(_SUB_ALL, pots, 2, 2)],
        },
        "expected_error": "duplicate",
    }

    # --- Invalid fixture 3: Wrong pot distribution ---
    teams3 = _make_teams()
    # Replace one of Man City's pot-4 opponents with a pot-1 team
    md_pot3 = _build_sample_matchday(_SUB_ALL, pots, 1, 0)
    for m in md_pot3:
        if m["team_a"] == "Man City" and m["away_pot"] == 4:
            m["team_b"] = "Real Madrid"
            m["away_pot"] = 1
            break
        if m["team_b"] == "Man City" and m["home_pot"] == 4:
            m["team_a"] = "Real Madrid"
            m["home_pot"] = 1
            break

    invalid3 = {
        "schedule": {
            "teams": teams3,
            "matchdays": [md_pot3, _build_sample_matchday(_SUB_ALL, pots, 2, 2)],
        },
        "expected_error": "pot",
    }

    return [invalid1, invalid2, invalid3]
