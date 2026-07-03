"""Shared pytest fixtures for UCL predictor tests."""

from dotenv import load_dotenv
import json
import os
import random
from datetime import datetime, timedelta

import pytest

load_dotenv()

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

# Subset of 16 teams (4 per pot) for minimal sample fixtures
_SUB_POT1 = ["Man City", "Bayern", "Real Madrid", "PSG"]
_SUB_POT2 = ["Bayer Leverkusen", "Atletico Madrid", "Juventus", "Arsenal"]
_SUB_POT3 = ["Feyenoord", "PSV", "Celtic", "Salzburg"]
_SUB_POT4 = ["Aston Villa", "Stuttgart", "Monaco", "Bodo/Glimt"]
_SUB_ALL = _SUB_POT1 + _SUB_POT2 + _SUB_POT3 + _SUB_POT4

# ── Path helpers ─────────────────────────────────────────────────────────

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


def _load_real_fixtures():
    """Load the full 36-team, 8-matchday fixture schedule from disk."""
    fixtures_path = os.path.join(_DATA_DIR, "fixtures.json")
    with open(fixtures_path) as f:
        return json.load(f)

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
    "Olympiacos": "Olympiakos",
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
    """Returns the real 36-team, 8-matchday fixture schedule loaded from fixtures.json.

    Structure matches the fixtures.json schema::
        {"schedule": {"teams": [...], "matchdays": [[...], ...]}}
    """
    return _load_real_fixtures()


@pytest.fixture
def sample_fixture_path(tmp_path, sample_fixture_schedule):
    """Writes the real fixture schedule to a temp JSON file and returns the path."""
    path = tmp_path / "fixtures.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sample_fixture_schedule, f, indent=2)
    return str(path)


@pytest.fixture
def sample_invalid_fixtures():
    """Returns a list of fixture schedule dicts with known validation failures.

    Each entry has the structure:
        {"schedule": {...}, "expected_error": "..."}

    Builds on top of the real 36-team schedule, then corrupts a copy for each
    failure case to minimize fixture generation code.

    Covers:
    1. Wrong opponent count — one team plays only 7 matches
    2. Duplicate matchup — same pair appears twice
    3. Wrong pot distribution — team faces 3 opponents from pot 1
    """
    import copy

    base = _load_real_fixtures()

    def _team_names(schedule):
        return [t["name"] for t in schedule["schedule"]["teams"]]

    def _flatten_matches(schedule):
        result = []
        for md in schedule["schedule"]["matchdays"]:
            result.extend(md)
        return result

    # --- Invalid fixture 1: Man City plays only 7 matches (8 required) ---
    invalid1 = copy.deepcopy(base)
    all_matches = _flatten_matches(invalid1)
    for m in all_matches:
        if "Man City" in (m["team_a"], m["team_b"]):
            # Remove from whichever matchday it belongs to
            for md in invalid1["schedule"]["matchdays"]:
                if m in md:
                    md.remove(m)
                    break
            break

    # --- Invalid fixture 2: Duplicate matchup ---
    invalid2 = copy.deepcopy(base)
    first_match = invalid2["schedule"]["matchdays"][0][0]
    dup = {
        "match_id": "DUPE_01",
        "team_a": first_match["team_a"],
        "team_b": first_match["team_b"],
        "home_pot": first_match["home_pot"],
        "away_pot": first_match["away_pot"],
    }
    invalid2["schedule"]["matchdays"].append([dup])

    # --- Invalid fixture 3: Wrong pot distribution ---
    invalid3 = copy.deepcopy(base)
    # Find Man City's first match and change opponent's pot to match own pot
    team_a_name = "Man City"
    for md in invalid3["schedule"]["matchdays"]:
        for m in md:
            if m["team_a"] == team_a_name and m["away_pot"] != 1:
                m["away_pot"] = 1  # Now 3 from pot 1 instead of 2
                break
        else:
            continue
        break

    return [
        {"schedule": invalid1["schedule"], "expected_error": "opponent"},
        {"schedule": invalid2["schedule"], "expected_error": "duplicate"},
        {"schedule": invalid3["schedule"], "expected_error": "pot"},
    ]


# ── Live API test marker ────────────────────────────────────────────────────


