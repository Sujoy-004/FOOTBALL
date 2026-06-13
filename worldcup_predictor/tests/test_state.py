"""Comprehensive tests for state.py load/validate functions and main.py.

All file I/O tests use tmp_path to avoid modifying real data files.
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from src.state import (
    load_bracket,
    load_played,
    load_teams,
    validate_bracket,
)


# ─── validate_bracket: success cases ─────────────────────────────────────


def test_valid_bracket_passes(sample_bracket):
    """A valid bracket with correct DAG structure should pass without exception."""
    validate_bracket(sample_bracket)


# ─── validate_bracket: error cases ───────────────────────────────────────


def test_duplicate_match_id():
    """Duplicate match_ids should raise ValueError with 'Duplicate match_id'."""
    bad = [
        {"match_id": "R16_1", "round": "R16", "team_a": "Arg", "team_b": "Nig", "source_matches": None, "winner": None},
        {"match_id": "R16_1", "round": "R16", "team_a": "Fra", "team_b": "Den", "source_matches": None, "winner": None},
    ]
    with pytest.raises(ValueError, match="Duplicate match_id"):
        validate_bracket(bad)


def test_missing_source_match():
    """Non-existent source_match reference should raise ValueError with 'non-existent'."""
    bad = [
        {"match_id": "R16_1", "round": "R16", "team_a": "Arg", "team_b": "Nig", "source_matches": None, "winner": None},
        {"match_id": "QF_1", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["R16_1", "R16_X"], "winner": None},
    ]
    with pytest.raises(ValueError, match="non-existent"):
        validate_bracket(bad)


def test_circular_dependency():
    """Circular source_matches dependencies should raise ValueError with 'Circular'."""
    cyclic = [
        {"match_id": "A", "round": "R16", "team_a": "T1", "team_b": "T2", "source_matches": None, "winner": None},
        {"match_id": "B", "round": "R16", "team_a": "T3", "team_b": "T4", "source_matches": ["C"], "winner": None},
        {"match_id": "C", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["B"], "winner": None},
    ]
    with pytest.raises(ValueError, match="Circular dependency"):
        validate_bracket(cyclic)


# ─── load_teams tests ────────────────────────────────────────────────────


def test_load_teams_success(tmp_path, sample_teams):
    """load_teams should return dict matching the written file contents."""
    (tmp_path / "teams.json").write_text(json.dumps(sample_teams), encoding="utf-8")
    loaded = load_teams(data_dir=tmp_path)
    assert loaded == sample_teams


def test_load_teams_file_not_found(tmp_path):
    """load_teams should raise FileNotFoundError when teams.json is missing."""
    with pytest.raises(FileNotFoundError):
        load_teams(data_dir=tmp_path)


def test_load_corrupt_json(tmp_path):
    """load_teams should raise json.JSONDecodeError on malformed JSON."""
    (tmp_path / "teams.json").write_text("{invalid json!!!", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_teams(data_dir=tmp_path)


# ─── load_bracket tests ──────────────────────────────────────────────────


def test_load_bracket_invalid(tmp_path):
    """load_bracket should raise ValueError for bracket with duplicate match_ids."""
    bad_bracket = [
        {"match_id": "R16_1", "round": "R16", "team_a": "Arg", "team_b": "Nig", "source_matches": None, "winner": None},
        {"match_id": "R16_1", "round": "R16", "team_a": "Fra", "team_b": "Den", "source_matches": None, "winner": None},
    ]
    (tmp_path / "bracket.json").write_text(json.dumps(bad_bracket), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate match_id"):
        load_bracket(data_dir=tmp_path)


# ─── main.py tests ───────────────────────────────────────────────────────

MAIN_DIR = Path(__file__).resolve().parent.parent


def test_main_runs_successfully():
    """main.py should exit 0 and print team/bracket summary."""
    result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=MAIN_DIR,
        capture_output=True, text=True,
    )
    assert result.returncode == 0, f"main.py exited {result.returncode}: stderr={result.stderr!r}"
    assert "Loaded" in result.stdout, f"Missing 'Loaded' in output: {result.stdout}"
    assert "Validated bracket" in result.stdout, f"Missing bracket validation: {result.stdout}"
    assert "Played matches" in result.stdout, f"Missing played matches: {result.stdout}"


def test_main_fails_on_duplicate_bracket(tmp_path):
    """main.py should exit 1 when bracket has duplicate match_id."""
    # Write a bad bracket JSON to data dir
    bad_json = json.dumps([
        {"match_id": "R16_1", "round": "R16", "team_a": "Arg", "team_b": "Nig", "source_matches": None, "winner": None},
        {"match_id": "R16_1", "round": "R16", "team_a": "Fra", "team_b": "Den", "source_matches": None, "winner": None},
    ])
    (tmp_path / "bracket.json").write_text(bad_json, encoding="utf-8")
    (tmp_path / "teams.json").write_text('{"Team A": {"elo": 1500}}', encoding="utf-8")
    (tmp_path / "played.json").write_text("{}", encoding="utf-8")

    # Run a helper script that overrides DATA_DIR and calls main
    runner_code = f"""import sys, os
