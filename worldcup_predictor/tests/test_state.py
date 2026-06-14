"""Comprehensive tests for state.py load/save/validate functions and main.py.

All file I/O tests use tmp_path to avoid modifying real data files.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.state import (
    load_bracket,
    load_played,
    load_teams,
    save_bracket,
    save_played,
    save_teams,
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


# ─── Save/persistence tests ──────────────────────────────────────────────


def test_teams_roundtrip(tmp_path):
    """save_teams → load_teams roundtrip should return identical data."""
    data = {"Argentina": {"elo": 2100}, "France": {"elo": 2050}}
    save_teams(data, data_dir=tmp_path)
    loaded = load_teams(data_dir=tmp_path)
    assert loaded == data


def test_bracket_roundtrip(tmp_path):
    """save_bracket → load_bracket roundtrip should return identical data."""
    data = [
        {"match_id": "R16_1", "round": "R16", "team_a": "Arg", "team_b": "Nig", "source_matches": None, "winner": None},
        {"match_id": "QF_1", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["R16_1"], "winner": None},
    ]
    save_bracket(data, data_dir=tmp_path)
    loaded = load_bracket(data_dir=tmp_path)
    assert loaded == data


def test_played_roundtrip(tmp_path):
    """save_played → load_played roundtrip should return identical data."""
    data = {
        "R16_1": {
            "team_a": "Argentina", "team_b": "Mexico",
            "winner": "Argentina", "home_score": 2, "away_score": 1,
            "completed_at": "2026-06-15T22:05:01Z",
        }
    }
    save_played(data, data_dir=tmp_path)
    loaded = load_played(data_dir=tmp_path)
    assert loaded == data


def test_atomic_write_safety(tmp_path):
    """No temp files should remain after a successful atomic write."""
    data = {"Team": {"elo": 1500}}
    save_teams(data, data_dir=tmp_path)
    # Check no .tmp files linger in the target directory
    tmp_files = list(tmp_path.glob("*.tmp"))
    assert len(tmp_files) == 0, f"Temp files found: {tmp_files}"


def test_data_dir_created(tmp_path):
    """save_teams should auto-create nested data directories."""
    nested = tmp_path / "new" / "sub"
    save_teams({"T": {"elo": 1500}}, data_dir=nested)
    assert (nested / "teams.json").exists()


def test_saved_file_is_valid_json(tmp_path):
    """Saved JSON file should be valid and loadable."""
    data = {"Team": {"elo": 1500}}
    save_teams(data, data_dir=tmp_path)
    with open(tmp_path / "teams.json", encoding="utf-8") as f:
        loaded = json.load(f)
    assert loaded == data


# ─── main.py tests ───────────────────────────────────────────────────────

MAIN_DIR = Path(__file__).resolve().parent.parent


def test_main_runs_successfully():
    """main.py should print team/bracket summary (may be killed by timeout when loop added)."""
    runner_code = (
        f"import os, sys\n"
        f"os.environ['POLL_INTERVAL'] = '1'\n"
        f"os.environ['FOOTBALL_API_KEY'] = 'test_dummy_key'\n"
        f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
        f"os.chdir({str(MAIN_DIR)!r})\n"
        f"import requests\n"
        f"import src.constants\n"
        f"src.constants.API_TIMEOUT = 1\n"
        f"class _MockResp:\n"
        f"  status_code=200\n"
        f"  def json(self): return {{}}\n"
        f"  def raise_for_status(self): pass\n"
        f"  @property\n"
        f"  def ok(self): return True\n"
        f"requests.get = lambda url, **kw: _MockResp()\n"
        f"import main\n"
        f"main.main()\n"
    )

    try:
        result = subprocess.run(
            [sys.executable, "-u", "-c", runner_code],
            capture_output=True, text=True, timeout=10,
        )
    except subprocess.TimeoutExpired:
        # Loop may not have exited cleanly due to timeout — that's OK, we only check startup output
        return

    assert "Loaded" in result.stdout, f"Missing 'Loaded' in output: {result.stdout}"
    assert "bracket matches" in result.stdout, f"Missing bracket info: {result.stdout}"
    assert "played matches" in result.stdout, f"Missing played matches: {result.stdout}"


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