def pytest_addoption(parser):
    """Add a ``--live`` flag to run live ClubElo API tests."""
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="Run live ClubElo API integration tests",
    )


# ── Match simulation fixtures (Plan 02, Tasks 3 & 4) ──────────────────────


@pytest.fixture
def sample_elo_dict(sample_36_teams):
    """Returns a flat {team_name: elo} dict for all 36 teams.

    Useful for Monte Carlo tests that need elo ratings matching
    the full 36-team fixture schedule.
    """
    return {n: d["elo"] for n, d in sample_36_teams.items()}


@pytest.fixture
def sample_elo_ratings():
    """Returns Elo ratings for 4 sample teams."""
    return {
        "Man City": 1970.0,
        "Bayern": 1900.0,
        "Barcelona": 1850.0,
        "Slovan Bratislava": 1550.0,
    }


@pytest.fixture
def sample_match_results():
    """Returns a pre-built match results dict with 2 matches.

    Structure matches the output of ``simulate_swiss_matches()``.
    """
    return {
        "MD01_01": {
            "team_a": "Man City",
            "team_b": "Slovan Bratislava",
            "score_a": 4,
            "score_b": 0,
            "winner": "Man City",
            "yellow_cards_a": 1,
            "red_cards_a": 0,
            "yellow_cards_b": 2,
            "red_cards_b": 0,
        },
        "MD01_02": {
            "team_a": "Bayern",
            "team_b": "Barcelona",
            "score_a": 2,
            "score_b": 1,
            "winner": "Bayern",
            "yellow_cards_a": 0,
            "red_cards_a": 0,
            "yellow_cards_b": 1,
            "red_cards_b": 0,
        },
    }


@pytest.fixture
def sample_rng():
    """Returns a seeded ``random.Random(42)`` for deterministic tests."""
    return random.Random(42)


@pytest.fixture
def sample_uefa_coefficients():
    """Returns UEFA club coefficients for 4 sample teams."""
    return {
        "Man City": 123.0,
        "Bayern": 120.0,
        "Barcelona": 117.0,
        "Slovan Bratislava": 25.0,
    }


@pytest.fixture
def sample_standings_results():
    """Returns a pre-built 36-team standings list for zone classification tests.

    Teams are already sorted by position (1-36) with zone assignments.
    Only the first and last few are fully populated; middle entries are
    minimal stubs for position/zone checks.
    """
    teams = []
    for name in _ALL_36_TEAMS:
        teams.append({
            "team": name,
            "elo": _ELO_RATINGS[name],
        })
    # Sort by descending Elo to create a plausible ranking
    teams.sort(key=lambda t: -t["elo"])
    standings = []
    for i, t in enumerate(teams):
        pos = i + 1
        if pos <= 8:
            zone = "top_8"
        elif pos <= 24:
            zone = "playoff"
        else:
            zone = "eliminated"
        standings.append({
            "team": t["team"],
            "position": pos,
            "zone": zone,
            "pts": 0,
            "gd": 0,
            "gs": 0,
            "away_gs": 0,
            "wins": 0,
            "away_wins": 0,
            "opp_pts": 0,
            "opp_gd": 0,
            "opp_gs": 0,
            "conduct_score": 0,
            "uefa_coefficient": _UEFA_COEFFICIENTS.get(t["team"], 0.0),
            "elo": t["elo"],
        })
    return standings


# ── Monte Carlo test fixtures (Plan 03, Task 1) ─────────────────────────────


@pytest.fixture
def sample_full_fixture_path(tmp_path):
    """Writes the real fixtures.json to a temp path and returns the path.

    Uses the on-disk fixture data (36 teams, 8 matchdays, 144 matches)
    so tests that need the full schedule can load from a file path.
    """
    import json
    import os

    fixtures_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data",
        "fixtures.json",
    )
    dest = tmp_path / "fixtures.json"
    with open(fixtures_path) as src:
        data = json.load(src)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    return str(dest)


# ── Knockout test fixtures (Plan 02-01) ──────────────────────────────────


