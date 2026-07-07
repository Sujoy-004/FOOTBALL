"""UCL Live Monitor — incremental Elo updates and periodic ClubElo sync.

Two public functions:
  - apply_elo_update(): match-by-match Elo increment with restart guard
  - sync_elo_from_clubelo(): periodic external sync with graduated correction
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

import requests

from football_core import elo as core_elo
from football_core.elo_sync import (
    apply_graduated_correction,
    fetch_eloratings_tsv,
    parse_eloratings_tsv,
)
from football_core.state import save_teams

logger = logging.getLogger(__name__)

CLUBELO_TSV_URL = "https://www.clubelo.com/ClubElo.tsv"
CLUBELO_TIMEOUT = 15


def apply_elo_update(
    match: dict[str, Any],
    elo_ratings: dict[str, float],
    elo_applied: list[str],
) -> dict | None:
    """Apply incremental Elo update for a single finished match.

    Args:
        match: BSD match event with keys: match_id, home_team, away_team,
               home_score, away_score, winner.
        elo_ratings: Mutable dict mapping team_name -> elo. Modified in-place.
        elo_applied: List of match_ids already processed. Appended after apply.

    Returns:
        Correction dict with match_id, home, away, deltas, or None if skipped.
    """
    mid = match.get("match_id", "")
    if not mid:
        return None
    if mid in elo_applied:
        return None

    home_team = match.get("home_team", "")
    away_team = match.get("away_team", "")
    if home_team not in elo_ratings or away_team not in elo_ratings:
        logger.warning("Team not in elo_ratings: %s / %s", home_team, away_team)
        return None

    home_score = match.get("home_score")
    away_score = match.get("away_score")
    if home_score is None or away_score is None:
        logger.error("Missing scores for match %s", mid)
        return None

    winner = match.get("winner")
    home_before = elo_ratings[home_team]
    away_before = elo_ratings[away_team]

    goal_diff = abs(home_score - away_score)
    k_factor = core_elo.compute_k_factor(goal_diff)

    pk_winner = None
    if match.get("is_draw") is False and winner is not None:
        pk_winner = winner

    ratings_update = core_elo.update_ratings(
        home_team,
        away_team,
        winner,
        elo_ratings,
        K=int(round(k_factor)),
        pk_winner=pk_winner,
    )

    elo_ratings[home_team] = ratings_update[home_team]
    elo_ratings[away_team] = ratings_update[away_team]
    elo_applied.append(mid)

    return {
        "match_id": mid,
        "home": {"team": home_team, "elo_before": home_before, "elo_after": ratings_update[home_team]},
        "away": {"team": away_team, "elo_before": away_before, "elo_after": ratings_update[away_team]},
        "delta_home": round(ratings_update[home_team] - home_before, 1),
        "delta_away": round(ratings_update[away_team] - away_before, 1),
    }


def _parse_clubelo_tsv(tsv_raw: str) -> list[tuple[str, float]]:
    """Fallback parser for ClubElo TSV format (rank, club, country, rating, *rest)."""
    import csv
    import io

    result: list[tuple[str, float]] = []
    reader = csv.reader(io.StringIO(tsv_raw), delimiter="\t")
    for row in reader:
        if not row or len(row) < 4:
            continue
        club = row[1].strip() if len(row) > 1 else ""
        if not club:
            continue
        try:
            rating = float(row[3])
        except (ValueError, TypeError):
            continue
        result.append((club, rating))
    return result


def _try_load_cached_tsv(data_dir: str | None) -> str | None:
    """Load cached ClubElo TSV from disk, if available."""
    if not data_dir:
        return None
    cache_path = Path(data_dir) / "clubelo_cache.tsv"
    if cache_path.exists():
        try:
            return cache_path.read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _save_tsv_cache(tsv_raw: str, data_dir: str | None) -> None:
    """Persist ClubElo TSV to disk as cache."""
    if not data_dir:
        return
    cache_path = Path(data_dir) / "clubelo_cache.tsv"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cache_path.write_text(tsv_raw, encoding="utf-8")
    except OSError:
        pass


def sync_elo_from_clubelo(
    teams: dict[str, dict],
    elo_applied: list[str],
    data_dir: str | None = None,
) -> list[dict]:
    """Periodic external Elo sync from ClubElo with graduated correction.

    Args:
        teams: Mutable dict mapping team_name -> team_data (contains "elo" key).
               Modified in-place.
        elo_applied: List of match_ids already processed (informational only).
        data_dir: Optional data directory for cache and teams.json.

    Returns:
        List of correction dicts (team, elo_before, elo_after, drift, reason).
    """
    if elo_applied:
        logger.info(
            "%d match Elos applied this session — ClubElo sync may overwrite recent updates",
            len(elo_applied),
        )

    tsv_raw = fetch_eloratings_tsv(url=CLUBELO_TSV_URL)
    if tsv_raw is None:
        logger.warning("ClubElo fetch failed — trying cache")
        tsv_raw = _try_load_cached_tsv(data_dir)
        if tsv_raw is None:
            logger.warning("No cached ClubElo data available — skipping sync")
            return []

    _save_tsv_cache(tsv_raw, data_dir)

    parsed: list[tuple[str, float]] = []
    try:
        parsed = parse_eloratings_tsv(tsv_raw)
    except Exception:
        logger.warning("Standard TSV parse failed — trying ClubElo fallback parser")
        try:
            parsed = _parse_clubelo_tsv(tsv_raw)
        except Exception as e:
            logger.error("ClubElo TSV parse failed: %s", e)
            return []

    if not parsed:
        logger.warning("ClubElo TSV parsed zero entries")
        return []

    team_names = set(teams.keys())
    parsed_values: dict[str, float] = {}
    for code, rating in parsed:
        if code in team_names:
            parsed_values[code] = rating
        else:
            logger.debug("Skipping unknown team from ClubElo: %s", code)

    if not parsed_values:
        logger.info("No matching teams found in ClubElo data")
        return []

    corrections = apply_graduated_correction(teams, parsed_values)

    if corrections:
        save_teams(teams, data_dir=data_dir)

    return corrections
