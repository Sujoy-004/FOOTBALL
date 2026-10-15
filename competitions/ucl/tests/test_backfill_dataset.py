"""Regression tests locking in the backfilled historical UCL dataset.

Verifies the committed dataset under ``data/historical/``: real coverage of
the contract window, id uniqueness, chronological integrity, honest signal
availability, and the chronological evaluation gate verdict for every
accepted season. A failure here means the committed historical replay is
corrupt or leaky — not merely unhelpful.

The window is derived from ``contract.SEASONS`` (the single source of
truth), never from a hardcoded season list: the contract REQUESTS
2000/01-2025/26, but the keyless openfootball source only serves
2011/12 onward, so the accepted corpus is the verified subset and the
pre-2011/12 block is excluded-and-reported (see data/historical/COVERAGE.md).
"""

from __future__ import annotations

import json
import os

from competitions.ucl.historical_backfill.contract import (
    HISTORICAL_DIR,
    SEASONS,
    season_dir,
)
from competitions.ucl.src.gate import evaluate_matches
from competitions.ucl.src.historical import (
    available_signals,
    load_replay_matches,
    split_chronological,
)

# The verified window: every contract season with a committed dataset
# directory (mirrors evaluate.py). Exclusions are the source-absent
# 2000/01-2010/11 block, reported in COVERAGE.md — never fabricated.
COMMITTED_SEASONS = [s for s in SEASONS if os.path.isdir(season_dir(s))]

# A real UCL season (any in-window format era) holds 119-189 matches; a
# committed season with fewer is a truncated or padded parse.
MIN_SEASON_MATCHES = 100

# The prebuilt closing-odds dataset only starts its UCL coverage 2020-12,
# so market odds are available from 2020/21 onward and honestly absent
# (insufficient_data, never fabricated) before that boundary.
FIRST_ODDS_SEASON = "2020_21"

SQUAD = "squad_value"


def _load_season(season: str) -> tuple[list[dict], dict[str, float]]:
    matches = load_replay_matches(os.path.join(HISTORICAL_DIR, season, "matches.json"))
    with open(os.path.join(HISTORICAL_DIR, season, "elo_ratings.json")) as f:
        elo: dict[str, float] = json.load(f)
    return matches, elo


def test_contract_window_is_the_d01_window():
    assert list(SEASONS)[0] == "2000_01"
    assert list(SEASONS)[-1] == "2025_26"
    assert len(SEASONS) >= 20


def test_accepted_seasons_are_the_verified_subset():
    assert COMMITTED_SEASONS, "no committed UCL historical seasons on disk"
    assert COMMITTED_SEASONS[0] == "2011_12"  # openfootball source reach
    # Every contract season outside the committed set must be in the
    # source-absent pre-2011/12 block — no silent exclusion elsewhere.
    for season in SEASONS:
        if season not in COMMITTED_SEASONS:
            assert season < "2011_12", (
                f"{season} has no committed dataset and is not in the "
                "documented source-absent 2000/01-2010/11 exclusion block"
            )


def test_dataset_counts_match_the_committed_files():
    for season in COMMITTED_SEASONS:
        matches, _ = _load_season(season)
        assert len(matches) >= MIN_SEASON_MATCHES, (
            f"{season}: only {len(matches)} matches committed "
            f"(< {MIN_SEASON_MATCHES}) — truncated or padded parse?"
        )


def test_no_duplicate_match_ids():
    for season in COMMITTED_SEASONS:
        matches, _ = _load_season(season)
        ids = [m["match_id"] for m in matches]
        assert len(ids) == len(set(ids)), f"{season}: duplicate match ids"


def test_match_row_schema_complete():
    required = {"match_id", "team_a", "team_b", "home_score", "away_score", "event_date"}
    for season in COMMITTED_SEASONS:
        matches, _ = _load_season(season)
        for m in matches:
            missing = required - set(m)
            assert not missing, f"{season} {m.get('match_id')}: missing {missing}"


def test_chronological_split_is_date_driven():
    for season in COMMITTED_SEASONS:
        matches, _ = _load_season(season)
        _, _, meta = split_chronological(matches)
        assert meta["splittable"]
        assert meta["chronology"] == "date", f"{season}: expected date chronology"
        assert meta["n_oos"] >= 30


def test_signal_availability_is_honest():
    for season in COMMITTED_SEASONS:
        matches, elo = _load_season(season)
        avail = available_signals(matches, elo_ratings=elo)
        assert avail["refined_elo"] == "available"
        assert avail["rolling_form"] == "available"
        assert avail["rest_days"] == "available"
        assert avail[SQUAD].startswith("insufficient_data")  # omitted, never fabricated
        # Market odds follow the prebuilt dataset's real coverage boundary
        # (closing odds start 2020-12): available from 2020/21 onward,
        # honestly insufficient before — never fabricated either way.
        if season >= FIRST_ODDS_SEASON:
            assert avail["market_odds"] == "available"
        else:
            assert avail["market_odds"].startswith("insufficient_data")


def test_evaluation_gate_passes_every_season():
    for season in COMMITTED_SEASONS:
        matches, elo = _load_season(season)
        ev = evaluate_matches(matches, elo_ratings=elo)
        verdict = ev["verdict"]
        assert ev["chronology"] == "date"
        assert ev["n_real_signals"] >= 2
        assert verdict["status"] == "PASS", f"{season}: {verdict['reasons']}"
