"""Tests for state.py load and validate functions.

These are the RED-phase tests for Task 2. They verify that state.py
functions exist and work correctly before the implementation is created.
"""

import json
from pathlib import Path

import pytest


# ─── Fixtures for validation tests ───────────────────────────────────────

@pytest.fixture
def valid_bracket():
    """A valid 4-match bracket (2 R16 + 2 QF) with correct DAG structure."""
    return [
        {"match_id": "A", "round": "R16", "team_a": "T1", "team_b": "T2", "source_matches": None, "winner": None},
        {"match_id": "B", "round": "R16", "team_a": "T3", "team_b": "T4", "source_matches": None, "winner": None},
        {"match_id": "C", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["A", "B"], "winner": None},
        {"match_id": "D", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["C"], "winner": None},
    ]


@pytest.fixture
def duplicate_bracket():
    """Bracket with duplicate match_id."""
    return [
        {"match_id": "A", "round": "R16", "team_a": "T1", "team_b": "T2", "source_matches": None, "winner": None},
        {"match_id": "A", "round": "R16", "team_a": "T3", "team_b": "T4", "source_matches": None, "winner": None},
    ]


@pytest.fixture
def missing_source_bracket():
    """Bracket with a source_matches reference to a non-existent match_id."""
    return [
        {"match_id": "A", "round": "R16", "team_a": "T1", "team_b": "T2", "source_matches": None, "winner": None},
        {"match_id": "B", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["A", "Z"], "winner": None},
    ]


@pytest.fixture
def cyclic_bracket():
    """Bracket with circular dependency: A←B←C←A."""
    return [
        {"match_id": "A", "round": "R16", "team_a": "T1", "team_b": "T2", "source_matches": None, "winner": None},
        {"match_id": "B", "round": "R16", "team_a": "T3", "team_b": "T4", "source_matches": ["C"], "winner": None},
        {"match_id": "C", "round": "QF", "team_a": None, "team_b": None, "source_matches": ["B"], "winner": None},
    ]


# ─── Validation tests ────────────────────────────────────────────────────

def test_import_state_module():
    """Test that state.py can be imported (will fail before implementation)."""
    from src.state import load_teams, load_bracket, load_played, validate_bracket  # noqa


def test_valid_bracket_passes(valid_bracket):
    """Test 7: validate_bracket passes for a valid bracket with correct DAG."""
    from src.state import validate_bracket
    # Should not raise any exception
    validate_bracket(valid_bracket)


def test_duplicate_match_id(duplicate_bracket):
    """Test 4: validate_bracket raises ValueError for duplicate match_ids."""
    from src.state import validate_bracket
    with pytest.raises(ValueError, match="Duplicate match_id"):
        validate_bracket(duplicate_bracket)


def test_missing_source_match(missing_source_bracket):
    """Test 5: validate_bracket raises ValueError for non-existent source_match."""
    from src.state import validate_bracket
    with pytest.raises(ValueError, match="non-existent"):
        validate_bracket(missing_source_bracket)


def test_circular_dependency(cyclic_bracket):
    """Test 6: validate_bracket raises ValueError for circular dependencies."""
    from src.state import validate_bracket
    with pytest.raises(ValueError, match="Circular dependency"):
        validate_bracket(cyclic_bracket)


def test_load_teams_success(tmp_path):
    """Test 1: load_teams with valid teams.json returns dict matching file contents."""
    from src.state import load_teams
    teams_data = {"Argentina": {"elo": 2100}, "France": {"elo": 2050}}
    (tmp_path / "teams.json").write_text(json.dumps(teams_data), encoding="utf-8")
    loaded = load_teams(data_dir=tmp_path)
    assert loaded == teams_data


def test_load_bracket_valid(tmp_path, valid_bracket):
    """Test 2: load_bracket with valid bracket.json passes validate_bracket and returns list."""
    from src.state import load_bracket
    (tmp_path / "bracket.json").write_text(json.dumps(valid_bracket), encoding="utf-8")
    loaded = load_bracket(data_dir=tmp_path)
    assert isinstance(loaded, list)
    assert len(loaded) == 4


def test_load_bracket_invalid(tmp_path, duplicate_bracket):
    """Test: load_bracket raises ValueError for invalid bracket."""
    from src.state import load_bracket
    (tmp_path / "bracket.json").write_text(json.dumps(duplicate_bracket), encoding="utf-8")
    with pytest.raises(ValueError, match="Duplicate match_id"):
        load_bracket(data_dir=tmp_path)


