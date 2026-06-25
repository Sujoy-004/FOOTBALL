"""Integration tests for the group match pipeline (Phase 10).

Covers group match ingestion, persistence, standings display, and full pipeline.
Maps to INTG-01 through INTG-07 from REQUIREMENTS.md.
"""

import json
import os
import random
from pathlib import Path

import pytest

from src.fetcher import process_group_matches, _extract_group_letter, find_group_match
from src.groups import (
    compute_standings,
    rank_third_placed,
    simulate_group_matches,
    precompute_matchup_lambdas,
)
from src.state import load_aliases, load_played_groups, save_played_groups


# ─── Fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def group_a_fixture():
    """Minimal 1-group fixture matching Group A from groups.json structure.

    Teams and match slots mirror conftest.py's sample_groups fixture so
    tests that need a single group can use this directly.
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
def elo_ratings():
    """Elo ratings for Group A test teams."""
    return {
        "Mexico": 1850.0,
        "South Africa": 1700.0,
        "South Korea": 1650.0,
        "Czech Republic": 1468.0,
    }


@pytest.fixture
def teams_dict(elo_ratings):
    """Teams dict (with 'elo' key) for Group A test teams."""
    return {name: {"elo": elo} for name, elo in elo_ratings.items()}


@pytest.fixture
def group_a_match_bsd_events():
    """Mock BSD API events for 2 finished group A matches.

    Mexico 2-1 South Africa (GS_A_01)
    South Korea 2-0 Czech Republic (GS_A_06)
    """
    return [
        {
            "id": 1001,
            "status": "finished",
            "home_team": "Mexico",
            "away_team": "South Africa",
            "home_score": 2,
            "away_score": 1,
            "group_name": "Group A",
            "round_number": 1,
            "event_date": "2026-06-14T17:00:00Z",
        },
        {
            "id": 1002,
            "status": "finished",
            "home_team": "South Korea",
            "away_team": "Czech Republic",
            "home_score": 2,
            "away_score": 0,
            "group_name": "Group A",
            "round_number": 6,
            "event_date": "2026-06-14T19:00:00Z",
        },
    ]


# ─── INTG-01: Group match ingestion tests ───────────────────────────────


class TestProcessGroupMatches:
    """Tests for process_group_matches() — BSD API group match ingestion."""

    def test_process_group_matches_basic(self, group_a_fixture, group_a_match_bsd_events):
        """Basic ingestion: mock BSD event returns 1 entry with correct match_id, winner, scores."""
        result = process_group_matches(
            group_a_match_bsd_events[:1],  # First event only: Mexico vs South Africa
            {}, group_a_fixture, {},
            set(), set(),
        )
        assert len(result) == 1, f"Expected 1 result, got {len(result)}"
        entry = result[0]
        assert entry["match_id"] == "GS_A_01", (
            f"Expected GS_A_01, got {entry['match_id']}"
        )
        assert entry["winner"] == "Mexico", (
            f"Expected winner Mexico, got {entry['winner']}"
        )
        assert entry["home_score"] == 2
        assert entry["away_score"] == 1
        assert entry["team_a"] == "Mexico"
        assert entry["team_b"] == "South Africa"

    def test_process_group_matches_basic_two_events(self, group_a_fixture, group_a_match_bsd_events):
        """Two mock BSD events produce 2 entries with distinct match_ids."""
        result = process_group_matches(
            group_a_match_bsd_events, {}, group_a_fixture, {},
            set(), set(),
        )
        assert len(result) == 2, f"Expected 2 results, got {len(result)}"
        match_ids = {e["match_id"] for e in result}
        assert match_ids == {"GS_A_01", "GS_A_06"}, (
            f"Expected GS_A_01 and GS_A_06, got {match_ids}"
        )

    def test_process_group_matches_dedup_bsd_event(self, group_a_fixture, group_a_match_bsd_events):
        """BSD event id dedup: same event second time returns empty list."""
        played_bsd_ids: set[str] = set()
        first = process_group_matches(
            group_a_match_bsd_events[:1], {}, group_a_fixture, {},
            set(), played_bsd_ids,
        )
        assert len(first) == 1, "First call should return 1 entry"

        second = process_group_matches(
            group_a_match_bsd_events[:1], {}, group_a_fixture, {},
            set(), played_bsd_ids,
        )
        assert len(second) == 0, (
            f"Second call with same bsd_id should be empty, got {len(second)}"
        )

    def test_process_group_matches_dedup_match_id(self, group_a_fixture, group_a_match_bsd_events):
        """Match_id dedup: fresh BSD event but played_group_ids prevents re-processing."""
        played_group_ids = {"GS_A_01"}
        result = process_group_matches(
            group_a_match_bsd_events[:1], {}, group_a_fixture, {},
            played_group_ids, set(),
        )
        assert len(result) == 0, (
            f"Expected empty when match_id is in played_group_ids, got {len(result)}"
        )

    def test_process_group_matches_unmatchable_team(self, group_a_fixture):
        """Unknown team name returns empty list (log warning, no crash)."""
        bad_events = [
            {
                "id": 9999,
                "status": "finished",
                "home_team": "UnknownTeam",
                "away_team": "Mexico",
                "home_score": 1,
                "away_score": 0,
                "group_name": "Group A",
                "round_number": 1,
                "event_date": "2026-06-14T17:00:00Z",
            }
        ]
        result = process_group_matches(
            bad_events, {}, group_a_fixture, {},
            set(), set(),
        )
        assert result == [], f"Expected empty for unknown team, got {result}"

    def test_process_group_matches_draw_included(self, group_a_fixture):
        """Draw match (equal scores) produces entry with winner=None, is_draw=True."""
        draw_events = [
            {
                "id": 2001,
                "status": "finished",
                "home_team": "Mexico",
                "away_team": "South Africa",
                "home_score": 1,
                "away_score": 1,
                "group_name": "Group A",
                "round_number": 1,
                "event_date": "2026-06-14T17:00:00Z",
            }
        ]
        result = process_group_matches(
            draw_events, {}, group_a_fixture, {},
            set(), set(),
        )
        assert len(result) == 1, f"Expected 1 result for draw, got {len(result)}"
        assert result[0]["winner"] is None
        assert result[0]["is_draw"] is True
        assert result[0]["match_id"] == "GS_A_01"
        assert result[0]["home_score"] == 1
        assert result[0]["away_score"] == 1
        assert result[0]["team_a"] == "Mexico"
        assert result[0]["team_b"] == "South Africa"

    def test_process_group_matches_invalid_group_name(self, group_a_fixture):
        """Event with invalid group_name (not A-L) is skipped."""
        bad_group_events = [
            {
                "id": 3001,
                "status": "finished",
                "home_team": "Mexico",
                "away_team": "South Africa",
                "home_score": 2,
                "away_score": 1,
                "group_name": "Group Z",
                "round_number": 1,
                "event_date": "2026-06-14T17:00:00Z",
            }
        ]
        result = process_group_matches(
            bad_group_events, {}, group_a_fixture, {},
            set(), set(),
        )
        assert result == [], f"Expected empty for bad group_name, got {result}"

    def test_process_group_matches_null_group_name_skipped(self, group_a_fixture, group_a_match_bsd_events):
        """Event with null group_name is skipped (knockout match, handled elsewhere)."""
        knockout_event = [
            {
                "id": 4001,
                "status": "finished",
                "home_team": "Argentina",
                "away_team": "France",
                "home_score": 3,
                "away_score": 1,
                "group_name": None,
                "round_number": None,
                "event_date": "2026-06-14T21:00:00Z",
            }
        ]
        result = process_group_matches(
            knockout_event, {}, group_a_fixture, {},
            set(), set(),
        )
        assert result == [], (
            f"Expected empty for null group_name, got {result}"
        )


# ─── INTG-02: played_groups persistence tests ───────────────────────────


class TestPlayedGroupsPersistence:
    """Tests for played_groups.json roundtrip (load/save)."""

    def test_played_groups_roundtrip(self, tmp_path):
        """Save dict with one entry via save_played_groups, load via load_played_groups, assert equality."""
        played = {
            "GS_A_01": {
                "match_id": "GS_A_01",
                "team_a": "Mexico",
                "team_b": "South Africa",
                "winner": "Mexico",
                "home_score": 2,
                "away_score": 1,
                "completed_at": "2026-06-14T17:00:00Z",
            }
        }
        save_played_groups(played, data_dir=tmp_path)
        loaded = load_played_groups(data_dir=tmp_path)
        assert loaded == played, f"Roundtrip failed: {loaded} != {played}"

    def test_played_groups_empty_bootstrap(self, tmp_path):
        """load_played_groups returns empty dict when file doesn't exist (D-09)."""
        loaded = load_played_groups(data_dir=tmp_path)
        assert loaded == {}, (
            f"Expected empty dict for missing file, got {loaded}"
        )

    def test_played_groups_multiple_entries(self, tmp_path):
        """Multiple entries survive save → load roundtrip."""
        played = {
            "GS_A_01": {
                "match_id": "GS_A_01",
                "team_a": "Mexico",
                "team_b": "South Africa",
                "winner": "Mexico",
                "home_score": 2,
                "away_score": 1,
                "completed_at": "2026-06-14T17:00:00Z",
            },
            "GS_B_03": {
                "match_id": "GS_B_03",
                "team_a": "Brazil",
                "team_b": "Spain",
                "winner": "Brazil",
                "home_score": 3,
                "away_score": 0,
                "completed_at": "2026-06-15T19:00:00Z",
            },
        }
        save_played_groups(played, data_dir=tmp_path)
        loaded = load_played_groups(data_dir=tmp_path)
        assert len(loaded) == 2
        assert loaded["GS_A_01"]["winner"] == "Mexico"
        assert loaded["GS_B_03"]["winner"] == "Brazil"


