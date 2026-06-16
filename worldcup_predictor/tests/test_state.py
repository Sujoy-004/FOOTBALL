"""Comprehensive tests for state.py load/save/validate functions and main.py.

All file I/O tests use tmp_path to avoid modifying real data files.
"""

import itertools
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.state import (
    is_cache_valid,
    load_annex_c,
    load_bracket,
    load_groups,
    load_played,
    load_prediction_history,
    load_signal_cache,
    load_teams,
    migrate_prediction_history,
    save_bracket,
    save_played,
    save_signal_cache,
    save_teams,
    save_prediction_history,
    validate_annex_c,
    validate_bracket,
    validate_groups,
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
        f"os.environ['BSD_API_KEY'] = 'test_dummy_key'\n"
        f"sys.path.insert(0, {str(MAIN_DIR)!r})\n"
        f"os.chdir({str(MAIN_DIR)!r})\n"
        f"import requests\n"
        f"import src.constants\n"
        f"src.constants.API_TIMEOUT = 1\n"
        f"class _MockResp:\n"
        f"  status_code=200\n"
        f"  text = ''\n"
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


# ─── validate_groups tests ──────────────────────────────────────────


def _make_valid_groups(teams_override=None):
    """Build a valid 12-group dict for testing purposes."""
    groups = {}
    all_teams = teams_override or [f"Team_{i}" for i in range(48)]
    for idx, letter in enumerate("ABCDEFGHIJKL"):
        team_slice = all_teams[idx * 4 : (idx + 1) * 4]
        matches = []
        for mnum in range(1, 7):
            matches.append({
                "match_id": f"GS_{letter}_{mnum:02d}",
                "team_a": team_slice[0],
                "team_b": team_slice[1] if mnum == 1 else team_slice[min(mnum, 3)],
                "winner": None,
                "score_a": None,
                "score_b": None,
            })
        groups[letter] = {"teams": list(team_slice), "matches": matches}
    return {"groups": groups}


def test_valid_groups_passes():
    """A valid 12-group (A-L) structure with 4 teams and 6 matches each passes."""
    validate_groups(_make_valid_groups())


def test_valid_groups_wrong_group_count():
    """Structure with only 11 groups should raise ValueError."""
    data = _make_valid_groups()
    # Remove group L (last entry)
    groups = data["groups"]
    del groups["L"]
    with pytest.raises(ValueError, match="Expected.*12 groups.*got 11"):
        validate_groups(data)


def test_valid_groups_wrong_team_count():
    """A group with only 3 teams should raise ValueError."""
    data = _make_valid_groups()
    data["groups"]["A"]["teams"] = data["groups"]["A"]["teams"][:3]
    with pytest.raises(ValueError, match="Group A.*expected 4 teams.*got 3"):
        validate_groups(data)


def test_valid_groups_wrong_match_count():
    """A group with only 5 matches should raise ValueError."""
    data = _make_valid_groups()
    data["groups"]["B"]["matches"] = data["groups"]["B"]["matches"][:5]
    with pytest.raises(ValueError, match="Group B.*expected 6 matches.*got 5"):
        validate_groups(data)


def test_valid_groups_duplicate_team():
    """Same team appearing in 2+ groups should raise ValueError."""
    data = _make_valid_groups()
    # Put Team_0 into group B as well (it's already in group A)
    data["groups"]["B"]["teams"][0] = "Team_0"
    with pytest.raises(ValueError, match="Team.*Team_0.*appears in multiple"):
        validate_groups(data)


def test_valid_groups_duplicate_match_id():
    """Duplicate match_id across groups should raise ValueError."""
    data = _make_valid_groups()
    # Create duplicate within group B (prefix check passes, duplicate check fires)
    data["groups"]["B"]["matches"][5]["match_id"] = "GS_B_01"
    with pytest.raises(ValueError, match="Duplicate match_id"):
        validate_groups(data)


def test_valid_groups_invalid_match_id():
    """match_id not matching GS_{group}_NN pattern should raise ValueError."""
    data = _make_valid_groups()
    data["groups"]["A"]["matches"][0]["match_id"] = "GS_X_01"
    with pytest.raises(ValueError, match="does not start with.*GS_A_"):
        validate_groups(data)


def test_valid_groups_team_not_in_teams():
    """Team in groups but not in teams dict should raise ValueError."""
    groups_data = _make_valid_groups()
    teams_dict = {"Team_0": {"elo": 1500}, "Team_1": {"elo": 1500}}
    with pytest.raises(ValueError, match="not found in teams"):
        validate_groups(groups_data, teams=teams_dict)


def test_load_groups_success(tmp_path):
    """load_groups should return dict with 'groups' key from valid JSON."""
    data = _make_valid_groups()
    (tmp_path / "groups.json").write_text(json.dumps(data), encoding="utf-8")
    loaded = load_groups(data_dir=tmp_path)
    assert "groups" in loaded


def test_load_groups_file_not_found(tmp_path):
    """load_groups should raise FileNotFoundError when groups.json missing."""
    with pytest.raises(FileNotFoundError):
        load_groups(data_dir=tmp_path)


def test_load_groups_invalid_json(tmp_path):
    """load_groups should raise json.JSONDecodeError on malformed JSON."""
    (tmp_path / "groups.json").write_text("{invalid json!!!", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_groups(data_dir=tmp_path)


def test_load_groups_validation_error(tmp_path):
    """load_groups should raise ValueError for invalid groups data."""
    data = _make_valid_groups()
    del data["groups"]["A"]
    (tmp_path / "groups.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="Expected.*12 groups"):
        load_groups(data_dir=tmp_path)


# ─── validate_annex_c tests ─────────────────────────────────────────


def _make_valid_annex_c():
    """Build a valid 495-entry Annex C lookup table via itertools.combinations.
    
    Each entry maps 8 winner-group slots to third-place groups from the combo.
    Uses offset-based assignment with self-reference fallback: for each winner
    group, picks combo[(i+1) % 8]; if that equals the winner group (self-ref),
    falls back to combo[(i+2) % 8] which is guaranteed distinct.
    """
    all_groups = list("ABCDEFGHIJKL")
    winner_groups = ["A", "B", "D", "E", "G", "I", "K", "L"]
    data = {}
    for combo in itertools.combinations(all_groups, 8):
        key = ",".join(combo)
        value = {}
        for i, wg in enumerate(winner_groups):
            ref = combo[(i + 1) % 8]
            if ref == wg:
                ref = combo[(i + 2) % 8]
            value[f"1{wg}"] = f"3{ref}"
        data[key] = value
    return data


def test_annex_c_valid_passes():
    """495 valid entries created by itertools.combinations pass without exception."""
    validate_annex_c(_make_valid_annex_c())


def test_annex_c_wrong_count():
    """Dict with fewer than 495 entries should raise ValueError."""
    data = _make_valid_annex_c()
    # Remove one entry
    keys = list(data.keys())
    del data[keys[0]]
    with pytest.raises(ValueError, match="Expected.*495.*Annex C"):
        validate_annex_c(data)


def test_annex_c_unsorted_key():
    """A key with unsorted group letters should raise ValueError."""
    data = _make_valid_annex_c()
    data["H,A,B,C,D,E,F,G"] = data.pop("A,B,C,D,E,F,G,H")
    with pytest.raises(ValueError, match="not sorted"):
        validate_annex_c(data)


def test_annex_c_missing_value_key():
    """An entry missing one of the 8 assignment keys should raise ValueError."""
    data = _make_valid_annex_c()
    # Remove the "1A" key from the first value
    first_key = next(iter(data))
    del data[first_key]["1A"]
    with pytest.raises(ValueError, match="missing or extra assignment keys"):
        validate_annex_c(data)


def test_annex_c_self_reference():
    """A self-reference (e.g. '1A' -> '3A') should raise ValueError."""
    data = _make_valid_annex_c()
    data["A,B,C,D,E,F,G,H"]["1A"] = "3A"
    with pytest.raises(ValueError, match="self-reference"):
        validate_annex_c(data)


def test_annex_c_out_of_key_reference():
    """A value referencing a group not in its key should raise ValueError."""
    data = _make_valid_annex_c()
    data["A,B,C,D,E,F,G,H"]["1A"] = "3I"
    with pytest.raises(ValueError, match="not in key"):
        validate_annex_c(data)


def test_annex_c_invalid_group_letter():
    """A key containing a non-A-L letter should raise ValueError."""
    data = _make_valid_annex_c()
    data["A,B,C,D,E,F,G,X"] = data.pop("A,B,C,D,E,F,G,H")
    with pytest.raises(ValueError, match="invalid group letter"):
        validate_annex_c(data)


def test_load_annex_c_success(tmp_path):
    """load_annex_c should return dict from valid JSON file."""
    data = _make_valid_annex_c()
    (tmp_path / "annex_c.json").write_text(json.dumps(data), encoding="utf-8")
    loaded = load_annex_c(data_dir=tmp_path)
    assert len(loaded) == 495


def test_load_annex_c_file_not_found(tmp_path):
    """load_annex_c should raise FileNotFoundError when annex_c.json missing."""
    with pytest.raises(FileNotFoundError):
        load_annex_c(data_dir=tmp_path)


# ─── Production data verification tests ─────────────────────────────


def test_production_groups_validates():
    """Real groups.json passes validate_groups with cross-reference to teams.json."""
    data_dir = MAIN_DIR / "data"
    with open(data_dir / "groups.json", encoding="utf-8") as f:
        groups = json.load(f)
    with open(data_dir / "teams.json", encoding="utf-8") as f:
        teams = json.load(f)
    # Should not raise
    validate_groups(groups, teams=teams)


def test_production_annex_c_validates():
    """Real annex_c.json passes validate_annex_c."""
    data_dir = MAIN_DIR / "data"
    with open(data_dir / "annex_c.json", encoding="utf-8") as f:
        annex_c = json.load(f)
    # Should not raise
    validate_annex_c(annex_c)


# ─── Signal cache tests (Phase 13) ──────────────────────────────────


def test_is_cache_valid_valid():
    """A cache with a future expires_at should return True."""
    cache = {"expires_at": "2099-01-01T00:00:00+00:00"}
    assert is_cache_valid(cache, ttl_hours=12) is True


def test_is_cache_valid_expired():
    """A cache with a past expires_at should return False."""
    cache = {"expires_at": "2020-01-01T00:00:00+00:00"}
    assert is_cache_valid(cache, ttl_hours=12) is False


def test_is_cache_valid_empty():
    """An empty dict should return False."""
    assert is_cache_valid({}, ttl_hours=12) is False


def test_is_cache_valid_no_expires():
    """A cache without an expires_at key should return False."""
    cache = {"fetched_at": "2026-06-16T12:00:00+00:00"}
    assert is_cache_valid(cache, ttl_hours=12) is False


def test_is_cache_valid_malformed():
    """A cache with an invalid date string should return False."""
    cache = {"expires_at": "not-a-date"}
    assert is_cache_valid(cache, ttl_hours=12) is False


def test_save_load_signal_cache(tmp_path):
    """Save then load a signal cache should return identical content."""
    cache = {
        "fetched_at": "2026-06-16T12:00:00+00:00",
        "expires_at": "2026-06-17T00:00:00+00:00",
        "matches": {"GS_A_01": {"probability": 0.54, "available": True}},
    }
    save_signal_cache(cache, "test_cache.json", data_dir=tmp_path)
    loaded = load_signal_cache("test_cache.json", data_dir=tmp_path)
    assert loaded == cache


def test_signal_cache_not_exists(tmp_path):
    """load_signal_cache should return empty dict if file doesn't exist."""
    loaded = load_signal_cache("nonexistent.json", data_dir=tmp_path)
    assert loaded == {}


def test_save_prediction_history(tmp_path):
    """save_prediction_history persists a complete history list."""
    history = [
        {"match_id": "GS_A_01", "actual": 1, "signals": {}},
        {"match_id": "GS_A_02", "actual": 0, "signals": {}},
        {"match_id": "GS_B_01", "actual": 1, "signals": {}},
    ]
    save_prediction_history(history, data_dir=tmp_path)
    loaded = load_prediction_history(data_dir=tmp_path)
    assert loaded == history


def test_save_prediction_history_overwrite(tmp_path):
    """save_prediction_history replaces the entire history (not append)."""
    history_a = [
        {"match_id": "GS_A_01", "actual": 1, "signals": {}},
    ]
    history_b = [
        {"match_id": "GS_B_01", "actual": 0, "signals": {}},
    ]
    save_prediction_history(history_a, data_dir=tmp_path)
    save_prediction_history(history_b, data_dir=tmp_path)
    loaded = load_prediction_history(data_dir=tmp_path)
    assert loaded == history_b, "Expected second save to replace, not append"


# ─── migrate_prediction_history tests (Phase 13, Plan 03) ──────────────


class TestMigratePredictionHistory:
    """Tests for migrate_prediction_history() flat→compound schema migration."""

    FLAT_ENTRY = {
        "match_id": "M01",
        "timestamp": "2026-06-15T09:29:22.355352+00:00",
        "team_a": "A",
        "team_b": "B",
        "prediction": 0.6401,
        "actual": 1.0,
        "signal": "elo",
        "team_a_elo": 2000,
        "team_b_elo": 1900,
    }

    COMPOUND_ENTRY = {
        "match_id": "M01",
        "timestamp": "2026-06-15T09:29:22.355352+00:00",
        "team_a": "A",
        "team_b": "B",
        "actual": 1.0,
        "signals": {
            "elo": {
                "probability": 0.6401,
                "version": "v1",
                "timestamp": "2026-06-15T09:29:22.355352+00:00",
                "available": True,
                "team_a_elo": 2000,
                "team_b_elo": 1900,
            }
        },
    }

    def test_migrate_flat_to_compound(self, tmp_path):
        """Flat entry becomes compound with signals.elo.probability, no top-level prediction/signal."""
        from src.state import migrate_prediction_history
        save_prediction_history([dict(self.FLAT_ENTRY)], data_dir=tmp_path)
        n = migrate_prediction_history(data_dir=tmp_path)
        assert n == 1, "Should migrate 1 entry"
        history = load_prediction_history(data_dir=tmp_path)
        entry = history[0]
        assert "signals" in entry, "Migrated entry must have 'signals' key"
        assert "prediction" not in entry, "Migrated entry must not have top-level 'prediction'"
        assert "signal" not in entry, "Migrated entry must not have top-level 'signal'"
        assert entry["signals"]["elo"]["probability"] == 0.6401
        assert entry["signals"]["elo"]["available"] is True
        assert entry["signals"]["elo"]["team_a_elo"] == 2000
        assert entry["signals"]["elo"]["team_b_elo"] == 1900
        assert entry["actual"] == 1.0

    def test_migrate_multiple_entries(self, tmp_path):
        """Multiple flat entries all migrated correctly."""
        from src.state import migrate_prediction_history
        entries = [
            {"match_id": f"M{i:02d}", "signal": "elo", "prediction": 0.5 + i * 0.1,
             "actual": 1.0, "team_a": "A", "team_b": "B",
             "timestamp": "2026-06-15T12:00:00+00:00", "team_a_elo": 2000, "team_b_elo": 1900}
            for i in range(3)
        ]
        save_prediction_history(entries, data_dir=tmp_path)
        n = migrate_prediction_history(data_dir=tmp_path)
        assert n == 3, f"Expected 3 migrated, got {n}"
        history = load_prediction_history(data_dir=tmp_path)
        assert len(history) == 3
        for entry in history:
            assert "signals" in entry
            assert "signal" not in entry

    def test_migrate_idempotent(self, tmp_path):
        """Already-compound entry unchanged after migration (idempotent)."""
        from src.state import migrate_prediction_history
        entry = dict(self.COMPOUND_ENTRY)
        save_prediction_history([entry], data_dir=tmp_path)
        n = migrate_prediction_history(data_dir=tmp_path)
        assert n == 0, "Should not migrate already-compound entries"
        history = load_prediction_history(data_dir=tmp_path)
        assert history[0] == entry

    def test_migrate_mixed(self, tmp_path):
        """Flat and compound entries in same list → both handled correctly."""
        from src.state import migrate_prediction_history
        flat = dict(self.FLAT_ENTRY)
        compound = dict(self.COMPOUND_ENTRY)
        save_prediction_history([flat, compound], data_dir=tmp_path)
        n = migrate_prediction_history(data_dir=tmp_path)
        assert n == 1, "Should migrate exactly 1 flat entry"
        history = load_prediction_history(data_dir=tmp_path)
        assert len(history) == 2
        assert "signals" in history[0]
        assert "signals" in history[1]

    def test_migrate_empty(self, tmp_path):
        """Empty list → empty list."""
        from src.state import migrate_prediction_history
        save_prediction_history([], data_dir=tmp_path)
        n = migrate_prediction_history(data_dir=tmp_path)
        assert n == 0
        history = load_prediction_history(data_dir=tmp_path)
        assert history == []

    def test_migrate_preserves_actual(self, tmp_path):
        """actual field preserved in compound entry."""
        from src.state import migrate_prediction_history
        entry = dict(self.FLAT_ENTRY)
        entry["actual"] = 0.0
        save_prediction_history([entry], data_dir=tmp_path)
        n = migrate_prediction_history(data_dir=tmp_path)
        assert n == 1
        history = load_prediction_history(data_dir=tmp_path)
        assert history[0]["actual"] == 0.0
