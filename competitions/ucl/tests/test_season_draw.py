"""Tests for the 2026/27 UCL league-phase draw season (snapshot -> season store).

Required verification items:
1. 2025/26 historical data is byte-identical and untouched by the draw pipeline
2. 2026/27 season loads independently as its own season store
3. Exactly 36 teams in the new season (4 pots of 9)
4. Fixture/opponent relationships match the authoritative draw snapshot
5. All 2026/27 league-phase matches are unplayed (future/scheduled)
6. Simulation never writes into 2025/26 factual stores
7. Season selection (pointer) + simulation/factual separation is honoured
8. Season-scoped API state resolves to the correct season store
9. Unknown fields stay null (no invented dates/matchday numbers)
10. Acquisition is repeatable/idempotent (byte-identical re-build)
"""

from __future__ import annotations

import random
import shutil
from pathlib import Path

import pytest

from competitions.ucl.src.season_draw import (
    DRAWN_SEASON,
    activate_draw_season,
    deactivate_draw_season,
    ensure_draw_season,
    load_snapshot,
    main,
    validate_draw_season,
)
from competitions.ucl.src.seasons import (
    LOCAL_HISTORICAL_SEASON,
    get_current_season,
    list_seasons,
    read_season_fixtures,
    read_season_results,
    resolve_active_view,
    season_dir,
)
from competitions.ucl.src.validation import validate_ucl_fixtures


def _copy_repo_data_to(tmp_path: Path) -> Path:
    """Materialize a full UCL data dir from the tracked repo data.

    The runtime ``seasons/`` directory is removed so the draw builder is
    tested from a fresh acquisition every time.
    """
    repo_data = Path(__file__).resolve().parents[1] / "data"
    dp = tmp_path / "data"
    shutil.copytree(repo_data, dp)
    seasons_dir = dp / "seasons"
    if seasons_dir.is_dir():
        shutil.rmtree(seasons_dir)
    return dp


def _root_store_bytes(dp: Path) -> dict[str, bytes | None]:
    """Byte snapshot of the 2025/26 canonical root stores."""
    names = [
        "fixtures.json", "results.json", "knockout_results.json",
        "bracket_rules.json", "playoff_pairings.json",
        "team_aliases.json", "squad_values.json",
    ]
    out = {}
    for name in names:
        p = dp / name
        out[name] = p.read_bytes() if p.exists() else None
    return out


def _expected_snapshot_pairings(snapshot: dict) -> set[tuple[str, str]]:
    """Derive the 144 directed (home, away) pairings from the snapshot.

    ``opponent.home: true`` means the listed team HOSTS that opponent; the
    snapshot mirrors every pairing across both clubs, so de-dup by set.
    """
    pairs: set[tuple[str, str]] = set()
    for entry in snapshot["opponents"]:
        team = entry["team"]
        for opp in entry["opponents"]:
            if opp.get("home", True):
                pairs.add((team, opp["name"]))
            else:
                pairs.add((opp["name"], team))
    return pairs


@pytest.fixture
def draw_data_dir(tmp_path) -> Path:
    return _copy_repo_data_to(tmp_path)


@pytest.fixture
def built_draw_season(draw_data_dir) -> Path:
    ensure_draw_season(draw_data_dir)
    return draw_data_dir


class TestItem1And2_IsolationAndIndependentLoad:
    """2025/26 untouched; 2026/27 loads as its own season store."""

    def test_build_creates_only_the_drawn_season_store(self, built_draw_season):
        dp = built_draw_season
        assert list_seasons(dp) == ["2026_27"]

        doc = read_season_fixtures(dp, DRAWN_SEASON)
        assert doc is not None
        assert doc["season"] == "2026/27"
        assert len(doc["fixtures"]) == 144
        assert len(doc["schedule"]["matchdays"]) == 8

        res = read_season_results(dp, DRAWN_SEASON)
        assert res is not None
        assert res["season"] == "2026/27"
        assert res["matches"] == []

    def test_2025_26_historical_stores_untouched(self, built_draw_season):
        dp = built_draw_season
        before = _root_store_bytes(dp)
        # Re-run the build/validate cycle over the same dir.
        ensure_draw_season(dp)
        validate_draw_season(dp)
        after = _root_store_bytes(dp)
        assert before == after, "2025/26 canonical stores changed during draw build"

    def test_2025_26_view_stays_default_until_activated(self, built_draw_season):
        view = resolve_active_view(built_draw_season)
        assert view["current_season"] is None
        assert view["local_historical_is_active"] is True
        assert view["seasons"]["2026_27"]["fixtures_count"] == 144
        assert view["seasons"]["2026_27"]["results_count"] == 0


