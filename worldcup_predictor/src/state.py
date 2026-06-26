"""State persistence — extends football_core with WC-specific validation and advanced features."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from football_core.state import (
    load_teams,
    save_teams,
    load_played,
    save_played,
    load_played_groups,
    save_played_groups,
    load_signal_cache,
    save_signal_cache,
    load_prediction_history,
    append_prediction_history,
    is_cache_valid,
    load_eloratings_cache,
    save_eloratings_cache,
    load_elo_update_log,
    save_elo_update_log,
    validate_bracket,
    load_probability_log,
    append_probability_log,
    _atomic_write_json,
    _resolve_data_dir as _resolve_data_dir_core,
)

from src import constants


def _resolve_data_dir(data_dir: Path | str | None) -> Path:
    if data_dir is None:
        return Path(constants.DATA_DIR)
    return Path(data_dir) if isinstance(data_dir, str) else data_dir


def load_bracket(data_dir: Path | str | None = None) -> list[dict]:
    from football_core.state import load_bracket as _load_bracket_core
    return _load_bracket_core(str(_resolve_data_dir(data_dir)))


def load_aliases(data_dir: Path | str | None = None) -> dict[str, list[str]]:
    path = _resolve_data_dir(data_dir) / "team_aliases.json"
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_team_values(data_dir: Path | str | None = None) -> dict[str, int]:
    from src.constants import TEAM_VALUES_FILE
    path = _resolve_data_dir(data_dir) / TEAM_VALUES_FILE
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def save_eloratings_cache(cache: dict, data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "eloratings_cache.json"
    _atomic_write_json(cache, path)


def load_elo_applied(data_dir: Path | str | None = None) -> set[str]:
    path = _resolve_data_dir(data_dir) / "elo_applied.json"
    if not path.exists():
        return set()
    with open(path, encoding="utf-8") as f:
        data: list[str] = json.load(f)
    return set(data)


def save_elo_applied(elo_applied: set[str], data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "elo_applied.json"
    _atomic_write_json(sorted(elo_applied), path)


# ─── WC-specific validation ────────────────────────────────────────────

def validate_groups(groups: dict, teams: dict[str, dict] | None = None) -> None:
    if not isinstance(groups, dict) or "groups" not in groups:
        raise ValueError("groups data must contain 'groups' key")

    group_data = groups["groups"]

    if len(group_data) != constants.GROUP_COUNT:
        raise ValueError(
            f"Expected {constants.GROUP_COUNT} groups, got {len(group_data)}"
        )

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

    for letter in sorted(group_data.keys()):
        group = group_data[letter]

        if "teams" not in group or "matches" not in group:
            raise ValueError(f"Group {letter}: missing 'teams' or 'matches' key")

        if len(group["teams"]) != constants.TEAMS_PER_GROUP:
            raise ValueError(
                f"Group {letter}: expected {constants.TEAMS_PER_GROUP} teams, "
                f"got {len(group['teams'])}"
            )

        if len(group["matches"]) != constants.MATCHES_PER_GROUP:
            raise ValueError(
                f"Group {letter}: expected {constants.MATCHES_PER_GROUP} matches, "
                f"got {len(group['matches'])}"
            )

        for team in group["teams"]:
            if not isinstance(team, str) or not team:
                raise ValueError(f"Group {letter}: invalid team name: '{team}'")

        for match in group["matches"]:
            for key in ("match_id", "team_a", "team_b"):
                if key not in match:
                    raise ValueError(f"Group {letter}: match missing '{key}' key")
            for key in ("winner", "score_a", "score_b"):
                if key not in match:
                    raise ValueError(f"Group {letter}: match missing '{key}' key")

        for match in group["matches"]:
            mid = match["match_id"]
            if not mid.startswith(f"GS_{letter}_"):
                raise ValueError(
                    f"Group {letter}: match_id '{mid}' does not start with "
                    f"'GS_{letter}_'"
                )

        for team in group["teams"]:
            if team in seen_teams:
                raise ValueError(f"Team '{team}' appears in multiple groups")
            seen_teams.add(team)

        for match in group["matches"]:
            mid = match["match_id"]
            if mid in seen_match_ids:
                raise ValueError(f"Duplicate match_id across groups: {mid}")
            seen_match_ids.add(mid)

    if teams is not None:
        for letter in sorted(group_data.keys()):
            for team in group_data[letter]["teams"]:
                if team not in teams:
                    raise ValueError(f"Team '{team}' not found in teams data")


def load_groups(
    data_dir: Path | str | None = None,
    teams: dict[str, dict] | None = None,
) -> dict:
    path = _resolve_data_dir(data_dir) / "groups.json"
    with open(path, encoding="utf-8") as f:
        groups: dict = json.load(f)
    validate_groups(groups, teams=teams)
    return groups


def validate_annex_c(annex_c: dict) -> None:
    if not isinstance(annex_c, dict):
        raise ValueError("Annex C data must be a dict")

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

    for key in sorted(data_keys.keys()):
        value = data_keys[key]
        parts = key.split(",")
        if len(parts) != 8:
            raise ValueError(f"Annex C key '{key}': expected 8 groups, got {len(parts)}")
        if parts != sorted(parts):
            raise ValueError(f"Annex C key '{key}': groups not sorted alphabetically")
        for part in parts:
            if part not in valid_groups:
                raise ValueError(f"Annex C key '{key}': invalid group letter '{part}'")
        if len(set(parts)) != 8:
            raise ValueError(f"Annex C key '{key}': duplicate group letter")
        if not isinstance(value, dict):
            raise ValueError(f"Annex C entry '{key}': expected a dict, got {type(value).__name__}")
        actual_keys = set(value.keys())
        if actual_keys != expected_value_keys:
            raise ValueError(
                f"Annex C entry '{key}': missing or extra assignment keys. "
                f"Expected {sorted(expected_value_keys)}, got {sorted(actual_keys)}"
            )
        for vk, v in value.items():
            if not isinstance(v, str) or not v.startswith("3") or len(v) != 2:
                raise ValueError(f"Annex C entry '{key}': invalid reference '{v}'")
            ref = v[1]
            if ref not in valid_groups:
                raise ValueError(f"Annex C entry '{key}': invalid reference '{v}'")
            if ref not in parts:
                raise ValueError(f"Annex C entry '{key}': references group {ref} not in key")
            vk_group = vk[1]
            if vk_group == ref:
                raise ValueError(f"Annex C entry '{key}': self-reference '{vk}' -> '{v}'")


def load_annex_c(data_dir: Path | str | None = None) -> dict:
    path = _resolve_data_dir(data_dir) / "annex_c.json"
    with open(path, encoding="utf-8") as f:
        annex_c: dict = json.load(f)
    validate_annex_c(annex_c)
    return annex_c


# ─── Prediction History ─────────────────────────────────────────────────

def save_prediction_history(history: list[dict], data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "prediction_history.json"
    _atomic_write_json(history, path)


def migrate_prediction_history(data_dir: Path | str | None = None) -> int:
    history = load_prediction_history(data_dir)
    if not history:
        return 0
    has_flat = any("signal" in entry for entry in history)
    if not has_flat:
        return 0
    n_migrated = 0
    migrated: list[dict] = []
    for entry in history:
        if "signal" in entry:
            signal_name = entry.get("signal", "elo")
            signals = {
                signal_name: {
                    "probability": entry.get("prediction"),
                    "version": "v1",
                    "timestamp": entry.get("timestamp"),
                    "available": True,
                }
            }
            if "team_a_elo" in entry:
                signals[signal_name]["team_a_elo"] = entry["team_a_elo"]
            if "team_b_elo" in entry:
                signals[signal_name]["team_b_elo"] = entry["team_b_elo"]
            new_entry = {
                "match_id": entry.get("match_id", ""),
                "timestamp": entry.get("timestamp"),
                "team_a": entry.get("team_a", ""),
                "team_b": entry.get("team_b", ""),
                "actual": entry.get("actual"),
                "signals": signals,
            }
            migrated.append(new_entry)
            n_migrated += 1
        else:
            migrated.append(entry)
    save_prediction_history(migrated, data_dir)
    return n_migrated


# ─── Prediction Ledger ──────────────────────────────────────────────────

def load_prediction_ledger(data_dir: Path | str | None = None) -> dict[str, dict]:
    from src.constants import PREDICTION_LEDGER_FILE
    path = _resolve_data_dir(data_dir) / PREDICTION_LEDGER_FILE
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def save_prediction_ledger(ledger: dict, data_dir: Path | str | None = None) -> None:
    from src.constants import PREDICTION_LEDGER_FILE
    path = _resolve_data_dir(data_dir) / PREDICTION_LEDGER_FILE
    _atomic_write_json(ledger, path)


def ledger_upsert(
    match_id: str,
    signal_name: str,
    entry: dict,
    data_dir: Path | str | None = None,
) -> None:
    ledger = load_prediction_ledger(data_dir)
    if match_id not in ledger:
        ledger[match_id] = {}
    ledger[match_id][signal_name] = entry
    save_prediction_ledger(ledger, data_dir)


# ─── Eval / Calibration ─────────────────────────────────────────────────

def save_eval_baseline_report(
    report: dict,
    data_dir: Path | str | None = None,
) -> None:
    path = _resolve_data_dir(data_dir) / "eval_baseline_report.json"
    _atomic_write_json(report, path)


def load_calibration_params(data_dir: Path | str | None = None) -> dict:
    path = _resolve_data_dir(data_dir) / constants.CALIBRATION_PARAMS_FILE
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def save_calibration_params(params: dict, data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / constants.CALIBRATION_PARAMS_FILE
    _atomic_write_json(params, path)


# ─── Governance ─────────────────────────────────────────────────────────

def load_versions(data_dir: Path | str | None = None) -> dict:
    path = _resolve_data_dir(data_dir) / constants.GOV_DATA_FILE
    if not path.exists():
        return {
            "data_version": "D0",
            "model_version": "M0",
            "run_version": "R0",
            "last_data_change": None,
            "last_model_change": None,
            "last_run_timestamp": None,
        }
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def save_versions(versions: dict, data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / constants.GOV_DATA_FILE
    _atomic_write_json(versions, path)


def save_run_snapshot(snapshot: dict, data_dir: Path | str | None = None) -> None:
    runs_dir = _resolve_data_dir(data_dir) / constants.GOV_RUNS_DIR
    run_id = snapshot["run_version"]
    safe_id = run_id.replace(":", "-")
    path = runs_dir / f"{safe_id}.json"
    _atomic_write_json(snapshot, path)

    if constants.GOV_RUN_SNAPSHOT_RETENTION > 0:
        files = sorted(runs_dir.glob("*.json"))
        if len(files) > constants.GOV_RUN_SNAPSHOT_RETENTION:
            to_delete = len(files) - constants.GOV_RUN_SNAPSHOT_RETENTION
            for f in files[:to_delete]:
                os.remove(str(f))


def load_run_snapshot(run_id: str, data_dir: Path | str | None = None) -> dict | None:
    safe_id = run_id.replace(":", "-")
    path = _resolve_data_dir(data_dir) / constants.GOV_RUNS_DIR / f"{safe_id}.json"
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as f:
        return dict(json.load(f))


def save_backtest_report(report: dict, data_dir: Path | str | None = None) -> None:
    path = _resolve_data_dir(data_dir) / "eval_backtest_report.json"
    _atomic_write_json(report, path)
