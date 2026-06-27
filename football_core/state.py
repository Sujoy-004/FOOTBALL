"""Generic state persistence: JSON load/save with atomic writes, bracket validation, cache helpers."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    if data_dir is None:
        return Path.cwd()
    return Path(data_dir) if isinstance(data_dir, str) else data_dir


def _atomic_write_json(data: dict | list, path: Path) -> None:
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


def load_teams(data_dir: Path | str | None = None) -> dict[str, dict]:
    path = _resolve_data_dir(data_dir) / "teams.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_teams(teams: dict[str, dict], data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "teams.json"
    _atomic_write_json(teams, path)


def load_played(data_dir: Path | str | None = None) -> dict[str, dict]:
    path = _resolve_data_dir(data_dir) / "played.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_played(played: dict[str, dict], data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "played.json"
    _atomic_write_json(played, path)


def load_played_groups(data_dir: Path | str | None = None) -> dict[str, dict]:
    path = _resolve_data_dir(data_dir) / "played_groups.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_played_groups(played_groups: dict[str, dict], data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "played_groups.json"
    _atomic_write_json(played_groups, path)


def load_prediction_history(data_dir: Path | str | None = None) -> list[dict]:
    path = _resolve_data_dir(data_dir) / "prediction_history.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data: list[dict] = json.load(f)
    return data


def save_prediction_history(history: list[dict], data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "prediction_history.json"
    _atomic_write_json(history, path)


def append_prediction_history(
    entry: dict,
    data_dir: Path | str | None = None,
) -> None:
    history = load_prediction_history(data_dir)
    history.append(entry)
    path = _resolve_data_dir(data_dir) / "prediction_history.json"
    _atomic_write_json(history, path)


def load_eloratings_cache(data_dir: Path | str | None = None) -> dict:
    path = _resolve_data_dir(data_dir) / "eloratings_cache.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def save_eloratings_cache(cache: dict, data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "eloratings_cache.json"
    _atomic_write_json(cache, path)


def load_elo_update_log(data_dir: Path | str | None = None) -> list[dict]:
    path = _resolve_data_dir(data_dir) / "elo_update_log.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(json.load(f))


def save_elo_update_log(log: list[dict], data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "elo_update_log.json"
    _atomic_write_json(log, path)


def load_signal_cache(cache_filename: str, data_dir: Path | str | None = None) -> dict:
    path = _resolve_data_dir(data_dir) / cache_filename
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def save_signal_cache(cache: dict, cache_filename: str, data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / cache_filename
    _atomic_write_json(cache, path)


def is_cache_valid(cache: dict, ttl_hours: int = 12) -> bool:
    if not cache:
        return False
    expires_at = cache.get("expires_at")
    if not expires_at:
        return False
    try:
        expiry = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) < expiry
    except (ValueError, TypeError):
        return False


def validate_bracket(matches: list[dict[str, Any]]) -> None:
    match_ids: set[str] = set()
    for match in matches:
        mid = match["match_id"]
        if mid in match_ids:
            raise ValueError(f"Duplicate match_id: {mid}")
        match_ids.add(mid)

    for match in matches:
        sources = match.get("source_matches")
        if sources:
            for src in sources:
                if src not in match_ids:
                    raise ValueError(
                        f"Match '{match['match_id']}' references "
                        f"non-existent source_match '{src}'"
                    )

    adj: dict[str, list[str]] = {mid: [] for mid in match_ids}
    for match in matches:
        sources = match.get("source_matches")
        if sources:
            for src in sources:
                adj[src].append(match["match_id"])

    color: dict[str, int] = {mid: 0 for mid in match_ids}

    def _dfs(node: str) -> None:
        color[node] = 1
        for neighbor in adj[node]:
            if color[neighbor] == 1:
                raise ValueError(
                    f"Circular dependency detected involving matches: {node}, {neighbor}"
                )
            if color[neighbor] == 0:
                _dfs(neighbor)
        color[node] = 2

    for mid in match_ids:
        if color[mid] == 0:
            _dfs(mid)


def load_bracket(data_dir: Path | str | None = None) -> list[dict]:
    path = _resolve_data_dir(data_dir) / "bracket.json"
    with open(path, encoding="utf-8") as f:
        bracket: list[dict] = json.load(f)
    validate_bracket(bracket)
    return bracket


def load_probability_log(data_dir: Path | str | None = None) -> list[dict]:
    path = _resolve_data_dir(data_dir) / "probability_log.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return list(json.load(f))


def append_probability_log(snapshot: dict, data_dir: Path | str | None = None) -> None:
    log = load_probability_log(data_dir)
    log.append(snapshot)
    path = _resolve_data_dir(data_dir) / "probability_log.json"
    _atomic_write_json(log, path)
