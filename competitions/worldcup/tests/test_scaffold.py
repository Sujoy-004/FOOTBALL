"""Tests for project scaffold, constants, seed data, and test fixtures."""

import json
import sys
from pathlib import Path

import pytest


def test_constants_module_importable():
    """Test 1: src.constants defines K_FACTOR=60, DEFAULT_ELO=1500, DATA_DIR as Path."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))
    try:
        from src.constants import K_FACTOR, DEFAULT_ELO, DATA_DIR  # noqa
    except ImportError:
        pytest.fail("src.constants module not importable")


def test_teams_json_exists_and_valid():
    """Test 2: data/teams.json is valid JSON with at least 32 entries, each having 'elo'."""
    teams_path = Path(__file__).resolve().parent.parent / "data" / "teams.json"
    assert teams_path.exists(), f"teams.json not found at {teams_path}"
    with open(teams_path, encoding="utf-8") as f:
        teams = json.load(f)
    assert isinstance(teams, dict), "teams.json must be a dict"
    assert len(teams) >= 32, f"Expected at least 32 teams, got {len(teams)}"
    for name, data in teams.items():
        assert "elo" in data, f"Team '{name}' missing 'elo' field"
        assert isinstance(data["elo"], int), f"Team '{name}' elo must be int"


def test_bracket_json_exists_and_valid():
    """Test 3: data/bracket.json is valid JSON with 32 matches, R32 uses slot descriptors, R16+ uses source_matches."""
    bracket_path = Path(__file__).resolve().parent.parent / "data" / "bracket.json"
    assert bracket_path.exists(), f"bracket.json not found at {bracket_path}"
    with open(bracket_path, encoding="utf-8") as f:
        bracket = json.load(f)
    assert isinstance(bracket, list), "bracket.json must be a list"
    assert len(bracket) == 32, f"Expected 32 matches, got {len(bracket)}"
    for match in bracket:
        assert "match_id" in match, "Match missing match_id"
        assert "round" in match, f"Match {match.get('match_id')} missing round"
        r = match["round"]
        if r == "R32":
            assert "home" in match, f"R32 match {match['match_id']} missing home slot"
            assert "away" in match, f"R32 match {match['match_id']} missing away slot"
            assert "kind" in match["home"], f"R32 match {match['match_id']} home missing kind"
            assert "kind" in match["away"], f"R32 match {match['match_id']} away missing kind"
        else:
            assert "source_matches" in match, f"{r} match {match['match_id']} missing source_matches"
            assert match["source_matches"] is None or isinstance(match["source_matches"], list)


def test_conftest_has_fixtures():
    """Test 4: tests/conftest.py defines sample_teams and sample_bracket fixtures."""
    conftest_path = Path(__file__).resolve().parent / "conftest.py"
    assert conftest_path.exists(), "conftest.py not found"
    content = conftest_path.read_text(encoding="utf-8")
    assert "@pytest.fixture" in content, "conftest.py missing @pytest.fixture"
    assert "def sample_teams" in content, "conftest.py missing sample_teams fixture"
    assert "def sample_bracket" in content, "conftest.py missing sample_bracket fixture"


def test_constants_import_works():
    """Test 5: 'from src.constants import K_FACTOR, DEFAULT_ELO' succeeds."""
    import subprocess
    import os
    repo_root = str(Path(__file__).resolve().parent.parent.parent.parent)
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", "")
    env["PYTHONPATH"] = repo_root + os.pathsep + env["PYTHONPATH"]
    result = subprocess.run(
        [sys.executable, "-c", "from src.constants import K_FACTOR, DEFAULT_ELO; print(K_FACTOR, DEFAULT_ELO)"],
        cwd=Path(__file__).resolve().parent.parent,
        capture_output=True, text=True, env=env,
    )
    assert result.returncode == 0, f"Import failed: {result.stderr}"
    parts = result.stdout.strip().split()
    assert len(parts) == 2, f"Expected 2 values, got: {result.stdout}"
    assert parts[0] == "60", f"K_FACTOR should be 60, got {parts[0]}"
    assert parts[1] == "1500", f"DEFAULT_ELO should be 1500, got {parts[1]}"


def test_team_aliases_includes_known_ambiguities():
    """Test 6: team_aliases.json includes USA/United States, Korea Republic/South Korea, IR Iran/Iran."""
    aliases_path = Path(__file__).resolve().parent.parent / "data" / "team_aliases.json"
    assert aliases_path.exists(), "team_aliases.json not found"
    with open(aliases_path, encoding="utf-8") as f:
        aliases = json.load(f)
    # United States must map to at least ["USA"]
    assert "United States" in aliases, "Missing 'United States' key"
    assert "USA" in aliases["United States"], "'United States' should include 'USA'"
    # Iran must map to at least ["IR Iran"]
    assert "Iran" in aliases, "Missing 'Iran' key"
    assert "IR Iran" in aliases["Iran"], "'Iran' should include 'IR Iran'"
    # South Korea must map to at least ["Korea Republic"]
    assert "South Korea" in aliases, "Missing 'South Korea' key"
    assert "Korea Republic" in aliases["South Korea"], "'South Korea' should include 'Korea Republic'"


def test_played_json_is_empty_dict():
    """Test 7: data/played.json is a valid JSON object `{}`."""
    played_path = Path(__file__).resolve().parent.parent / "data" / "played.json"
    assert played_path.exists(), "played.json not found"
    with open(played_path, encoding="utf-8") as f:
        played = json.load(f)
    assert played == {}, f"Expected empty dict, got: {played}"



