"""State persistence and bracket validation for the World Cup predictor.

All JSON state files (teams.json, bracket.json, played.json) are loaded
and saved through this module. Bracket validation ensures the tournament
structure is valid before simulation.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from src import constants


# ─── Load functions ──────────────────────────────────────────────────────


def load_aliases(data_dir: Path | str | None = None) -> dict[str, list[str]]:
    """Load team aliases from team_aliases.json.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        dict[str, list[str]]: Mapping of canonical team name to list of aliases.

    Raises:
        FileNotFoundError: If team_aliases.json does not exist.
        json.JSONDecodeError: If team_aliases.json contains invalid JSON.
    """
    path = _resolve_data_dir(data_dir) / "team_aliases.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_teams(data_dir: Path | str | None = None) -> dict[str, dict]:
    """Load teams from teams.json.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        dict[str, dict]: Mapping of team name to team data (e.g. {"elo": 2100}).

    Raises:
        FileNotFoundError: If teams.json does not exist.
        json.JSONDecodeError: If teams.json contains invalid JSON.
    """
    path = _resolve_data_dir(data_dir) / "teams.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_bracket(data_dir: Path | str | None = None) -> list[dict]:
    """Load bracket from bracket.json and validate its structure.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        list[dict]: List of match objects from the bracket.

    Raises:
        FileNotFoundError: If bracket.json does not exist.
        json.JSONDecodeError: If bracket.json contains invalid JSON.
        ValueError: If bracket validation fails.
    """
    path = _resolve_data_dir(data_dir) / "bracket.json"
    with open(path, encoding="utf-8") as f:
        bracket: list[dict] = json.load(f)
    validate_bracket(bracket)
    return bracket


def load_played(data_dir: Path | str | None = None) -> dict[str, dict]:
    """Load played matches from played.json.

    Args:
        data_dir: Directory containing the JSON files. Defaults to constants.DATA_DIR.

    Returns:
        dict[str, dict]: Mapping of match_id to match result data.

    Raises:
        FileNotFoundError: If played.json does not exist.
        json.JSONDecodeError: If played.json contains invalid JSON.
    """
    path = _resolve_data_dir(data_dir) / "played.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ─── Save functions ──────────────────────────────────────────────────────


def _atomic_write_json(data: dict | list, path: Path) -> None:
    """Write JSON data to a file atomically using tempfile + os.replace.

    Uses mkstemp (not NamedTemporaryFile) for Windows compatibility.
    Temp file is created in the same directory as the target to guarantee
    same-filesystem rename (os.replace is atomic only on same filesystem).

    Args:
        data: JSON-serializable data to write.
        path: Target file path.

    Raises:
        OSError: If file writing fails.
        TypeError: If data is not JSON-serializable.
    """
    dir_path = path.parent
    dir_path.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(dir_path),
        prefix=path.stem + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(path))
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_teams(teams: dict[str, dict], data_dir: Path | str | None = None) -> None:
    """Save teams data to teams.json atomically.

    Args:
        teams: Mapping of team name to team data dict.
        data_dir: Directory for the JSON files. Defaults to constants.DATA_DIR.
    """
    path = _resolve_data_dir(data_dir) / "teams.json"
    _atomic_write_json(teams, path)


def save_bracket(bracket: list[dict], data_dir: Path | str | None = None) -> None:
    """Save bracket data to bracket.json atomically.

    Args:
        bracket: List of match objects.
        data_dir: Directory for the JSON files. Defaults to constants.DATA_DIR.
    """
    path = _resolve_data_dir(data_dir) / "bracket.json"
    _atomic_write_json(bracket, path)


def save_played(played: dict[str, dict], data_dir: Path | str | None = None) -> None:
    """Save played match data to played.json atomically.

    Args:
        played: Mapping of match_id to match result dict.
        data_dir: Directory for the JSON files. Defaults to constants.DATA_DIR.
    """
    path = _resolve_data_dir(data_dir) / "played.json"
    _atomic_write_json(played, path)


# ─── Validation ──────────────────────────────────────────────────────────


def validate_bracket(matches: list[dict[str, Any]]) -> None:
    """Validate bracket structure. Raises ValueError on failure.

    Validates:
    1. All match_ids are unique.
    2. Every source_matches reference exists as a match_id.
    3. No circular dependencies in source_matches (should be a DAG).

    Args:
        matches: List of match objects from bracket.json.

    Raises:
        ValueError: If any validation check fails, with a descriptive message.
    """
    # Step 1: Uniqueness check
    match_ids: set[str] = set()
    for match in matches:
        mid = match["match_id"]
        if mid in match_ids:
            raise ValueError(f"Duplicate match_id: {mid}")
        match_ids.add(mid)

    # Step 2: Reference integrity
    for match in matches:
        sources = match.get("source_matches")
        if sources:
            for src in sources:
                if src not in match_ids:
                    raise ValueError(
                        f"Match '{match['match_id']}' references "
                        f"non-existent source_match '{src}'"
                    )

    # Step 3: Cycle detection via 3-color DFS
    # Build adjacency: for each match, edges go from source → current match_id
    adj: dict[str, list[str]] = {mid: [] for mid in match_ids}
    for match in matches:
        sources = match.get("source_matches")
        if sources:
            for src in sources:
                adj[src].append(match["match_id"])

    # 3-color DFS: 0=unvisited, 1=in-progress, 2=done
    color: dict[str, int] = {mid: 0 for mid in match_ids}

    def _dfs(node: str) -> None:
        color[node] = 1  # in progress
        for neighbor in adj[node]:
            if color[neighbor] == 1:
                raise ValueError(
                    f"Circular dependency detected involving matches: {node}, {neighbor}"
                )
            if color[neighbor] == 0:
                _dfs(neighbor)
        color[node] = 2  # done

    for mid in match_ids:
        if color[mid] == 0:
            _dfs(mid)


# ─── Helpers ──────────────────────────────────────────────────────────────


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    """Resolve the data directory, defaulting to constants.DATA_DIR."""
    if data_dir is None:
        result = constants.DATA_DIR
    else:
        result = data_dir
    return Path(result) if isinstance(result, str) else result
