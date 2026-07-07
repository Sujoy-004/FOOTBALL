"""UCL Live Monitor state persistence — thin wrapper around football_core.state for UCL-specific paths and file names."""

import json
import logging
import os
from pathlib import Path
from typing import Any

from football_core.state import (
    _atomic_write_json,
    is_cache_valid,
    load_signal_cache,
    save_signal_cache,
)

logger = logging.getLogger(__name__)

LIVE_DATA_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "live"
)


def _resolve_live_dir(data_dir: str | None = None) -> str:
    if data_dir is not None:
        return data_dir
    os.makedirs(LIVE_DATA_DIR, exist_ok=True)
    return LIVE_DATA_DIR


def _ucl_path(filename: str, data_dir: str | None = None) -> Path:
    return Path(_resolve_live_dir(data_dir)) / filename


def load_ucl_played(data_dir: str | None = None) -> dict[str, dict]:
    path = _ucl_path("ucl_played.json", data_dir)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return dict(json.load(f))
    except json.JSONDecodeError:
        logger.warning("Corrupted ucl_played.json — returning empty dict")
        return {}


def save_ucl_played(played: dict[str, dict], data_dir: str | None = None) -> None:
    path = _ucl_path("ucl_played.json", data_dir)
    _atomic_write_json(played, path)


def load_ucl_elo_applied(data_dir: str | None = None) -> list[str]:
    path = _ucl_path("ucl_elo_applied.json", data_dir)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return list(json.load(f))
    except json.JSONDecodeError:
        logger.warning("Corrupted ucl_elo_applied.json — returning empty list")
        return []


def save_ucl_elo_applied(elo_applied: list[str], data_dir: str | None = None) -> None:
    path = _ucl_path("ucl_elo_applied.json", data_dir)
    _atomic_write_json(elo_applied, path)


def load_ucl_prediction_history(data_dir: str | None = None) -> list[dict]:
    path = _ucl_path("ucl_prediction_history.json", data_dir)
    if not path.exists():
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return list(json.load(f))
    except json.JSONDecodeError:
        logger.warning("Corrupted ucl_prediction_history.json — returning empty list")
        return []


def save_ucl_prediction_history(history: list[dict], data_dir: str | None = None) -> None:
    path = _ucl_path("ucl_prediction_history.json", data_dir)
    _atomic_write_json(history, path)


def append_ucl_prediction_history(entry: dict, data_dir: str | None = None) -> None:
    history = load_ucl_prediction_history(data_dir)
    history.append(entry)
    save_ucl_prediction_history(history, data_dir)


def load_ucl_cache(cache_key: str, data_dir: str | None = None) -> dict | None:
    return load_signal_cache(cache_key, _resolve_live_dir(data_dir))


def save_ucl_cache(cache_key: str, data: dict, data_dir: str | None = None, ttl_hours: int = 12) -> None:
    save_signal_cache(cache_key, data, _resolve_live_dir(data_dir), ttl_hours)


def ucl_is_cache_valid(cache: dict | None, ttl_hours: int = 12) -> bool:
    return is_cache_valid(cache, ttl_hours)
