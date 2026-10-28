"""Format correctness tests for LaLiga double round-robin league (FMT-03, FMT-04, D-03)."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

from competitions.laliga.src.groups import compute_laliga_standings
from competitions.laliga.src.pipeline import fetch_live_data, load_fixtures
from competitions.laliga.src.schedule_generator import generate_berger_schedule

DATA_DIR = Path(__file__).parent.parent / "competitions" / "laliga" / "data"


def test_berger_generator_completeness():
    teams = [f"Team_{i:02d}" for i in range(20)]
    fixtures = generate_berger_schedule(teams, season_token="2026/27")

    assert len(fixtures) == 380

    by_matchday: dict[int, list[dict]] = {}
    for f in fixtures:
        by_matchday.setdefault(f["matchday"], []).append(f)

    assert len(by_matchday) == 38
    assert sorted(by_matchday.keys()) == list(range(1, 39))

    for md, m_list in by_matchday.items():
        assert len(m_list) == 10, f"Matchday {md} has {len(m_list)} matches, expected 10"
        teams_in_md = []
        for m in m_list:
            teams_in_md.extend([m["home_team"], m["away_team"]])
        assert len(teams_in_md) == 20
        assert len(set(teams_in_md)) == 20, f"Duplicate team found in matchday {md}"

    # Asserts every unordered pair meets twice (once A home, once B home)
    pair_counts: dict[tuple[str, str], int] = {}
    for f in fixtures:
        pair_counts[(f["home_team"], f["away_team"])] = pair_counts.get((f["home_team"], f["away_team"]), 0) + 1

    for i in range(20):
        for j in range(i + 1, 20):
            ta, tb = teams[i], teams[j]
            assert pair_counts.get((ta, tb)) == 1, f"Missing or duplicate fixture {ta} vs {tb}"
            assert pair_counts.get((tb, ta)) == 1, f"Missing or duplicate fixture {tb} vs {ta}"

    # Asserts every match has provenance == "derived" and schedule_source == "derived_fixtures"
    for f in fixtures:
        assert f["provenance"] == "derived"
        assert f["schedule_source"] == "derived_fixtures"


def test_laliga_shortfall_detection_and_derived_fixtures(tmp_path: Path):
    shutil.copy(DATA_DIR / "team_aliases.json", tmp_path / "team_aliases.json")
    aliases = json.loads((DATA_DIR / "team_aliases.json").read_text(encoding="utf-8"))
    canonical_teams = sorted(list(aliases.keys()))
    assert len(canonical_teams) == 20

    class MockProvider:
        def fetch_matches(self, competition_id=None, **kwargs):
            return [
                {
                    "match_id": f"real_match_{i}",
                    "home_team": canonical_teams[i * 2],
                    "away_team": canonical_teams[i * 2 + 1],
                    "round_number": 1,
                    "status": "scheduled",
                    "stage": "REGULAR_SEASON",
                }
                for i in range(10)
            ]

    res = fetch_live_data(tmp_path, provider=MockProvider())

    shortfall = res.get("shortfall")
    assert shortfall is not None
    assert shortfall["provider"] == "MockProvider"
    assert shortfall["expected"] == 380
    assert shortfall["actual"] == 10
    assert shortfall["missing"] == 370
    assert shortfall["schedule_complete"] is False

    saved_fixtures = load_fixtures(tmp_path, "2026/27")
    assert len(saved_fixtures) == 380

    real_fixtures = [f for f in saved_fixtures if f.get("provenance") != "derived"]
    derived_fixtures = [f for f in saved_fixtures if f.get("provenance") == "derived"]

    assert len(real_fixtures) == 10
    assert len(derived_fixtures) == 370

    for f in real_fixtures:
        assert f["status"] == "scheduled"
        assert f.get("provenance") != "derived"

    for f in derived_fixtures:
        assert f["provenance"] == "derived"
        assert f["schedule_source"] == "derived_fixtures"


def test_laliga_qualification_zones():
    teams = [f"Team_{i:02d}" for i in range(20)]
    standings = compute_laliga_standings({}, team_names=teams)
    assert len(standings) == 20

    expected_zones = {
        1: ("champion", "Champions"),
        2: ("ucl", "Champions League"),
        3: ("ucl", "Champions League"),
        4: ("ucl", "Champions League"),
        5: ("uel", "Europa League"),
        6: ("uecl", "Conference League"),
        7: ("safe", ""),
        8: ("safe", ""),
        9: ("safe", ""),
        10: ("safe", ""),
        11: ("safe", ""),
        12: ("safe", ""),
        13: ("safe", ""),
        14: ("safe", ""),
        15: ("safe", ""),
        16: ("safe", ""),
        17: ("safe", ""),
        18: ("relegation", "Relegation"),
        19: ("relegation", "Relegation"),
        20: ("relegation", "Relegation"),
    }

    for row in standings:
        pos = row["position"]
        expected_zone, expected_label = expected_zones[pos]
        assert row["zone"] == expected_zone, f"Position {pos} expected zone {expected_zone}, got {row['zone']}"
        assert row["zone_label"] == expected_label, (
            f"Position {pos} expected zone_label {expected_label}, got {row['zone_label']}"
        )


def test_laliga_20_teams_zero_baseline():
    teams = [f"Team_{i:02d}" for i in range(20)]
    standings = compute_laliga_standings({}, team_names=teams)

    assert len(standings) == 20
    for i, row in enumerate(standings, start=1):
        assert row["position"] == i
        assert row["played"] == 0
        assert row["points"] == 0
        assert row["goal_diff"] == 0
        assert row["wins"] == 0
        assert row["draws"] == 0
        assert row["losses"] == 0
        assert row["goals_for"] == 0
        assert row["goals_against"] == 0

        # Validate zone assignment
        if i == 1:
            assert row["zone"] == "champion"
            assert row["zone_label"] == "Champions"
        elif 2 <= i <= 4:
            assert row["zone"] == "ucl"
            assert row["zone_label"] == "Champions League"
        elif i == 5:
            assert row["zone"] == "uel"
            assert row["zone_label"] == "Europa League"
        elif i == 6:
            assert row["zone"] == "uecl"
            assert row["zone_label"] == "Conference League"
        elif 7 <= i <= 17:
            assert row["zone"] == "safe"
            assert row["zone_label"] == ""
        else:
            assert row["zone"] == "relegation"
            assert row["zone_label"] == "Relegation"
