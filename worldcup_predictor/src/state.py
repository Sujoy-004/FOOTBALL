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


def validate_groups(groups: dict, teams: dict[str, dict] | None = None) -> None:
    """Validate groups.json structure. Raises ValueError on failure.

    Validates:
    1. 'groups' key exists and has exactly GROUP_COUNT entries (A-L).
    2. Each group has exactly TEAMS_PER_GROUP teams and MATCHES_PER_GROUP matches.
    3. Match IDs follow pattern GS_{letter}_{NN} and are unique.
    4. No duplicate teams across groups.
    5. All team names exist in teams dict if provided.

    Args:
        groups: The groups object loaded from groups.json.
        teams: Optional dict of valid teams for cross-reference validation.

    Raises:
        ValueError: If any validation check fails, with a descriptive message.
    """
    # Step 1: Check 'groups' key exists
    if not isinstance(groups, dict) or "groups" not in groups:
        raise ValueError("groups data must contain 'groups' key")

    group_data = groups["groups"]

    # Step 2: Check group count
    if len(group_data) != constants.GROUP_COUNT:
        raise ValueError(
            f"Expected {constants.GROUP_COUNT} groups, got {len(group_data)}"
        )

    # Step 3: Check group keys are exactly A-L
    expected_keys: set[str] = set("ABCDEFGHIJKL")
    actual_keys: set[str] = set(group_data.keys())
    if actual_keys != expected_keys:
        missing = expected_keys - actual_keys
        extra = actual_keys - expected_keys
        parts: list[str] = []
        if missing:
            parts.append(f"missing: {''.join(sorted(missing))}")
        if extra:
            parts.append(f"extra: {''.join(sorted(extra))}")
        raise ValueError(f"Invalid group keys: {'; '.join(parts)}")

    seen_teams: set[str] = set()
    seen_match_ids: set[str] = set()

    # Step 4: Validate each group (deterministic order)
    for letter in sorted(group_data.keys()):
        group = group_data[letter]

        # 4a: Check teams/matches keys exist
        if "teams" not in group or "matches" not in group:
            raise ValueError(f"Group {letter}: missing 'teams' or 'matches' key")

        # 4b: Check team count
        if len(group["teams"]) != constants.TEAMS_PER_GROUP:
            raise ValueError(
                f"Group {letter}: expected {constants.TEAMS_PER_GROUP} teams, "
                f"got {len(group['teams'])}"
            )

        # 4c: Check match count
        if len(group["matches"]) != constants.MATCHES_PER_GROUP:
            raise ValueError(
                f"Group {letter}: expected {constants.MATCHES_PER_GROUP} matches, "
                f"got {len(group['matches'])}"
            )

        # 4d: Check team names are non-empty strings
        for team in group["teams"]:
            if not isinstance(team, str) or not team:
                raise ValueError(f"Group {letter}: invalid team name: '{team}'")

        # 4e: Check match structure
        for match in group["matches"]:
            for key in ("match_id", "team_a", "team_b"):
                if key not in match:
                    raise ValueError(
                        f"Group {letter}: match missing '{key}' key"
                    )
            for key in ("winner", "score_a", "score_b"):
                if key not in match:
                    raise ValueError(
                        f"Group {letter}: match missing '{key}' key"
                    )

        # 4f: Check match_id prefix
        for match in group["matches"]:
            mid = match["match_id"]
            if not mid.startswith(f"GS_{letter}_"):
                raise ValueError(
                    f"Group {letter}: match_id '{mid}' does not start with "
                    f"'GS_{letter}_'"
                )

        # Step 5: Check no duplicate teams across groups
        for team in group["teams"]:
            if team in seen_teams:
                raise ValueError(f"Team '{team}' appears in multiple groups")
            seen_teams.add(team)

        # Step 6: Check no duplicate match_ids across groups
        for match in group["matches"]:
            mid = match["match_id"]
            if mid in seen_match_ids:
                raise ValueError(f"Duplicate match_id across groups: {mid}")
            seen_match_ids.add(mid)

    # Step 7: Cross-reference team names with teams dict if provided
    if teams is not None:
        for letter in sorted(group_data.keys()):
            for team in group_data[letter]["teams"]:
                if team not in teams:
                    raise ValueError(
                        f"Team '{team}' not found in teams data"
                    )


def load_groups(
    data_dir: Path | str | None = None,
    teams: dict[str, dict] | None = None,
) -> dict:
    """Load group definitions from groups.json and validate structure.

    Args:
        data_dir: Directory containing the JSON files. Defaults to
            constants.DATA_DIR.
        teams: Optional teams dict for cross-reference validation.

    Returns:
        dict: The groups object with 'groups' key mapping to A-L entries.

    Raises:
        FileNotFoundError: If groups.json does not exist.
        json.JSONDecodeError: If groups.json contains invalid JSON.
        ValueError: If group validation fails.
    """
    path = _resolve_data_dir(data_dir) / "groups.json"
    with open(path, encoding="utf-8") as f:
        groups: dict = json.load(f)
    validate_groups(groups, teams=teams)
    return groups


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


