"""Regression tests locking in the backfilled historical UCL dataset.

Verifies the committed dataset under ``data/historical/``: match counts,
id uniqueness, chronological integrity, honest signal availability, and the
chronological evaluation gate verdict for every season. A failure here means
the committed historical replay is corrupt or leaky — not merely unhelpful.
"""

from __future__ import annotations

import json
import os

import pytest

from competitions.ucl.historical_backfill.contract import HISTORICAL_DIR
from competitions.ucl.src.gate import evaluate_matches
from competitions.ucl.src.historical import (
    available_signals,
    load_replay_matches,
    split_chronological,
)

EXPECTED_MATCH_COUNTS = {
    "2019_20": 119,
    "2020_21": 125,
    "2021_22": 125,
    "2022_23": 125,
    "2023_24": 125,
}

SQUAD = "squad_value"


def _load_season(season: str) -> tuple[list[dict], dict[str, float]]:
    matches = load_replay_matches(os.path.join(HISTORICAL_DIR, season, "matches.json"))
    with open(os.path.join(HISTORICAL_DIR, season, "elo_ratings.json")) as f:
        elo: dict[str, float] = json.load(f)
    return matches, elo


def test_dataset_exists_and_counts_match():
    for season, expected in EXPECTED_MATCH_COUNTS.items():
        matches, _ = _load_season(season)
        assert len(matches) == expected, f"{season}: expected {expected}, got {len(matches)}"


def test_no_duplicate_match_ids():
    for season in EXPECTED_MATCH_COUNTS:
        matches, _ = _load_season(season)
        ids = [m["match_id"] for m in matches]
        assert len(ids) == len(set(ids)), f"{season}: duplicate match ids"


def test_match_row_schema_complete():
    required = {"match_id", "team_a", "team_b", "home_score", "away_score", "event_date"}
    for season in EXPECTED_MATCH_COUNTS:
        matches, _ = _load_season(season)
        for m in matches:
            missing = required - set(m)
            assert not missing, f"{season} {m.get('match_id')}: missing {missing}"


def test_chronological_split_is_date_driven():
    for season in EXPECTED_MATCH_COUNTS:
        matches, _ = _load_season(season)
        _, _, meta = split_chronological(matches)
        assert meta["splittable"]
        assert meta["chronology"] == "date", f"{season}: expected date chronology"
        assert meta["n_oos"] >= 30


def test_signal_availability_is_honest():
    for season in EXPECTED_MATCH_COUNTS:
        matches, elo = _load_season(season)
        avail = available_signals(matches, elo_ratings=elo)
        assert avail["refined_elo"] == "available"
        assert avail["rolling_form"] == "available"
        assert avail["rest_days"] == "available"
        assert avail[SQUAD].startswith("insufficient_data")  # omitted, never fabricated
        if season == "2019_20":
            # market odds unavailable in the prebuilt dataset for this season
            assert avail["market_odds"].startswith("insufficient_data")
        else:
            assert avail["market_odds"] == "available"


def test_evaluation_gate_passes_every_season():
    for season in EXPECTED_MATCH_COUNTS:
        matches, elo = _load_season(season)
        ev = evaluate_matches(matches, elo_ratings=elo)
        verdict = ev["verdict"]
        assert ev["chronology"] == "date"
        assert ev["n_real_signals"] >= 2
        assert verdict["status"] == "PASS", f"{season}: {verdict['reasons']}"