@pytest.fixture
def sample_playoff_pairings():
    """Returns the playoff pairings data for testing.

    Loads from the dedicated competition data file created
    alongside the implementation (exact filename chosen during
    implementation).
    """
    import json, os, glob
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    # Discover the playoff pairings file by convention
    pairings_files = glob.glob(os.path.join(data_dir, "*playoff*"))
    path = pairings_files[0] if pairings_files else os.path.join(data_dir, "playoff_pairings.json")
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def sample_bracket_rules():
    """Returns the bracket rules data for testing.

    Loads from the dedicated competition data file created
    alongside the implementation (exact filename chosen during
    implementation).
    """
    import json, os, glob
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    bracket_files = glob.glob(os.path.join(data_dir, "*bracket*"))
    path = bracket_files[0] if bracket_files else os.path.join(data_dir, "bracket_rules.json")
    with open(path) as f:
        return json.load(f)


@pytest.fixture
def sample_knockout_elos():
    """Returns Elo dict for 2 teams used in standalone tie tests."""
    return {"Man City": 1970.0, "Real Madrid": 1943.0}


@pytest.fixture
def sample_tie_standings():
    """Returns a minimal 24-entry standings list (positions 1-24) for playoff/bracket tests.

    Teams are sorted by descending Elo to create a plausible ranking.
    Only position, team, and zone fields are populated; tiebreaker
    stats are zeroed.
    """
    import copy
    from competitions.ucl.tests.conftest import _ALL_36_TEAMS, _ELO_RATINGS
    teams = [{"team": t, "elo": _ELO_RATINGS[t]} for t in _ALL_36_TEAMS]
    teams.sort(key=lambda t: -t["elo"])
    standings = []
    for i, t in enumerate(teams[:24]):
        pos = i + 1
        standings.append({
            "team": t["team"],
            "position": pos,
            "zone": "top_8" if pos <= 8 else "playoff",
            "pts": 0, "gd": 0, "gs": 0, "away_gs": 0,
            "wins": 0, "away_wins": 0, "opp_pts": 0, "opp_gd": 0,
            "opp_gs": 0, "conduct_score": 0, "uefa_coefficient": 0.0,
            "elo": t["elo"],
        })
    return standings


@pytest.fixture
def sample_playoff_standings():
    """Returns 36-team standings sorted by Elo for playoff round tests.

    Teams are ranked by descending Elo and assigned zones per standard
    UCL league phase rules: top_8 (1-8), playoff (9-24), eliminated (25-36).
    Only position, team, zone, and elo fields are substantive; tiebreaker
    stats are zeroed.
    """
    teams = [{"team": t, "elo": _ELO_RATINGS[t]} for t in _ALL_36_TEAMS]
    teams.sort(key=lambda t: -t["elo"])
    standings = []
    for i, t in enumerate(teams):
        pos = i + 1
        standings.append({
            "team": t["team"],
            "position": pos,
            "zone": "top_8" if pos <= 8 else ("playoff" if pos <= 24 else "eliminated"),
            "pts": 0, "gd": 0, "gs": 0, "away_gs": 0,
            "wins": 0, "away_wins": 0, "opp_pts": 0, "opp_gd": 0,
            "opp_gs": 0, "conduct_score": 0, "uefa_coefficient": 0.0,
            "elo": t["elo"],
        })
    return standings


@pytest.fixture
def sample_mc_output():
    """Returns a minimal pre-formatted MC output dict with 3 teams.

    Matches the D-06/D-07 output schema for testing aggregation
    format independently from simulation logic.
    """
    return {
        "snapshot_date": "2026-06-27",
        "n_iterations": 1000,
        "seed": 42,
        "teams": {
            "Man City": {
                "top_8_prob": 0.85,
                "playoff_prob": 0.13,
                "eliminated_prob": 0.02,
                "champion_prob": 0.12,
                "avg_position": 4.2,
                "avg_pts": 16.8,
                "avg_gd": 5.3,
                "avg_gs": 12.1,
                "avg_away_gs": 5.8,
                "avg_wins": 5.1,
                "avg_away_wins": 2.4,
            },
            "Bayern": {
                "top_8_prob": 0.78,
                "playoff_prob": 0.19,
                "eliminated_prob": 0.03,
                "champion_prob": 0.09,
                "avg_position": 5.1,
                "avg_pts": 15.9,
                "avg_gd": 4.8,
                "avg_gs": 11.5,
                "avg_away_gs": 5.3,
                "avg_wins": 4.8,
                "avg_away_wins": 2.1,
            },
            "Slovan Bratislava": {
                "top_8_prob": 0.01,
                "playoff_prob": 0.12,
                "eliminated_prob": 0.87,
                "champion_prob": 0.0001,
                "avg_position": 31.8,
                "avg_pts": 3.2,
                "avg_gd": -4.1,
                "avg_gs": 4.5,
                "avg_away_gs": 1.8,
                "avg_wins": 0.8,
                "avg_away_wins": 0.3,
            },
        },
    }