def test_load_played_empty(tmp_path):
    """Test 3: load_played with empty played.json returns empty dict."""
    from src.state import load_played
    (tmp_path / "played.json").write_text("{}", encoding="utf-8")
    loaded = load_played(data_dir=tmp_path)
    assert loaded == {}


def test_load_teams_file_not_found(tmp_path):
    """Test 8: load_teams raises FileNotFoundError when teams.json missing."""
    from src.state import load_teams
    with pytest.raises(FileNotFoundError):
        load_teams(data_dir=tmp_path)


def test_load_teams_corrupt_json(tmp_path):
    """Test 9: load_teams raises json.JSONDecodeError on corrupt JSON."""
    from src.state import load_teams
    (tmp_path / "teams.json").write_text("{invalid json!!!", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_teams(data_dir=tmp_path)


# ─── Annex C validation tests (RED phase for TDD Task 2) ─────────────────


def test_validate_annex_c_empty_raises():
    """validate_annex_c({}) should raise ValueError for 0 entries."""
    from src.state import validate_annex_c
    with pytest.raises(ValueError, match="495"):
        validate_annex_c({})


def test_validate_annex_c_valid_495_passes():
    """validate_annex_c with 495 valid entries should pass without exception."""
    from src import constants
    from src.state import validate_annex_c
    import itertools

    all_groups = list('ABCDEFGHIJKL')
    expected_keys = {'1A', '1B', '1D', '1E', '1G', '1I', '1K', '1L'}
    valid_data = {}
    for combo in itertools.combinations(all_groups, 8):
        key = ','.join(combo)
        winner_groups = ['A', 'B', 'D', 'E', 'G', 'I', 'K', 'L']
        value = {}
        for i, wg in enumerate(winner_groups):
            target = combo[i % 8]
            value[f'1{wg}'] = f'3{target}'
        valid_data[key] = value

    validate_annex_c(valid_data)


def test_validate_annex_c_self_reference_raises():
    """validate_annex_c with self-reference ('1A' -> '3A') should raise ValueError."""
    from src.state import validate_annex_c
    import itertools

    all_groups = list('ABCDEFGHIJKL')
    valid_data = {}
    for combo in itertools.combinations(all_groups, 8):
        key = ','.join(combo)
        winner_groups = ['A', 'B', 'D', 'E', 'G', 'I', 'K', 'L']
        value = {}
        for i, wg in enumerate(winner_groups):
            target = combo[i % 8]
            value[f'1{wg}'] = f'3{target}'
        valid_data[key] = value

    # Inject a self-reference into the first entry
    first_key = list(valid_data.keys())[0]
    valid_data[first_key]['1A'] = '3A'

    with pytest.raises(ValueError, match="self-reference"):
        validate_annex_c(valid_data)


def test_validate_annex_c_ref_outside_key_raises():
    """validate_annex_c with reference to group not in key should raise ValueError."""
    from src.state import validate_annex_c
    import itertools

    all_groups = list('ABCDEFGHIJKL')
    valid_data = {}
    for combo in itertools.combinations(all_groups, 8):
        key = ','.join(combo)
        winner_groups = ['A', 'B', 'D', 'E', 'G', 'I', 'K', 'L']
        value = {}
        for i, wg in enumerate(winner_groups):
            target = combo[i % 8]
            value[f'1{wg}'] = f'3{target}'
        valid_data[key] = value

    # Inject a reference to a group not in the key
    first_key = list(valid_data.keys())[0]
    valid_data[first_key]['1A'] = '3X'

    with pytest.raises(ValueError):
        validate_annex_c(valid_data)


def test_load_annex_c_valid(tmp_path):
    """load_annex_c with valid annex_c.json should return dict."""
    from src.state import load_annex_c
    import itertools

    all_groups = list('ABCDEFGHIJKL')
    valid_data = {'_meta': {'source': 'test'}}
    for combo in itertools.combinations(all_groups, 8):
        key = ','.join(combo)
        winner_groups = ['A', 'B', 'D', 'E', 'G', 'I', 'K', 'L']
        value = {}
        for i, wg in enumerate(winner_groups):
            target = combo[i % 8]
            value[f'1{wg}'] = f'3{target}'
        valid_data[key] = value

    p = tmp_path / 'annex_c.json'
    p.write_text(json.dumps(valid_data), encoding='utf-8')
    loaded = load_annex_c(data_dir=tmp_path)
    assert '_meta' in loaded
    assert len(loaded) == 496  # 495 entries + _meta


def test_load_annex_c_missing_file(tmp_path):
    """load_annex_c with missing file should raise FileNotFoundError."""
    from src.state import load_annex_c
    with pytest.raises(FileNotFoundError):
        load_annex_c(data_dir=tmp_path)