class TestItem3_ExactlyThirtySixTeams:
    def test_thirty_six_teams_in_four_pots(self, built_draw_season):
        snapshot = load_snapshot(built_draw_season)
        doc = read_season_fixtures(built_draw_season, DRAWN_SEASON)

        assert len(snapshot["teams"]) == 36
        pots: dict[int, int] = {}
        for t in snapshot["teams"]:
            pots[int(t["pot"])] = pots.get(int(t["pot"]), 0) + 1
        assert pots == {1: 9, 2: 9, 3: 9, 4: 9}

        schedule_teams = doc["schedule"]["teams"]
        assert len(schedule_teams) == 36
        assert sorted(t["name"] for t in schedule_teams) == \
            sorted(t["name"] for t in snapshot["teams"])

    def test_validation_contract_passes(self, built_draw_season):
        doc = read_season_fixtures(built_draw_season, DRAWN_SEASON)
        validate_ucl_fixtures(doc)


class TestItem4_PairingsMatchAuthoritativeSource:
    def test_all_144_pairings_match_snapshot_direction(self, built_draw_season):
        snapshot = load_snapshot(built_draw_season)
        doc = read_season_fixtures(built_draw_season, DRAWN_SEASON)

        expected = _expected_snapshot_pairings(snapshot)
        assert len(expected) == 144

        schedule_pairs = {
            (m["team_a"], m["team_b"])
            for md in doc["schedule"]["matchdays"]
            for m in md
        }
        flat_pairs = {
            (f["team_a"], f["team_b"])
            for f in doc["fixtures"]
        }
        assert schedule_pairs == expected
        assert flat_pairs == expected
        assert len(schedule_pairs) == 144


class TestItem5_AllNewMatchesUnplayed:
    def test_every_row_scheduled_with_null_unknowns(self, built_draw_season):
        doc = read_season_fixtures(built_draw_season, DRAWN_SEASON)
        schema_season = doc.get("season")
        for f in doc["fixtures"]:
            assert f["status"] == "scheduled"
            assert f["event_date"] is None
            assert f["official_matchday"] is None
            assert 1 <= f["simulation_matchday"] <= 8
            assert f["provenance"] == {
                "fixture": "authoritative", "schedule": "derived"}
        schedule = doc["schedule"]
        assert schedule["authoritative"] is False
        assert schedule["official_matchdays_known"] is False
        assert all(m["event_date"] is None
                   for md in schedule["matchdays"] for m in md)

    def test_no_results_recorded(self, built_draw_season):
        res = read_season_results(built_draw_season, DRAWN_SEASON)
        assert res["matches"] == []
        assert res["schema"] == 1


class TestItem7_SeasonSelection:
    def test_activate_and_deactivate_flip_pointer(self, draw_data_dir):
        out = activate_draw_season(draw_data_dir, return_build=True)
        assert out["active"] is True
        current = get_current_season(draw_data_dir)
        assert current["season"] == DRAWN_SEASON
        assert current["basis"] == "draw"

        view = resolve_active_view(draw_data_dir)
        assert view["current_season"] == DRAWN_SEASON
        assert view["local_historical_is_active"] is False

        out = deactivate_draw_season(draw_data_dir)
        assert out["active"] is False
        current = get_current_season(draw_data_dir)
        assert current["season"] == LOCAL_HISTORICAL_SEASON

    def test_activate_routeing_for_sim_and_factual(self, draw_data_dir):
        from competitions.ucl.src.orchestrator import (
            resolve_active_data_dir,
            resolve_compute_mode,
        )
        # No pointer yet -> root (2025/26).
        assert str(Path(resolve_active_data_dir(draw_data_dir)).resolve()) == \
            str(draw_data_dir.resolve())

        activate_draw_season(draw_data_dir)
        active_dir = Path(resolve_active_data_dir(draw_data_dir))
        assert active_dir == season_dir(draw_data_dir, DRAWN_SEASON)
        assert (active_dir / "fixtures.json").exists()

        # Factual mode stays "results" (fixtures loaded, awaiting results):
        # a fresh 2026/27 season is NOT simulated until real results land.
        mode, reason = resolve_compute_mode(draw_data_dir)
        assert mode == "results"
        assert "2026/27" in reason