@pytest.fixture
def sample_playoff_winners():
    """Returns mock playoff winners for bracket construction tests.

    8 winners, one per playoff tie (1-8), using team names
    from the Elo-sorted playoff standings.
    """
    from competitions.ucl.tests.conftest import _ALL_36_TEAMS, _ELO_RATINGS
    teams = sorted(_ALL_36_TEAMS, key=lambda t: -_ELO_RATINGS[t])
    # Teams at positions 17-24 — these would be the playoff winners
    # (lower seeded teams advancing as upset examples)
    winners_pool = [teams[i] for i in range(16, 24)]
    return {i + 1: winners_pool[i] for i in range(8)}


@pytest.fixture
def sample_stage_collectors():
    """Returns per-team stage collector data for 3 teams over 10 iterations.

    Stage values: 0=eliminated, 1=playoff, 2=r16, 3=qf, 4=sf, 5=final, 6=champion
    """
    return {
        "Man City": [6, 6, 6, 5, 5, 6, 6, 5, 6, 6],       # champion 7/10, final 3/10
        "Bayern": [4, 4, 3, 4, 2, 4, 4, 3, 4, 4],          # sf 7/10, qf 2/10, r16 1/10
        "Slovan Bratislava": [0, 0, 0, 0, 1, 0, 0, 0, 1, 0],  # eliminated 8/10, playoff 2/10
    }


@pytest.fixture
def sample_knockout_stage_result():
    """Returns a minimal mock knockout_result for stage tracking tests.

    Simulates a tree where Man City wins and Bayern reaches SF.
    """
    return {
        "stage": {
            "Man City": "CHAMPION",
            "Real Madrid": "FINAL",
            "Bayern": "SF",
            "PSG": "SF",
            "Inter": "QF",
            "Dortmund": "QF",
            "RB Leipzig": "QF",
            "Barcelona": "QF",
            "Arsenal": "R16",
            "Bayer Leverkusen": "R16",
            "Juventus": "R16",
            "Atletico Madrid": "R16",
            "Sporting": "R16",
            "Benfica": "R16",
            "AC Milan": "R16",
            "Club Brugge": "R16",
            # Teams 17-24 (playoff losers) are NOT in stage dict
        },
        "champion": "Man City",
    }


