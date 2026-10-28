"""Format correctness tests for World Cup 2026 (FMT-01, FMT-04, D-01, D-04)."""

from __future__ import annotations

import json
import pathlib

import pytest

from competitions.worldcup.src.bracket import compute_full_bracket
from competitions.worldcup.src.groups import (
    compute_standings,
    rank_third_placed,
    resolve_r32_matchups,
    select_advancers,
)
from competitions.worldcup.src.knockout import resolve_knockout_slot_teams
from competitions.worldcup.src.overview import compute_real_standings

DATA_DIR = pathlib.Path(__file__).parent.parent / "competitions" / "worldcup" / "data"


def _load(filename: str) -> dict:
    return json.loads((DATA_DIR / filename).read_text(encoding="utf-8"))


def test_wc_48_teams_zero_baseline():
    """Assert all 12 groups render 4 teams each (48 teams total) with 0 played/pts when empty."""
    groups_data = _load("groups.json")
    teams = _load("teams.json")
    groups = groups_data.get("groups", groups_data)

    standings = compute_real_standings(groups, {}, teams)

    assert len(standings) == 48, f"Expected 48 teams in pre-tournament standings, got {len(standings)}"
    by_group: dict[str, list[dict]] = {}
    for row in standings:
        by_group.setdefault(row["group"], []).append(row)

    expected_groups = [chr(ord("A") + i) for i in range(12)]  # Groups A through L
    assert sorted(by_group.keys()) == expected_groups

    for gl, rows in by_group.items():
        assert len(rows) == 4, f"Group {gl} must have 4 teams, got {len(rows)}"
        positions = [r["position"] for r in rows]
        assert positions == [1, 2, 3, 4], f"Group {gl} positions must be 1..4, got {positions}"
        for r in rows:
            assert r["played"] == 0, f"Expected played=0 for {r['team']}, got {r['played']}"
            assert r["pts"] == 0, f"Expected pts=0 for {r['team']}, got {r['pts']}"
            assert r["gd"] == 0, f"Expected gd=0 for {r['team']}, got {r['gd']}"
            assert r["gs"] == 0, f"Expected gs=0 for {r['team']}, got {r['gs']}"
            assert r["ga"] == 0, f"Expected ga=0 for {r['team']}, got {r['ga']}"


