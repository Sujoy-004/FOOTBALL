"""State persistence and bracket validation for the World Cup predictor.

All JSON state files (teams.json, bracket.json, played.json) are loaded
and saved through this module. Bracket validation ensures the tournament
structure is valid before simulation.
"""

import json
from pathlib import Path
from typing import Any

from src import constants


# ─── Load functions ──────────────────────────────────────────────────────


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
        return constants.DATA_DIR
    if isinstance(data_dir, str):
        return Path(data_dir)
    return data_dir