@pytest.fixture
def sample_result():
    """Returns a populated SimulationResult with all 36 teams and full match data.

    Builds a realistic simulation result using pre-existing fixture data:
    - 36 teams sorted by Elo for standings
    - 8 playoff ties with mock two-legged tie results
    - 4 bracket rounds (R16, QF, SF, FINAL)
    - All 36 stage entries
    """
    from competitions.ucl.result import SimulationResult

    # ── Standings: 36 teams sorted by descending Elo ──
    ranked_teams = sorted(_ALL_36_TEAMS, key=lambda t: -_ELO_RATINGS[t])
    standings = []
    for i, name in enumerate(ranked_teams):
        pos = i + 1
        if pos <= 8:
            zone = "top_8"
        elif pos <= 24:
            zone = "playoff"
        else:
            zone = "eliminated"
        # Realistic stats: top teams score more, bottom teams less
        pts = max(18 - i * 0.45, 0)  # ~18 pts for pos 1, ~2 pts for pos 36
        gd = max(10 - i * 0.5, -8)
        gs = max(14 - i * 0.3, 3)
        standings.append({
            "team": name,
            "position": pos,
            "zone": zone,
            "pts": round(pts, 1),
            "gd": round(gd, 1),
            "gs": round(gs, 1),
        })

    # ── Teams: per-team probabilities from MC ──
    teams_data = {}
    for name in _ALL_36_TEAMS:
        elo = _ELO_RATINGS.get(name, 1500.0)
        # Scale probabilities by Elo strength
        strength = (elo - 1500.0) / 500.0  # 0.0 to ~0.94
        top_8_prob = max(0.0, min(0.95, strength * 0.9))
        playoff_prob = max(0.0, min(0.9, (1.0 - top_8_prob) * 0.8))
        eliminated_prob = max(0.0, 1.0 - top_8_prob - playoff_prob)
        champion_prob = max(0.0, strength * 0.12)
        stage_final_prob = max(0.0, champion_prob * 1.5)
        stage_sf_prob = max(0.0, stage_final_prob * 1.4)
        stage_qf_prob = max(0.0, stage_sf_prob * 1.3)
        teams_data[name] = {
            "top_8_prob": round(top_8_prob, 3),
            "playoff_prob": round(playoff_prob, 3),
            "eliminated_prob": round(eliminated_prob, 3),
            "champion_prob": round(champion_prob, 4),
            "stage_final_prob": round(stage_final_prob, 4),
            "stage_sf_prob": round(stage_sf_prob, 4),
            "stage_qf_prob": round(stage_qf_prob, 4),
            "avg_position": round(37.0 - strength * 18.0, 1),
            "avg_pts": round(strength * 18.0, 1),
            "avg_gd": round(strength * 6.0 - 4.0, 1),
            "avg_gs": round(strength * 8.0 + 2.0, 1),
        }

    # ── Playoff ties: 8 ties with mock two-legged results ──
    # Playoff participants are positions 9-24
    playoff_teams_9_16 = ranked_teams[8:16]   # seeded (9-16)
    playoff_teams_17_24 = ranked_teams[16:24]  # challengers (17-24)
    playoff_ties = {}
    playoff_winners = {}
    for tie_num in range(1, 9):
        seeded = playoff_teams_9_16[tie_num - 1]
        challenger = playoff_teams_17_24[tie_num - 1]
        mock_result = {
            "winner": seeded,
            "loser": challenger,
            "aggregate_a": 2,
            "aggregate_b": 1,
            "agg_a_full": 2,
            "agg_b_full": 1,
            "leg1": {"team_a": challenger, "team_b": seeded, "score_a": 1, "score_b": 2},
            "leg2": {"team_a": challenger, "team_b": seeded, "score_a": 1, "score_b": 0},
            "et_played": False,
            "et_a": 0,
            "et_b": 0,
            "penalties_played": False,
            "penalty_a": 0,
            "penalty_b": 0,
        }
        playoff_ties[tie_num] = mock_result
        playoff_winners[tie_num] = seeded

    # ── Bracket rounds: R16 → QF → SF → FINAL ──
    bracket_rounds = {}

    # R16: 8 matches — top 8 seeds vs playoff winners
    r16_matches = []
    for match_num in range(8):
        seed_team = ranked_teams[match_num]  # top 8
        pw_team = playoff_winners[match_num + 1]
        r16_matches.append({
            "match_id": f"r16_{match_num + 1:02d}",
            "team_a": seed_team,
            "team_b": pw_team,
            "winner": seed_team,
            "result": {
                "winner": seed_team,
                "loser": pw_team,
                "aggregate_a": 3,
                "aggregate_b": 1,
                "agg_a_full": 3,
                "agg_b_full": 1,
                "leg1": {"team_a": seed_team, "team_b": pw_team, "score_a": 2, "score_b": 0},
                "leg2": {"team_a": seed_team, "team_b": pw_team, "score_a": 1, "score_b": 1},
                "et_played": False,
                "et_a": 0,
                "et_b": 0,
                "penalties_played": False,
                "penalty_a": 0,
                "penalty_b": 0,
            },
        })
    bracket_rounds["R16"] = r16_matches

    # QF: 4 matches — top 4 R16 winners vs bottom 4 R16 winners
    qf_matches = []
    for match_num in range(4):
        team_a = ranked_teams[match_num]
        team_b = ranked_teams[match_num + 4]
        qf_matches.append({
            "match_id": f"qf_{match_num + 1:02d}",
            "team_a": team_a,
            "team_b": team_b,
            "winner": team_a,
            "result": {
                "winner": team_a,
                "loser": team_b,
                "aggregate_a": 2,
                "aggregate_b": 0,
                "agg_a_full": 2,
                "agg_b_full": 0,
                "leg1": {"team_a": team_a, "team_b": team_b, "score_a": 1, "score_b": 0},
                "leg2": {"team_a": team_a, "team_b": team_b, "score_a": 1, "score_b": 0},
                "et_played": False,
                "et_a": 0,
                "et_b": 0,
                "penalties_played": False,
                "penalty_a": 0,
                "penalty_b": 0,
            },
        })
    bracket_rounds["QF"] = qf_matches

    # SF: 2 matches
    sf_matches = []
    for match_num in range(2):
        team_a = ranked_teams[match_num]
        team_b = ranked_teams[match_num + 2]
        sf_matches.append({
            "match_id": f"sf_{match_num + 1:02d}",
            "team_a": team_a,
            "team_b": team_b,
            "winner": team_a,
            "result": {
                "winner": team_a,
                "loser": team_b,
                "aggregate_a": 3,
                "aggregate_b": 2,
                "agg_a_full": 3,
                "agg_b_full": 2,
                "leg1": {"team_a": team_a, "team_b": team_b, "score_a": 2, "score_b": 1},
                "leg2": {"team_a": team_a, "team_b": team_b, "score_a": 1, "score_b": 1},
                "et_played": False,
                "et_a": 0,
                "et_b": 0,
                "penalties_played": False,
                "penalty_a": 0,
                "penalty_b": 0,
            },
        })
    bracket_rounds["SF"] = sf_matches

    # FINAL: 1 match
    champion = "Man City"
    final_match = {
        "match_id": "final_01",
        "team_a": ranked_teams[0],
        "team_b": ranked_teams[1],
        "winner": champion,
        "result": {
            "winner": champion,
            "loser": ranked_teams[1],
            "is_final": True,
            "score_a": 2,
            "score_b": 1,
        },
    }
    bracket_rounds["FINAL"] = [final_match]

    # ── Stages: all 36 teams mapped to stage strings ──
    stages = {}
    for i, name in enumerate(ranked_teams):
        pos = i + 1
        if pos >= 25:
            stages[name] = "eliminated"
        elif pos >= 17:
            stages[name] = "playoff"
        elif name == "Man City":
            stages[name] = "champion"
        elif name in ("Bayern", "Real Madrid"):
            stages[name] = "final"
        elif pos <= 4:
            stages[name] = "sf"
        elif pos <= 8:
            stages[name] = "qf"
        else:
            stages[name] = "r16"

    return SimulationResult(
        snapshot_date="2026-06-28",
        n_iterations=10000,
        seed=42,
        standings=standings,
        teams=teams_data,
        playoff_ties=playoff_ties,
        playoff_winners=playoff_winners,
        bracket_rounds=bracket_rounds,
        bracket_champion=champion,
        stages=stages,
    )