sys.path.insert(0, {str(MAIN_DIR)!r})
os.chdir({str(MAIN_DIR)!r})
import src.constants
src.constants.DATA_DIR = {str(tmp_path)!r}
import importlib
import src.state
importlib.reload(src.state)
import main
try:
    main.main()
    sys.exit(0)
except (ValueError, FileNotFoundError) as e:
    print(f"Error: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", runner_code],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"
    assert "Duplicate match_id" in result.stderr, f"Missing error: {result.stderr}"


def test_main_fails_on_circular_dependency(tmp_path):
    """main.py should exit 1 when bracket has circular dependency."""
    bad_json = json.dumps([
        {"match_id": "A", "round": "R16", "team_a": "T1", "team_b": "T2", "source_matches": None, "winner": None},
        {"match_id": "B", "round": "R16", "team_a": "T3", "team_b": "T4", "source_matches": ["C"], "winner": None},
        {"match_id": "C", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["B"], "winner": None},
    ])
    (tmp_path / "bracket.json").write_text(bad_json, encoding="utf-8")
    (tmp_path / "teams.json").write_text('{"Team A": {"elo": 1500}}', encoding="utf-8")
    (tmp_path / "played.json").write_text("{}", encoding="utf-8")

    runner_code = f"""import sys, os
sys.path.insert(0, {str(MAIN_DIR)!r})
os.chdir({str(MAIN_DIR)!r})
import src.constants
src.constants.DATA_DIR = {str(tmp_path)!r}
import importlib
import src.state
importlib.reload(src.state)
import main
try:
    main.main()
    sys.exit(0)
except (ValueError, FileNotFoundError) as e:
    print(f"Error: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", runner_code],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"
    assert "Circular dependency" in result.stderr, f"Missing error: {result.stderr}"


def test_main_fails_on_missing_teams(tmp_path):
    """main.py should exit 1 when teams.json is missing."""
    (tmp_path / "bracket.json").write_text('[]', encoding="utf-8")
    (tmp_path / "played.json").write_text("{}", encoding="utf-8")

    runner_code = f"""import sys, os
sys.path.insert(0, {str(MAIN_DIR)!r})
os.chdir({str(MAIN_DIR)!r})
import src.constants
src.constants.DATA_DIR = {str(tmp_path)!r}
import importlib
import src.state
importlib.reload(src.state)
import main
try:
    main.main()
    sys.exit(0)
except FileNotFoundError as e:
    print(f"Error: File not found: {{e}}", file=sys.stderr)
    sys.exit(1)
"""
    result = subprocess.run(
        [sys.executable, "-c", runner_code],
        capture_output=True, text=True,
    )
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"
    assert "File not found" in result.stderr, f"Missing error: {result.stderr}"
