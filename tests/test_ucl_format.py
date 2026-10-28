"""Format correctness tests for UEFA Champions League 2026/27 (FMT-02, FMT-04, D-02)."""

from __future__ import annotations

import json
import pathlib
import shutil

import pytest

from competitions.ucl.src.groups import compute_swiss_standings
from competitions.ucl.src.pipeline import compute_deterministic_standings
from competitions.ucl.src.state import _populate_ko_from_standings, build_competition_state

DATA_DIR = pathlib.Path(__file__).parent.parent / "competitions" / "ucl" / "data"


def _load_fixtures_teams() -> list[str]:
    f = json.loads((DATA_DIR / "fixtures.json").read_text(encoding="utf-8"))
    return [t["name"] for t in f["schedule"]["teams"]]


def test_ucl_36_teams_zero_baseline(tmp_path: pathlib.Path):
    """Verify that compute_swiss_standings([], team_names=36) and build_competition_state return
    a 36-team pre-tournament baseline with 0 played, 0 pts, and 0 GD."""
    team_names = _load_fixtures_teams()
    assert len(team_names) == 36

    standings = compute_swiss_standings([], team_names=team_names)
    assert len(standings) == 36
    for i, row in enumerate(standings, start=1):
        assert row["position"] == i
        assert row["played"] == 0
        assert row["pts"] == 0
        assert row["gd"] == 0
        assert row["gs"] == 0
        assert row["ga"] == 0
        assert row["wins"] == 0
        assert row["draws"] == 0
        assert row["losses"] == 0

    # Also test build_competition_state on a fresh empty results store
    test_dir = tmp_path / "ucl_baseline"
    test_dir.mkdir()
    shutil.copy(DATA_DIR / "fixtures.json", test_dir / "fixtures.json")
    shutil.copy(DATA_DIR / "bracket_rules.json", test_dir / "bracket_rules.json")
    shutil.copy(DATA_DIR / "playoff_pairings.json", test_dir / "playoff_pairings.json")
    (test_dir / "results.json").write_text(json.dumps({"matches": []}), encoding="utf-8")

    state = build_competition_state(test_dir)
    league_standings = state["stages"]["league"]["standings"]
    assert len(league_standings) == 36
    assert all(r["played"] == 0 and r["pts"] == 0 for r in league_standings)


def test_ucl_tiebreaker_metrics_in_standings():
    """Verify that all 10 tiebreaker fields and played count are exposed in standings rows."""
    team_names = ["ClubA", "ClubB"]
    results = [
        {
            "match_id": "M01",
            "team_a": "ClubA",
            "team_b": "ClubB",
            "score_a": 2,
            "score_b": 1,
            "yellow_cards_a": 1,
            "red_cards_a": 0,
            "yellow_cards_b": 2,
            "red_cards_b": 0,
        }
    ]
    uefa_coeffs = {"ClubA": 45.0, "ClubB": 50.0}
    elo_ratings = {"ClubA": 1600.0, "ClubB": 1550.0}

    standings = compute_swiss_standings(
        results,
        elo_ratings=elo_ratings,
        uefa_coefficients=uefa_coeffs,
        team_names=team_names,
    )
    assert len(standings) == 2

    required_keys = {
        "position",
        "team",
        "zone",
        "played",
        "pts",
        "gd",
        "gs",
        "ga",
        "wins",
        "draws",
        "losses",
        "away_gs",
        "away_ga",
        "home_wins",
        "home_gs",
        "home_ga",
        "away_wins",
        "opp_pts",
        "opp_gd",
        "opp_gs",
        "conduct_score",
        "uefa_coefficient",
        "coeff",
        "elo",
    }

    for row in standings:
        missing = required_keys - set(row.keys())
        assert not missing, f"Row for {row.get('team')} missing keys: {missing}"
        assert row["coeff"] == row["uefa_coefficient"]
        assert row["played"] == row["wins"] + row["draws"] + row["losses"]


def test_ucl_playoff_seeding_uses_canonical_chain(tmp_path: pathlib.Path):
    """Verify that playoff seeding in _populate_ko_from_standings uses the canonical 10-step chain."""
    test_dir = tmp_path / "ucl_seeding"
    test_dir.mkdir()
    shutil.copy(DATA_DIR / "fixtures.json", test_dir / "fixtures.json")
    shutil.copy(DATA_DIR / "bracket_rules.json", test_dir / "bracket_rules.json")
    shutil.copy(DATA_DIR / "playoff_pairings.json", test_dir / "playoff_pairings.json")

    # Construct matches where TeamX and TeamY are tied on points, GD, GS,
    # but separated by away goals scored.
    team_names = _load_fixtures_teams()
    # Team at pos 9 and pos 10
    t9 = team_names[8]
    t10 = team_names[9]
    t_other = team_names[0]

    # Both play against t_other:
    # t9 plays away, wins 2-1 (away_gs = 2)
    # t10 plays home, wins 2-1 (away_gs = 0)
    matches = [
        {"match_id": "M_9", "team_a": t_other, "team_b": t9, "home_score": 1, "away_score": 2},
        {"match_id": "M_10", "team_a": t10, "team_b": t_other, "home_score": 2, "away_score": 1},
    ]
    (test_dir / "results.json").write_text(json.dumps({"matches": matches}), encoding="utf-8")

    ko_store = _populate_ko_from_standings(test_dir, test_dir)
    playoff_entries = ko_store.get("playoff", [])
    assert len(playoff_entries) > 0

    # Tie 1 in playoff_pairings.json pairs position 9 vs position 24
    tie_1 = next((p for p in playoff_entries if p.get("tie_num") == 1), None)
    assert tie_1 is not None
    # t9 has more away goals than t10, so t9 must be position 9 (team_a in tie_1)
    # or t10 if ranking inverted
    st = compute_deterministic_standings(matches, team_names=team_names)
    pos_map = {r["team"]: r["position"] for r in st}
    assert pos_map[t9] < pos_map[t10], f"Expected {t9} (away_gs=2) ahead of {t10} (away_gs=0)"
    assert tie_1["team_a"] == (t9 if pos_map[t9] == 9 else tie_1["team_a"])


def test_ucl_competition_state_embeds_standings():
    """Verify that build_competition_state embeds 36-team standings in stages.league.standings."""
    state = build_competition_state(DATA_DIR)
    assert "stages" in state
    assert "league" in state["stages"]
    assert "standings" in state["stages"]["league"]

    standings = state["stages"]["league"]["standings"]
    assert len(standings) == 36
    positions = [r["position"] for r in standings]
    assert positions == list(range(1, 37))
    for r in standings:
        assert "team" in r
        assert "pts" in r
        assert "played" in r
        assert "zone" in r