# ── BSD fixture data fixtures (Plan 05) ─────────────────────────────────────────


@pytest.fixture
def bsd_response_data():
    """Returns the BSD API snapshot response for offline unit tests."""
    fixtures_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests", "fixtures", "bsd_response.json",
    )
    with open(fixtures_path) as f:
        return json.load(f)


@pytest.fixture
def sample_36_teams_data():
    """Returns list of team dicts matching the Team dataclass fields for all 36 teams."""
    return [
        {
            "name": name,
            "pot": _POT_MAP[name],
            "clubelo_name": _CLUBELO_NAMES[name],
            "coefficient": _UEFA_COEFFICIENTS[name],
        }
        for name in _ALL_36_TEAMS
    ]


@pytest.fixture
def sample_cached_fixtures(tmp_path, sample_fixture_schedule):
    """Pre-seeds a valid BSD cache file and returns the cache directory path.

    Writes a cache dict with ``expires_at`` 2 hours in the future and
    the full fixture schedule serialised via dataclasses.asdict().
    """
    from dataclasses import asdict
    from datetime import timezone
    from football_core.provider import Team, Match, FixtureSchedule

    schedule_dict = sample_fixture_schedule["schedule"]
    teams = [Team(**t) for t in schedule_dict["teams"]]
    matchdays = []
    for md in schedule_dict["matchdays"]:
        matches = [Match(**m) for m in md]
        matchdays.append(matches)
    schedule = FixtureSchedule(teams=teams, matchdays=matchdays)

    cache_data = {
        "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        "cached_at": datetime.now(timezone.utc).isoformat(),
        "schedule": asdict(schedule),
    }

    cache_path = tmp_path / "cached_fixtures.json"
    with open(cache_path, "w") as f:
        json.dump(cache_data, f, indent=2)
    return tmp_path