class TestItem8_SeasonScopedApiState:
    def test_competition_state_is_season_scoped(self, draw_data_dir):
        from competitions.ucl.src.state import build_competition_state
        activate_draw_season(draw_data_dir)

        state = build_competition_state(
            str(draw_data_dir), mode="results", active_season=DRAWN_SEASON)
        assert state["season"] == DRAWN_SEASON
        # League stage reads the 2026/27 store: zero played entries.
        league = state["stages"]["league"]
        assert not league.get("played")
        assert state["availability"]["league_results"] == "available"
        # Phase reports the season as not started (no results recorded).
        assert state["phase"]["progress"]["played"] == 0

    def test_local_season_state_unchanged_by_default(self, draw_data_dir):
        from competitions.ucl.src.state import build_competition_state
        state = build_competition_state(str(draw_data_dir), mode="results")
        assert state["season"] == LOCAL_HISTORICAL_SEASON


class TestItem6_SimulationNeverWritesFactualStores:
    def test_sim_over_drawn_season_is_pure(self, built_draw_season):
        from competitions.ucl.src.simulation import simulate_league_phase

        doc = read_season_fixtures(built_draw_season, DRAWN_SEASON)
        before = _root_store_bytes(built_draw_season)
        before_season = (season_dir(built_draw_season, DRAWN_SEASON)
                         / "results.json").read_bytes()

        elo = {
            t["name"]: 1400.0 + (float(t["coefficient"]) / 147.5) * 400.0
            for t in doc["schedule"]["teams"]
        }
        standings = simulate_league_phase(
            {"schedule": doc["schedule"]}, elo, random.Random(42))
        assert len(standings) == 36

        after = _root_store_bytes(built_draw_season)
        after_season = (season_dir(built_draw_season, DRAWN_SEASON)
                        / "results.json").read_bytes()
        assert before == after
        assert before_season == after_season


class TestItem10_RepeatableAcquisition:
    def test_rebuild_is_byte_identical(self, draw_data_dir):
        ensure_draw_season(draw_data_dir)
        fx1 = (season_dir(draw_data_dir, DRAWN_SEASON) / "fixtures.json").read_bytes()
        res1 = (season_dir(draw_data_dir, DRAWN_SEASON) / "results.json").read_bytes()

        ensure_draw_season(draw_data_dir)
        fx2 = (season_dir(draw_data_dir, DRAWN_SEASON) / "fixtures.json").read_bytes()
        res2 = (season_dir(draw_data_dir, DRAWN_SEASON) / "results.json").read_bytes()

        assert fx1 == fx2
        assert res1 == res2

    def test_matches_per_matchday_consistent(self, draw_data_dir):
        summary = ensure_draw_season(draw_data_dir)
        assert summary["fixtures"] == 144
        assert summary["matchdays"] == 8
        assert summary["matches_per_matchday"] == 18
        assert summary["authoritative_schedule"] is False
        assert summary["grouping_method"] == "deterministic_v1"


class TestCli:
    def test_documented_invocation_forms(self, draw_data_dir, capsys):
        rc = main(["build", "--data-dir", str(draw_data_dir)])
        assert rc == 0
        rc = main(["validate", "--data-dir", str(draw_data_dir)])
        assert rc == 0
        rc = main(["deactivate", "--data-dir", str(draw_data_dir)])
        assert rc == 0
        out = capsys.readouterr().out
        assert '"ok": true' in out or '"season": "2026/27"' in out