def validate_annex_c(annex_c: dict) -> None:
    """Validate annex_c.json structure. Raises ValueError on failure.

    Validates:
    1. Exactly ANNEX_C_ENTRIES keys (495 = C(12,8)).
    2. Every key contains 8 sorted, comma-separated group letters (A-L).
    3. Every value has exactly 8 assignment keys (1A, 1B, 1D, 1E, 1G, 1I, 1K, 1L).
    4. No self-references (e.g., '1A' never maps to '3A').
    5. No value references a group letter not in the key.

    Args:
        annex_c: The Annex C lookup table loaded from annex_c.json.

    Raises:
        ValueError: If any validation check fails, with a descriptive message.
    """
    # Step 1: Verify it's a dict
    if not isinstance(annex_c, dict):
        raise ValueError("Annex C data must be a dict")

    # Step 2: Extract data keys (exclude _meta)
    data_keys: dict[str, Any] = {
        k: v for k, v in annex_c.items() if k != "_meta"
    }

    if len(data_keys) != constants.ANNEX_C_ENTRIES:
        raise ValueError(
            f"Expected {constants.ANNEX_C_ENTRIES} Annex C entries, "
            f"got {len(data_keys)}"
        )

    valid_groups: set[str] = set("ABCDEFGHIJKL")
    expected_value_keys: set[str] = {
        "1A", "1B", "1D", "1E", "1G", "1I", "1K", "1L",
    }

    # Step 3: Validate each entry (deterministic order)
    for key in sorted(data_keys.keys()):
        value = data_keys[key]

        # 3a: Split key and verify parts count
        parts = key.split(",")
        if len(parts) != 8:
            raise ValueError(
                f"Annex C key '{key}': expected 8 groups, got {len(parts)}"
            )

        # 3b: Verify groups are sorted alphabetically
        if parts != sorted(parts):
            raise ValueError(
                f"Annex C key '{key}': groups not sorted alphabetically"
            )

        # 3c: Verify every part is a valid group letter
        for part in parts:
            if part not in valid_groups:
                raise ValueError(
                    f"Annex C key '{key}': invalid group letter '{part}'"
                )

        # 3d: Verify no duplicate letters
        if len(set(parts)) != 8:
            raise ValueError(
                f"Annex C key '{key}': duplicate group letter"
            )

        # 3e: Verify value structure
        if not isinstance(value, dict):
            raise ValueError(
                f"Annex C entry '{key}': expected a dict, "
                f"got {type(value).__name__}"
            )

        actual_keys = set(value.keys())
        if actual_keys != expected_value_keys:
            raise ValueError(
                f"Annex C entry '{key}': missing or extra assignment keys. "
                f"Expected {sorted(expected_value_keys)}, "
                f"got {sorted(actual_keys)}"
            )

        # 3f: Validate each assignment (no self-reference, no out-of-key ref)
        for vk, v in value.items():
            # Extract referenced group: "3H" -> "H"
            if not isinstance(v, str) or not v.startswith("3") or len(v) != 2:
                raise ValueError(
                    f"Annex C entry '{key}': invalid reference '{v}'"
                )
            ref = v[1]  # Second character is the group letter

            if ref not in valid_groups:
                raise ValueError(
                    f"Annex C entry '{key}': invalid reference '{v}'"
                )

            if ref not in parts:
                raise ValueError(
                    f"Annex C entry '{key}': references group {ref} "
                    f"not in key"
                )

            # Check self-reference: value key's group must differ from ref
            vk_group = vk[1]  # e.g., "1A" -> "A"
            if vk_group == ref:
                raise ValueError(
                    f"Annex C entry '{key}': self-reference "
                    f"'{vk}' -> '{v}'"
                )


def load_annex_c(data_dir: Path | str | None = None) -> dict:
    """Load Annex C lookup table from annex_c.json and validate.

    Args:
        data_dir: Directory containing the JSON files. Defaults to
            constants.DATA_DIR.

    Returns:
        dict: The Annex C table with 495 entries plus optional _meta key.

    Raises:
        FileNotFoundError: If annex_c.json does not exist.
        json.JSONDecodeError: If annex_c.json contains invalid JSON.
        ValueError: If Annex C validation fails.
    """
    path = _resolve_data_dir(data_dir) / "annex_c.json"
    with open(path, encoding="utf-8") as f:
        annex_c: dict = json.load(f)
    validate_annex_c(annex_c)
    return annex_c


# ─── Helpers ──────────────────────────────────────────────────────────────


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    """Resolve the data directory, defaulting to constants.DATA_DIR."""
    if data_dir is None:
        result = constants.DATA_DIR
    else:
        result = data_dir
    return Path(result) if isinstance(result, str) else result