# ── Signal fixtures (Phase 7) ──────────────────────────────────────────────


@pytest.fixture
def sample_match_data():
    """Returns a single match dict matching the Match schema."""
    return {
        "match_id": "MD01_01",
        "team_a": "Manchester City",
        "team_b": "Bayern Munich",
        "home_pot": 1,
        "away_pot": 1,
        "event_date": "2026-09-15T19:00:00+00:00",
    }


@pytest.fixture
def sample_prediction_context():
    """Returns a PredictionContext with sample Elo ratings."""
    from football_core.signal import PredictionContext

    return PredictionContext(
        fixtures=[],
        elo_ratings={
            "Manchester City": 2100.0,
            "Bayern Munich": 2050.0,
            "Real Madrid": 2080.0,
            "Liverpool": 2030.0,
        },
        played_results=[],
        team_aliases={},
        squad_values={},
    )


@pytest.fixture
def sample_match_with_odds_data(sample_match_data):
    """Like sample_match_data but with BSD odds fields."""
    return {**sample_match_data,
        "odds_home": 2.10,
        "odds_draw": 3.40,
        "odds_away": 3.80,
    }


class _MockMatchResultProvider:
    """Minimal stub implementing MatchResultProvider for tests."""

    def __init__(self, results: list[dict], default_return: list | None = None):
        self._results = results
        self._default = default_return or []

    def get_team_results(
        self, team: str, before_date: str, limit: int = 10
    ) -> list[dict]:
        filtered = [
            r
            for r in self._results
            if (r.get("team_a") == team or r.get("team_b") == team)
            and r.get("event_date", "") < before_date
        ]
        return sorted(filtered, key=lambda r: r.get("event_date", ""), reverse=True)[
            :limit
        ]


@pytest.fixture
def sample_match_result_provider():
    """Returns a _MockMatchResultProvider with 5 pre-built results."""
    return _MockMatchResultProvider([
        {
            "match_id": "PREV_01",
            "team_a": "Manchester City",
            "team_b": "Arsenal",
            "event_date": "2026-09-01T19:00:00+00:00",
            "home_score": 3, "away_score": 0,
            "winner": "Manchester City", "is_draw": False,
        },
        {
            "match_id": "PREV_02",
            "team_a": "Chelsea",
            "team_b": "Manchester City",
            "event_date": "2026-08-25T19:00:00+00:00",
            "home_score": 1, "away_score": 2,
            "winner": "Manchester City", "is_draw": False,
        },
        {
            "match_id": "PREV_03",
            "team_a": "Manchester City",
            "team_b": "Liverpool",
            "event_date": "2026-08-18T19:00:00+00:00",
            "home_score": 1, "away_score": 1,
            "winner": None, "is_draw": True,
        },
        {
            "match_id": "PREV_04",
            "team_a": "Bayern Munich",
            "team_b": "Dortmund",
            "event_date": "2026-09-02T19:00:00+00:00",
            "home_score": 3, "away_score": 1,
            "winner": "Bayern Munich", "is_draw": False,
        },
        {
            "match_id": "PREV_05",
            "team_a": "Leverkusen",
            "team_b": "Bayern Munich",
            "event_date": "2026-08-26T19:00:00+00:00",
            "home_score": 2, "away_score": 2,
            "winner": None, "is_draw": True,
        },
    ])


@pytest.fixture
def empty_result_provider():
    """Returns a _MockMatchResultProvider with no results."""
    return _MockMatchResultProvider([])


# ── Validation suite fixtures (Phase 9, Plan 02) ────────────────────────────


