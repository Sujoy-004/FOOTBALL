"""Tests for UCL fixture schedule validation.

Covers UCLT-00 and UCLT-04 — validates fixture schedule format,
opponent counts, pot distribution, duplicate detection, and loading.
"""

import copy
import json
import os

import pytest

from competitions.ucl.src.validation import validate_ucl_fixtures


class TestFixtureValidation:
    """Tests for validate_ucl_fixtures()."""

    # ── Valid Schedule Tests ─────────────────────────────────────────────

    def test_valid_schedule_passes(self, sample_fixture_schedule):
        """A correctly structured 16-team, 2-matchday schedule passes."""
        result = validate_ucl_fixtures(sample_fixture_schedule)
        assert result is not None
        assert "schedule" in result

    # ── Team Count Tests ─────────────────────────────────────────────────

    def test_wrong_team_count(self, sample_fixture_schedule):
        """Schedule with 35 teams raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        schedule["schedule"]["teams"].pop()
        with pytest.raises(ValueError, match="36 teams"):
            validate_ucl_fixtures(schedule)

    # ── Opponent Count Tests ─────────────────────────────────────────────

    def test_wrong_opponent_count(self, sample_fixture_schedule):
        """Team with 7 opponents raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        # Remove one match involving the first team
        team_name = schedule["schedule"]["teams"][0]["name"]
        removed = False
        for md in schedule["schedule"]["matchdays"]:
            for m in list(md):
                if m["team_a"] == team_name or m["team_b"] == team_name:
                    md.remove(m)
                    removed = True
                    break
            if removed:
                break
        with pytest.raises(ValueError, match="opponent"):
            validate_ucl_fixtures(schedule)

    # ── Pot Distribution Tests ───────────────────────────────────────────

    def test_wrong_pot_distribution(self, sample_fixture_schedule):
        """Team with 3 opponents from one pot and 1 from another raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        # Find a matchup and change the pot value so distribution is wrong
        team_name = schedule["schedule"]["teams"][0]["name"]
        team_pot = schedule["schedule"]["teams"][0]["pot"]
        # Find first match involving this team and change opponent pot
        modified = False
        for md in schedule["schedule"]["matchdays"]:
            for m in md:
                if m["team_a"] == team_name and m["away_pot"] != team_pot:
                    m["away_pot"] = team_pot  # Same pot - unbalances distribution
                    modified = True
                    break
                elif m["team_b"] == team_name and m["home_pot"] != team_pot:
                    m["home_pot"] = team_pot
                    modified = True
                    break
            if modified:
                break
        with pytest.raises(ValueError, match="pot"):
            validate_ucl_fixtures(schedule)

    # ── Duplicate Matchup Tests ──────────────────────────────────────────

    def test_duplicate_matchup(self, sample_fixture_schedule):
        """Same team pair appearing twice raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        # Clone the first match into a new matchday
        first_match = schedule["schedule"]["matchdays"][0][0]
        new_match = {
            "match_id": "XX_XX",
            "team_a": first_match["team_a"],
            "team_b": first_match["team_b"],
            "home_pot": first_match["home_pot"],
            "away_pot": first_match["away_pot"],
        }
        schedule["schedule"]["matchdays"].append([new_match])
        with pytest.raises(ValueError, match="duplicate"):
            validate_ucl_fixtures(schedule)

    # ── Matchday Count Tests ─────────────────────────────────────────────

    def test_wrong_matchday_count(self, sample_fixture_schedule):
        """Schedule with 7 matchdays raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        schedule["schedule"]["matchdays"] = schedule["schedule"]["matchdays"][:7]
        with pytest.raises(ValueError, match="8 matchdays"):
            validate_ucl_fixtures(schedule)

    def test_nine_matchdays(self, sample_fixture_schedule):
        """Schedule with 9 matchdays raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        # Add an empty matchday
        schedule["schedule"]["matchdays"].append([{"match_id": "MD09_01", "team_a": "Man City", "team_b": "Bayern", "home_pot": 1, "away_pot": 1}])
        with pytest.raises(ValueError, match="8 matchdays"):
            validate_ucl_fixtures(schedule)

    # ── Matchday Size Tests ──────────────────────────────────────────────

    def test_incomplete_matchday(self, sample_fixture_schedule):
        """Matchday with 17 matches raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        schedule["schedule"]["matchdays"][0].pop()
        with pytest.raises(ValueError, match="18 matches"):
            validate_ucl_fixtures(schedule)

    # ── Team Reference Tests ─────────────────────────────────────────────

    def test_invalid_team_reference(self, sample_fixture_schedule):
        """Matchup referencing an unknown team raises ValueError."""
        schedule = copy.deepcopy(sample_fixture_schedule)
        schedule["schedule"]["matchdays"][0][0]["team_a"] = "NonExistent FC"
        with pytest.raises(ValueError, match="unknown team"):
            validate_ucl_fixtures(schedule)

    # ── Real Fixtures Pass ───────────────────────────────────────────────

    def test_real_fixtures_pass(self):
        """The live fixtures.json file must pass validation."""
        fixtures_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data",
            "fixtures.json",
        )
        with open(fixtures_path) as f:
            fixtures = json.load(f)
        result = validate_ucl_fixtures(fixtures)
        assert result is not None
        assert len(result["schedule"]["teams"]) == 36
        assert len(result["schedule"]["matchdays"]) == 8