def test_wc_official_tiebreakers():
    """Verify that H2H results, goal difference, conduct score, and Elo break ties deterministically."""
    groups_data = {
        "A": {
            "teams": ["Alpha", "Beta", "Gamma", "Delta"],
            "matches": [
                {"match_id": "M_AB", "team_a": "Alpha", "team_b": "Beta"},
                {"match_id": "M_CD", "team_a": "Gamma", "team_b": "Delta"},
                {"match_id": "M_AC", "team_a": "Alpha", "team_b": "Gamma"},
                {"match_id": "M_BD", "team_a": "Beta", "team_b": "Delta"},
                {"match_id": "M_AD", "team_a": "Alpha", "team_b": "Delta"},
                {"match_id": "M_BC", "team_a": "Beta", "team_b": "Gamma"},
            ],
        }
    }

    # Case 1: H2H head-to-head points
    # Alpha beats Beta 2-1. Both beat Gamma and Delta. Both have 6 pts (out of 3 matches, say).
    # Specifically:
    # Alpha beats Beta (2-1)
    # Alpha beats Delta (1-0), loses to Gamma (0-1) -> 6 pts (2 wins, 1 loss)
    # Beta beats Gamma (1-0), beats Delta (1-0) -> 6 pts (2 wins, 1 loss)
    # Alpha has H2H win over Beta, so Alpha must rank above Beta.
    played_h2h = {
        "M_AB": {"team_a": "Alpha", "team_b": "Beta", "home_score": 2, "away_score": 1, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_AC": {"team_a": "Alpha", "team_b": "Gamma", "home_score": 0, "away_score": 1, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_AD": {"team_a": "Alpha", "team_b": "Delta", "home_score": 1, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_BC": {"team_a": "Beta", "team_b": "Gamma", "home_score": 1, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_BD": {"team_a": "Beta", "team_b": "Delta", "home_score": 1, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_CD": {"team_a": "Gamma", "team_b": "Delta", "home_score": 0, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
    }
    teams = {
        "Alpha": {"elo": 1500},
        "Beta": {"elo": 1500},
        "Gamma": {"elo": 1500},
        "Delta": {"elo": 1500},
    }

    st_h2h = compute_real_standings(groups_data, played_h2h, teams)
    assert st_h2h[0]["team"] == "Alpha"
    assert st_h2h[1]["team"] == "Beta"

    # Case 2: Tied on pts and H2H drawn, separated by conduct score
    played_conduct = {
        "M_AB": {"team_a": "Alpha", "team_b": "Beta", "home_score": 1, "away_score": 1, "yellow_cards_a": 2, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_AC": {"team_a": "Alpha", "team_b": "Gamma", "home_score": 2, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_BC": {"team_a": "Beta", "team_b": "Gamma", "home_score": 2, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_AD": {"team_a": "Alpha", "team_b": "Delta", "home_score": 1, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_BD": {"team_a": "Beta", "team_b": "Delta", "home_score": 1, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
        "M_CD": {"team_a": "Gamma", "team_b": "Delta", "home_score": 0, "away_score": 0, "yellow_cards_a": 0, "red_cards_a": 0, "yellow_cards_b": 0, "red_cards_b": 0},
    }
    # Alpha and Beta both have 7 pts, +3 GD, 4 GS, H2H 1-1.
    # Alpha has 2 yellow cards (conduct_score = 2). Beta has 0 cards (conduct_score = 0).
    # In FIFA rules, lower conduct score wins tiebreaker.
    st_conduct = compute_real_standings(groups_data, played_conduct, teams)
    assert st_conduct[0]["team"] == "Beta"
    assert st_conduct[1]["team"] == "Alpha"


def test_wc_unresolved_slots_truthfulness():
    """Verify that on empty played_groups, R32 knockout matches report prob_available=False,
    prob_reason='slot_unresolved', and explicit slot labels without fabricated team names."""
    groups = _load("groups.json")
    teams = _load("teams.json")
    bracket = _load("bracket.json")
    annex_c = _load("annex_c.json")

    res = compute_full_bracket(groups, teams, bracket, annex_c, {}, {})
    r32_matches = res["rounds"]["R32"]
    assert len(r32_matches) == 16

    for m in r32_matches:
        assert m["team_a"] is None, f"Expected team_a=None in results mode for {m['match_id']}"
        assert m["team_b"] is None, f"Expected team_b=None in results mode for {m['match_id']}"
        assert m["prob_available"] is False
        assert m["prob_reason"] == "slot_unresolved"
        assert m["slot_a"] is not None and len(m["slot_a"]) > 0
        assert m["slot_b"] is not None and len(m["slot_b"]) > 0


def test_wc_stage_completeness():
    """Verify all 6 stages (R32, R16, QF, SF, TPP, FINAL) exist in strict chronological order
    with total match count == 32 (16+8+4+2+1+1)."""
    groups = _load("groups.json")
    teams = _load("teams.json")
    bracket = _load("bracket.json")
    annex_c = _load("annex_c.json")

    res = compute_full_bracket(groups, teams, bracket, annex_c, {}, {})
    expected_stages = ["R32", "R16", "QF", "SF", "TPP", "FINAL"]
    assert list(res["rounds"].keys()) == expected_stages

    stage_counts = {k: len(v) for k, v in res["rounds"].items()}
    assert stage_counts == {
        "R32": 16,
        "R16": 8,
        "QF": 4,
        "SF": 2,
        "TPP": 1,
        "FINAL": 1,
    }
    assert res["n_matchups"] == 32


def test_wc_annex_c_routing():
    """Verify that valid third-place combinations from Annex C resolve properly without errors."""
    annex_c = _load("annex_c.json")
    standings = {}
    for gl in [chr(ord("A") + i) for i in range(12)]:
        standings[gl] = [
            {"team": f"{gl}1", "group": gl, "pts": 9, "gd": 5, "gs": 6, "conduct_score": 0, "elo": 1600},
            {"team": f"{gl}2", "group": gl, "pts": 6, "gd": 2, "gs": 4, "conduct_score": 0, "elo": 1500},
            {"team": f"{gl}3", "group": gl, "pts": 3, "gd": 0, "gs": 3, "conduct_score": 0, "elo": 1400},
            {"team": f"{gl}4", "group": gl, "pts": 0, "gd": -7, "gs": 1, "conduct_score": 0, "elo": 1300},
        ]
    third_ranked = rank_third_placed(standings)
    advancers = select_advancers(standings, third_ranked)

    matchups = resolve_r32_matchups(advancers, standings, third_ranked, annex_c)
    assert len(matchups) == 16

    assigned_teams = set()
    for mid, m in matchups.items():
        assert m["team_a"] is not None
        assert m["team_b"] is not None
        assert m["team_a"] not in assigned_teams
        assert m["team_b"] not in assigned_teams
        assigned_teams.add(m["team_a"])
        assigned_teams.add(m["team_b"])

    assert len(assigned_teams) == 32