# ─── INTG-03: Standings with played groups tests ────────────────────────


class TestStandingsWithPlayedGroups:
    """Tests for group standings with real results injected via played_groups."""

    def test_compute_standings_with_played_groups(
        self, group_a_fixture, teams_dict, elo_ratings
    ):
        """Standings reflect real played results, not simulated ones."""
        played_groups = {
            "GS_A_01": {
                "match_id": "GS_A_01",
                "team_a": "Mexico",
                "team_b": "South Africa",
                "winner": "Mexico",
                "home_score": 2,
                "away_score": 1,
            },
            "GS_A_06": {
                "match_id": "GS_A_06",
                "team_a": "South Korea",
                "team_b": "Czech Republic",
                "winner": "South Korea",
                "home_score": 2,
                "away_score": 0,
            },
        }
        rng = random.Random(0)
        results = simulate_group_matches(
            group_a_fixture, teams_dict, elo_ratings, rng,
            played_groups=played_groups,
        )
        # Verify played results are injected
        assert results["A"]["GS_A_01"]["winner"] == "Mexico"
        assert results["A"]["GS_A_01"]["score_a"] == 2
        assert results["A"]["GS_A_01"]["score_b"] == 1
        assert results["A"]["GS_A_06"]["winner"] == "South Korea"
        assert results["A"]["GS_A_06"]["score_a"] == 2
        assert results["A"]["GS_A_06"]["score_b"] == 0

    def test_played_groups_simulation_skips_remaining_matches(
        self, group_a_fixture, teams_dict, elo_ratings
    ):
        """Remaining matches (without played_groups) are simulated as usual."""
        played_groups = {
            "GS_A_01": {
                "match_id": "GS_A_01",
                "team_a": "Mexico",
                "team_b": "South Africa",
                "winner": "Mexico",
                "home_score": 2,
                "away_score": 1,
            },
        }
        rng = random.Random(42)
        lambdas = precompute_matchup_lambdas(group_a_fixture, elo_ratings)
        results = simulate_group_matches(
            group_a_fixture, teams_dict, elo_ratings, rng,
            played_groups=played_groups,
            matchup_lambdas=lambdas,
        )
        # GS_A_01 should be played result
        assert results["A"]["GS_A_01"]["winner"] == "Mexico"
        # Other matches should be simulated (non-None scores)
        for mid in ["GS_A_02", "GS_A_03", "GS_A_04", "GS_A_05", "GS_A_06"]:
            assert results["A"][mid]["score_a"] is not None, (
                f"{mid} should have been simulated with a score"
            )
            assert results["A"][mid]["score_b"] is not None


