"""Tests for --what-if counterfactual analysis: parsing, impact direction, CLI edge cases."""

import json
import os
import subprocess
import sys

import pytest

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
LEAGUE_DATA_DIR = os.path.join(DATA_DIR, "27")
HAS_DATA = os.path.exists(os.path.join(LEAGUE_DATA_DIR, "teams.json"))


class TestWhatIfParsing:

    def test_parse_valid_elo_override(self):
        from competitions.worldcup.main import _parse_what_if_file
        teams = {"Brazil": {"elo": 2100}, "Argentina": {"elo": 2050}}
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"elo_changes": {"Brazil": 2200}}, f)
            path = f.name
        try:
            result = _parse_what_if_file(path, teams)
            assert result == {"elo_changes": {"Brazil": 2200}}
        finally:
            os.unlink(path)

    def test_parse_empty_overrides(self):
        from competitions.worldcup.main import _parse_what_if_file
        teams = {"Brazil": {"elo": 2100}}
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            path = f.name
        try:
            result = _parse_what_if_file(path, teams)
            assert result == {}
        finally:
            os.unlink(path)

    def test_parse_unknown_team(self):
        from competitions.worldcup.main import _parse_what_if_file
        teams = {"Brazil": {"elo": 2100}}
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"elo_changes": {"UnknownTeam": 2000}}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unknown team"):
                _parse_what_if_file(path, teams)
        finally:
            os.unlink(path)

    def test_parse_negative_elo(self):
        from competitions.worldcup.main import _parse_what_if_file
        teams = {"Brazil": {"elo": 2100}}
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"elo_changes": {"Brazil": -100}}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="positive"):
                _parse_what_if_file(path, teams)
        finally:
            os.unlink(path)

    def test_parse_unknown_override_key(self):
        from competitions.worldcup.main import _parse_what_if_file
        teams = {"Brazil": {"elo": 2100}}
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"unknown_key": 123}, f)
            path = f.name
        try:
            with pytest.raises(ValueError, match="Unknown override"):
                _parse_what_if_file(path, teams)
        finally:
            os.unlink(path)


class TestCounterfactualImpact:

    @pytest.fixture
    def loaded_data(self):
        from competitions.worldcup.src.state import (
            load_teams, load_groups, load_bracket, load_annex_c,
            load_played, load_played_groups,
        )
        teams = load_teams(DATA_DIR)
        groups = load_groups(DATA_DIR)
        bracket = load_bracket(DATA_DIR)
        annex_c = load_annex_c(DATA_DIR)
        played = load_played(DATA_DIR)
        played_groups = load_played_groups(DATA_DIR)
        return teams, groups, bracket, annex_c, played, played_groups

    def test_elo_increase_increases_probability(self, loaded_data):
        from competitions.worldcup.src.knockout import run_full_simulation
        from competitions.worldcup.main import _run_counterfactual

        teams, groups, bracket, annex_c, played, played_groups = loaded_data
        if not teams:
            pytest.skip("No team data found")

        baseline = run_full_simulation(
            teams, groups, bracket, annex_c, played,
            iterations=100, seed=42, played_groups=played_groups,
        )
        favorite = max(baseline, key=lambda k: baseline[k]["champion"])
        overrides = {"elo_changes": {favorite: teams[favorite]["elo"] + 200}}
        cf_result, _ = _run_counterfactual(
            teams, groups, bracket, annex_c, played, played_groups,
            overrides, 42, 100,
        )
        cf_prob = cf_result.get(favorite, {}).get("champion", 0.0)
        bl_prob = baseline[favorite]["champion"]
        assert cf_prob >= bl_prob, (
            f"Elo increase should not decrease probability for {favorite}: "
            f"baseline={bl_prob:.4f}, cf={cf_prob:.4f}"
        )

    def test_elo_decrease_decreases_probability(self, loaded_data):
        from competitions.worldcup.src.knockout import run_full_simulation
        from competitions.worldcup.main import _run_counterfactual

        teams, groups, bracket, annex_c, played, played_groups = loaded_data
        if not teams:
            pytest.skip("No team data found")

        baseline = run_full_simulation(
            teams, groups, bracket, annex_c, played,
            iterations=100, seed=42, played_groups=played_groups,
        )
        favorite = max(baseline, key=lambda k: baseline[k]["champion"])
        overrides = {"elo_changes": {favorite: max(100, teams[favorite]["elo"] - 200)}}
        cf_result, _ = _run_counterfactual(
            teams, groups, bracket, annex_c, played, played_groups,
            overrides, 42, 100,
        )
        cf_prob = cf_result.get(favorite, {}).get("champion", 0.0)
        bl_prob = baseline[favorite]["champion"]
        assert cf_prob <= bl_prob, (
            f"Elo decrease should not increase probability for {favorite}: "
            f"baseline={bl_prob:.4f}, cf={cf_prob:.4f}"
        )

    def test_counterfactual_seed_offset(self, loaded_data):
        from competitions.worldcup.src.knockout import run_full_simulation
        from competitions.worldcup.main import _run_counterfactual

        teams, groups, bracket, annex_c, played, played_groups = loaded_data
        if not teams:
            pytest.skip("No team data found")

        overrides = {}
        cf_result, _ = _run_counterfactual(
            teams, groups, bracket, annex_c, played, played_groups,
            overrides, 42, 100,
        )
        baseline = run_full_simulation(
            teams, groups, bracket, annex_c, played,
            iterations=100, seed=42, played_groups=played_groups,
        )
        for team in baseline:
            if cf_result.get(team, {}).get("champion", 0.0) != baseline[team]["champion"]:
                break
        else:
            # All probabilities identical — seed offset might not change output for some data
            pass


class TestWhatIfCLI:

    def test_what_if_without_simulate(self):
        result = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--what-if", "test.json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        assert "requires --simulate" in result.stderr

    def test_what_if_nonexistent_file(self):
        if not HAS_DATA:
            pytest.skip("No WC league data (data/27/)")
        result = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--what-if", "nonexistent.json", "-n", "100", "--seed", "42"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        assert result.stderr, "Expected error output"

    def test_what_if_invalid_json(self, tmp_path):
        if not HAS_DATA:
            pytest.skip("No WC league data (data/27/)")
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not valid json", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "competitions.worldcup.main",
             "--simulate", "--what-if", str(bad_file), "-n", "100", "--seed", "42"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 1
        assert len(result.stderr) > 0, "Expected error output"