@pytest.fixture
def seasons_data():
    """Returns 4 synthetic UCL seasons for validation testing.

    Each season has 8 matchdays with 3-4 matches each (reduced for test speed).
    Uses a subset of 8 teams from the full 36-team pool.
    """
    teams = _SUB_ALL[:8]  # 8 teams for fast test execution
    n_matchdays = 8
    seasons: dict[str, dict] = {}

    for season_num in range(1, 5):
        season_id = f"Y{2022 + season_num}"
        matches: list[dict] = []
        standings: list[dict] = []

        rng = random.Random(season_num * 42)
        total_played = 0
        team_wins: dict[str, int] = {t: 0 for t in teams}
        team_draws: dict[str, int] = {t: 0 for t in teams}
        team_pts: dict[str, int] = {t: 0 for t in teams}
        team_gd: dict[str, int] = {t: 0 for t in teams}
        team_gs: dict[str, int] = {t: 0 for t in teams}
        team_games: dict[str, int] = {t: 0 for t in teams}

        for md_idx in range(n_matchdays):
            # Each matchday: pair up teams for n_teams/2 matches
            shuffled = list(teams)
            rng.shuffle(shuffled)
            for pair_idx in range(0, len(shuffled), 2):
                if pair_idx + 1 >= len(shuffled):
                    break
                ta, tb = shuffled[pair_idx], shuffled[pair_idx + 1]
                score_a = rng.randint(0, 4)
                score_b = rng.randint(0, 4)
                mid = f"season{season_num}_MD{md_idx + 1:02d}_{pair_idx // 2 + 1:02d}"

                if score_a > score_b:
                    winner, is_draw = ta, False
                elif score_b > score_a:
                    winner, is_draw = tb, False
                else:
                    winner, is_draw = None, True

                matches.append({
                    "match_id": mid,
                    "team_a": ta,
                    "team_b": tb,
                    "winner": winner,
                    "is_draw": is_draw,
                    "home_score": score_a,
                    "away_score": score_b,
                })

                total_played += 1
                team_games[ta] += 1
                team_games[tb] += 1
                team_gs[ta] += score_a
                team_gs[tb] += score_b
                team_gd[ta] += score_a - score_b
                team_gd[tb] += score_b - score_a

                if is_draw:
                    team_draws[ta] += 1
                    team_draws[tb] += 1
                    team_pts[ta] += 1
                    team_pts[tb] += 1
                elif winner == ta:
                    team_wins[ta] += 1
                    team_pts[ta] += 3
                else:
                    team_wins[tb] += 1
                    team_pts[tb] += 3

        # Build standings sorted by points, then GD
        sorted_teams = sorted(
            teams,
            key=lambda t: (-team_pts[t], -team_gd[t], -team_gs[t]),
        )
        for pos, team in enumerate(sorted_teams, 1):
            standings.append({
                "team": team,
                "position": pos,
                "zone": "top_8" if pos <= 8 else "playoff",
                "pts": team_pts[team],
                "gd": team_gd[team],
                "gs": team_gs[team],
                "wins": team_wins[team],
                "draws": team_draws[team],
                "elo": 1500.0 + (8 - pos) * 50.0,
            })

        seasons[season_id] = {
            "matches": matches,
            "teams": list(teams),
            "standings": standings,
        }

    return seasons


@pytest.fixture
def replay_matchdays():
    """Returns 3 matchdays of synthetic match data for replay validation tests.

    8 teams, 4 matches per matchday, with deterministic results.
    """
    teams = _SUB_ALL[:8]
    matchdays: list[list[dict]] = []
    rng = random.Random(99)

    for md_idx in range(3):
        shuffled = list(teams)
        rng.shuffle(shuffled)
        md_matches: list[dict] = []
        for pair_idx in range(0, len(shuffled), 2):
            if pair_idx + 1 >= len(shuffled):
                break
            ta, tb = shuffled[pair_idx], shuffled[pair_idx + 1]
            score_a = rng.randint(0, 3)
            score_b = rng.randint(0, 3)
            mid = f"replay_MD{md_idx + 1:02d}_{pair_idx // 2 + 1:02d}"

            if score_a > score_b:
                winner, is_draw = ta, False
            elif score_b > score_a:
                winner, is_draw = tb, False
            else:
                winner, is_draw = None, True

            md_matches.append({
                "match_id": mid,
                "team_a": ta,
                "team_b": tb,
                "winner": winner,
                "is_draw": is_draw,
                "home_score": score_a,
                "away_score": score_b,
            })
        matchdays.append(md_matches)

    return matchdays