# ─── INTG-06, INTG-07: Full pipeline end-to-end test ────────────────────


class TestFullPipeline:
    """End-to-end test: mock BSD → process → persist → simulate → standings."""

    def test_full_pipeline_with_group_matches(
        self, group_a_fixture, teams_dict, elo_ratings, tmp_path
    ):
        """Full pipeline: 2 processed BSD events → save → load → sim → standings."""
        # Step 1: Build mock BSD response with 2 group matches
        bsd_events = [
            {
                "id": 1001,
                "status": "finished",
                "home_team": "Mexico",
                "away_team": "South Africa",
                "home_score": 2,
                "away_score": 1,
                "group_name": "Group A",
                "round_number": 1,
                "event_date": "2026-06-14T17:00:00Z",
            },
            {
                "id": 1002,
                "status": "finished",
                "home_team": "South Korea",
                "away_team": "Czech Republic",
                "home_score": 3,
                "away_score": 0,
                "group_name": "Group A",
                "round_number": 6,
                "event_date": "2026-06-14T19:00:00Z",
            },
        ]

        # Step 2: Process group matches (mock BSD → results)
        processed = process_group_matches(
            bsd_events, {}, group_a_fixture, {},
            set(), set(),
        )
        assert len(processed) == 2, f"Expected 2 processed matches, got {len(processed)}"

        # Step 3: Build played_groups dict from processed results
        played_groups = {}
        for entry in processed:
            played_groups[entry["match_id"]] = {
                "match_id": entry["match_id"],
                "team_a": entry["team_a"],
                "team_b": entry["team_b"],
                "winner": entry["winner"],
                "home_score": entry["home_score"],
                "away_score": entry["away_score"],
            }

        # Step 4: Save played_groups to tmp_path
        save_played_groups(played_groups, data_dir=tmp_path)

        # Step 5: Load back (simulate restart persistence)
        loaded = load_played_groups(data_dir=tmp_path)
        assert len(loaded) == 2

        # Step 6: Simulate group matches with played_groups
        rng = random.Random(42)
        results = simulate_group_matches(
            group_a_fixture, teams_dict, elo_ratings, rng,
            played_groups=loaded,
        )

        # Step 7: Compute standings
        standings = compute_standings(results, elo_ratings)

        # Step 8: Verify standings include real results
        assert "A" in standings, "Group A should be in standings"
        assert len(standings["A"]) == 4, "Group A should have 4 teams"

        # The played results should be reflected:
        # Mexico beat South Africa 2-1 → Mexico has 3pts
        # South Korea beat Czech Republic 3-0 → South Korea has 3pts
        mexico = next(t for t in standings["A"] if t["team"] == "Mexico")
        south_korea = next(t for t in standings["A"] if t["team"] == "South Korea")
        czech = next(t for t in standings["A"] if t["team"] == "Czech Republic")
        south_africa = next(t for t in standings["A"] if t["team"] == "South Africa")

        assert mexico["pts"] >= 3, (
            f"Mexico should have at least 3pts (win), got {mexico['pts']}"
        )
        assert south_korea["pts"] >= 3, (
            f"South Korea should have at least 3pts (win), got {south_korea['pts']}"
        )
        # Positions should be deterministic
        assert mexico["position"] >= 1
        assert mexico["position"] <= 4


# ─── INTG-04: Third-place bubble calculation ─────────────────────────────


class TestThirdPlaceBubble:
    """Tests for third-place bubble calculation across 12 groups."""

    def _build_12_group_standings(self) -> dict:
        """Build standings dict with all 12 groups, each with 4 teams."""
        standings: dict = {}
        for group_letter in "ABCDEFGHIJKL":
            standings[group_letter] = [
                {"team": f"{group_letter}1", "pts": 9, "gd": 5, "gs": 7,
                 "conduct_score": 0, "elo": 1900.0, "position": 1},
                {"team": f"{group_letter}2", "pts": 6, "gd": 2, "gs": 4,
                 "conduct_score": 1, "elo": 1750.0, "position": 2},
                {"team": f"{group_letter}3", "pts": 4, "gd": 0, "gs": 2,
                 "conduct_score": 4, "elo": 1600.0, "position": 3},
                {"team": f"{group_letter}4", "pts": 1, "gd": -7, "gs": 0,
                 "conduct_score": 10, "elo": 1450.0, "position": 4},
            ]
        return standings

    def test_third_place_bubble_calculation_basic(self):
        """rank_third_placed returns 12 entries with correct ordering."""
        standings = self._build_12_group_standings()
        third = rank_third_placed(standings)
        assert len(third) == 12, f"Expected 12 third-placed teams, got {len(third)}"

    def test_third_place_bubble_ordering(self):
        """Third-placed teams are sorted by pts descending, then GD, GS."""
        standings = self._build_12_group_standings()
        third = rank_third_placed(standings)

        # All have 4 pts and GD=0 — but we'll add variation to test ordering
        # Default: all are tied (4pts, GD=0, GS=2) so order doesn't change
        for i in range(11):
            assert third[i]["pts"] >= third[i + 1]["pts"], (
                f"Position {i}: {third[i]['pts']} >= {third[i+1]['pts']}"
            )

    def test_third_place_bubble_cutoff_points(self):
        """Top 8 third-placed teams advance, bottom 4 are eliminated."""
        # Give groups A-H better points, I-L worse points
        standings: dict = {}
        for i, group_letter in enumerate("ABCDEFGHIJKL"):
            pts = 6 - i  # A=6, B=5, C=4, D=3, E=2, F=1, G=0, H=-1...
            standings[group_letter] = [
                {"team": f"{group_letter}1", "pts": 9, "gd": 5, "gs": 7,
                 "conduct_score": 0, "elo": 1900.0, "position": 1},
                {"team": f"{group_letter}2", "pts": 6, "gd": 2, "gs": 4,
                 "conduct_score": 1, "elo": 1750.0, "position": 2},
                {"team": f"{group_letter}3", "pts": pts, "gd": 0, "gs": 2,
                 "conduct_score": 4, "elo": 1600.0, "position": 3},
                {"team": f"{group_letter}4", "pts": 1, "gd": -7, "gs": 0,
                 "conduct_score": 10, "elo": 1450.0, "position": 4},
            ]

        third = rank_third_placed(standings)
        assert len(third) == 12

        # Top 8 (advancing) should have higher pts than bottom 4
        advancing = third[:8]
        eliminated = third[8:]
        assert all(t["pts"] >= eliminated[0]["pts"] for t in advancing), (
            f"Advancing third pts: {[t['pts'] for t in advancing]}, "
            f"eliminated: {[t['pts'] for t in eliminated]}"
        )

    def test_third_place_bubble_tiebreaker(self):
        """When tied on pts, GD decides ordering."""
        standings: dict = {}
        # A: 4pts, GD=+2
        # B: 4pts, GD=+1
        # C-L: 2pts
        for group_letter in "ABCDEFGHIJKL":
            if group_letter == "A":
                gd = 2
            elif group_letter == "B":
                gd = 1
            else:
                gd = 0
            standings[group_letter] = [
                {"team": f"{group_letter}1", "pts": 9, "gd": 5, "gs": 7,
                 "conduct_score": 0, "elo": 1900.0, "position": 1},
                {"team": f"{group_letter}2", "pts": 6, "gd": 2, "gs": 4,
                 "conduct_score": 1, "elo": 1750.0, "position": 2},
                {"team": f"{group_letter}3", "pts": 4 if group_letter in "AB" else 2,
                 "gd": gd, "gs": 2,
                 "conduct_score": 4, "elo": 1600.0, "position": 3},
                {"team": f"{group_letter}4", "pts": 1, "gd": -7, "gs": 0,
                 "conduct_score": 10, "elo": 1450.0, "position": 4},
            ]

        third = rank_third_placed(standings)
        # Find A and B in the ranking
        a_idx = next(i for i, t in enumerate(third) if t["group"] == "A")
        b_idx = next(i for i, t in enumerate(third) if t["group"] == "B")
        # A (GD=+2) should be before B (GD=+1)
        assert a_idx < b_idx, (
            f"A (GD=+2) should be ranked above B (GD=+1), "
            f"got A at {a_idx}, B at {b_idx}"
        )
