"""Tests for engine functions extracted from main.py."""

import pytest
from pathlib import Path

MAIN_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = MAIN_DIR / "data"





class TestHistoricalCatchUp:
    """Tests for _run_historical_catch_up in main.py."""

    @pytest.fixture
    def full_data(self):
        """Load production data for integration tests."""
        import json
        with open(f"{DATA_DIR}/teams.json", encoding="utf-8") as f:
            teams = json.load(f)
        with open(f"{DATA_DIR}/groups.json", encoding="utf-8") as f:
            groups = json.load(f)
        with open(f"{DATA_DIR}/bracket.json", encoding="utf-8") as f:
            bracket = json.load(f)
        with open(f"{DATA_DIR}/annex_c.json", encoding="utf-8") as f:
            annex_c = json.load(f)
        return teams, groups, bracket, annex_c

    def test_empty_raw_is_noop(self, monkeypatch):
        """When fetch_raw_matches returns [], catch-up returns inputs unchanged."""
        from src.engine import historical_catch_up

        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: [])

        played_groups_in = {"GS_A_01": {"match_id": "GS_A_01", "winner": "Mexico"}}
        played_in = {"M73": {"match_id": "M73", "winner": "Argentina"}}
        rg, rp, _ea, _ni = historical_catch_up(
            "dummy_key", {}, {"groups": {}}, [], {}, {},
            played_groups_in, played_in,
        )
        assert rg == played_groups_in
        assert rp == played_in
        assert id(rg) == id(played_groups_in)

    def test_knockout_event_matched_to_r32_slot(self, monkeypatch, full_data):
        """A single finished knockout BSD event is matched to the correct R32 slot and persisted."""
        from src.engine import historical_catch_up
        import src.state
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data

        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 3,
            "away_score": 1,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]

        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        played = {}
        team_copies = {n: dict(d) for n, d in teams.items()}
        rg, rp, _ea, _ni = historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, played,
        )
        assert first_mid in rp
        assert rp[first_mid]["team_a"] == slot["team_a"]
        assert rp[first_mid]["team_b"] == slot["team_b"]
        assert rp[first_mid]["winner"] == slot["team_a"]
        assert rp[first_mid]["home_score"] == 3
        assert rp[first_mid]["away_score"] == 1
        elo_a = team_copies[slot["team_a"]]["elo"]
        elo_b = team_copies[slot["team_b"]]["elo"]
        assert elo_a > teams[slot["team_a"]]["elo"]  # winner gained Elo
        assert elo_b < teams[slot["team_b"]]["elo"]  # loser lost Elo

    def test_draw_included(self, monkeypatch, full_data):
        """Draw events produce entry with winner=None, is_draw=True, and Elo is adjusted."""
        from src.engine import historical_catch_up
        import src.state
        from src.knockout import resolve_knockout_slot_teams
        from src.elo import expected_score

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 1,
            "away_score": 1,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        rg, rp, _ea, _ni = historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, {},
        )
        assert first_mid in rp
        assert rp[first_mid]["winner"] is None
        assert rp[first_mid]["is_draw"] is True
        assert rp[first_mid]["home_score"] == 1
        assert rp[first_mid]["away_score"] == 1
        # Elo should be adjusted for draw
        e_a = expected_score(teams[slot["team_a"]]["elo"], teams[slot["team_b"]]["elo"])
        if e_a > 0.5:
            assert team_copies[slot["team_a"]]["elo"] < teams[slot["team_a"]]["elo"]
        else:
            assert team_copies[slot["team_b"]]["elo"] < teams[slot["team_b"]]["elo"]

    def test_knockout_pk_catch_up(self, monkeypatch, full_data):
        """PK shootout (equal scores + BSD winner) produces PK entry with winner set, is_draw=False."""
        from src.engine import historical_catch_up
        import src.state
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99998,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 1,
            "away_score": 1,
            "winner": slot["team_a"],
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        rg, rp, _ea, _ni = historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, {},
        )
        assert first_mid in rp
        assert rp[first_mid]["winner"] == slot["team_a"]
        assert rp[first_mid]["is_draw"] is False

    def test_restart_dedup(self, monkeypatch, full_data):
        """Event already in played is not re-processed on restart."""
        from src.engine import historical_catch_up
        import src.state
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]
        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        played_before = {first_mid: {"match_id": first_mid, "winner": slot["team_a"]}}
        rg, rp, _ea, _ni = historical_catch_up(
            "dummy_key", teams, groups, bracket, annex_c, aliases,
            {}, played_before,
        )
        assert rp[first_mid]["winner"] == slot["team_a"]
        assert len(rp) == 1

    def test_unmatchable_team_skipped(self, monkeypatch, full_data):
        """Event with unmatchable team names is skipped gracefully."""
        from src.engine import historical_catch_up
        import src.state

        teams, groups, bracket, annex_c = full_data

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": "Unknown FC",
            "away_team": "Nowhere United",
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        rg, rp, _ea, _ni = historical_catch_up(
            "dummy_key", teams, groups, bracket, annex_c, {},
            {}, {},
        )
        assert rp == {}

    def test_catch_up_applies_elo_to_knockout(self, monkeypatch, full_data):
        """Catch-up applies Elo to ingested knockout matches in chronological order."""
        from src.engine import historical_catch_up
        import src.state
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        before_a = team_copies[slot["team_a"]]["elo"]
        before_b = team_copies[slot["team_b"]]["elo"]
        _rg, _rp, _ea, _ni = historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c,
            {slot["team_a"]: [], slot["team_b"]: []},
            {}, {},
        )
        assert team_copies[slot["team_a"]]["elo"] > before_a
        assert team_copies[slot["team_b"]]["elo"] < before_b

    def test_catch_up_elo_deterministic(self, monkeypatch, full_data):
        """Same ingested matches produce same Elo across runs."""
        from src.engine import historical_catch_up
        import src.state
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 3,
            "away_score": 1,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        def run_catchup():
            tc = {n: dict(d) for n, d in teams.items()}
            _rg, _rp, _ea, _ni = historical_catch_up(
                "dummy_key", tc, groups, bracket, annex_c, aliases,
                {}, {},
            )
            return tc

        elo1 = run_catchup()
        elo2 = run_catchup()
        for name in teams:
            assert elo1[name]["elo"] == elo2[name]["elo"]

    def test_elo_applied_prevents_reapplication(self, monkeypatch, full_data):
        """Passing elo_applied with match_id skips that match's Elo update."""
        from src.engine import historical_catch_up
        import src.state
        from src.knockout import resolve_knockout_slot_teams

        teams, groups, bracket, annex_c = full_data
        slot_teams = resolve_knockout_slot_teams(
            groups, teams, {}, bracket, annex_c, {},
        )
        first_mid = sorted(slot_teams.keys())[0]
        slot = slot_teams[first_mid]

        aliases = {slot["team_a"]: [], slot["team_b"]: []}

        mock_event = [{
            "id": 99999,
            "status": "finished",
            "home_team": slot["team_a"],
            "away_team": slot["team_b"],
            "home_score": 2,
            "away_score": 0,
            "event_date": "2026-06-15T22:00:00Z",
            "league": {"id": 27},
            "group_name": None,
        }]
        monkeypatch.setattr("src.engine.fetch_raw_matches", lambda *a, **kw: mock_event)
        monkeypatch.setattr(src.state, "save_played", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_played_groups", lambda *a, **kw: None)
        monkeypatch.setattr(src.state, "save_teams", lambda *a, **kw: None)

        team_copies = {n: dict(d) for n, d in teams.items()}
        before_a = team_copies[slot["team_a"]]["elo"]
        _rg, _rp, _ea, _ni = historical_catch_up(
            "dummy_key", team_copies, groups, bracket, annex_c, aliases,
            {}, {}, elo_applied={first_mid},
        )
        assert team_copies[slot["team_a"]]["elo"] == before_a


class TestDrawBackfillIntegration:
    """Integration tests for draw backfill + baseline flow."""

    @pytest.fixture
    def sample_teams(self):
        return {"A": {"elo": 2000}, "B": {"elo": 1900}, "C": {"elo": 1800}}

    def test_backfill_populates_elo_applied(self, monkeypatch, sample_teams):
        """2 draw matches both backfilled, Elo changed."""
        from src.engine import draw_backfill

        monkeypatch.setattr("src.state.save_elo_applied", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.save_teams", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.save_elo_update_log", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.load_elo_update_log", lambda *a, **kw: [])

        teams = dict(sample_teams)
        played = {
            "M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                    "winner": None, "home_score": 1, "away_score": 1,
                    "completed_at": "2026-06-11T20:00:00Z"},
            "M02": {"match_id": "M02", "team_a": "A", "team_b": "C",
                    "winner": None, "home_score": 2, "away_score": 2,
                    "completed_at": "2026-06-12T20:00:00Z"},
        }
        elo_applied = set()
        result, _ni = draw_backfill(teams, played, {}, elo_applied)
        assert "M01" in result
        assert "M02" in result
        # Elo changed for both teams
        assert teams["A"]["elo"] != 2000
        assert teams["B"]["elo"] != 1900

    def test_backfill_includes_group_matches(self, monkeypatch, sample_teams):
        """Group draw match in played_groups is backfilled."""
        from src.engine import draw_backfill

        monkeypatch.setattr("src.state.save_elo_applied", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.save_teams", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.save_elo_update_log", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.load_elo_update_log", lambda *a, **kw: [])

        teams = dict(sample_teams)
        played_groups = {
            "GS_A_01": {"match_id": "GS_A_01", "team_a": "A", "team_b": "B",
                        "winner": None, "home_score": 1, "away_score": 1,
                        "completed_at": "2026-06-10T20:00:00Z"},
        }
        elo_applied = set()
        result, _ni = draw_backfill(teams, {}, played_groups, elo_applied)
        assert "GS_A_01" in result
        assert teams["A"]["elo"] != 2000

    def test_backfill_skips_non_draw_matches(self, monkeypatch, sample_teams):
        """Only draws are backfilled, non-draws are skipped."""
        from src.engine import draw_backfill

        monkeypatch.setattr("src.state.save_elo_applied", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.save_teams", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.save_elo_update_log", lambda *a, **kw: None)
        monkeypatch.setattr("src.state.load_elo_update_log", lambda *a, **kw: [])

        teams = dict(sample_teams)
        played = {
            "M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                    "winner": "A", "home_score": 3, "away_score": 1,
                    "completed_at": "2026-06-11T20:00:00Z"},
        }
        elo_applied = set()
        result, _ni = draw_backfill(teams, played, {}, elo_applied)
        assert "M01" not in result
        assert teams["A"]["elo"] == 2000  # unchanged

    





class TestGatherSignalData:
    """Tests for _gather_signal_data (display blend logic)."""

    def _make_cache(self, mid: str, prob: float | None) -> dict:
        return {"matches": {mid: {"probability": prob}}}

    def _make_blend_params(self, match_probs: dict[str, float]) -> dict:
        return {
            "calibration_params": {},
            "blend_weights": {},
            "match_probs": match_probs,
        }

    @pytest.fixture
    def teams(self):
        return {"Arg": {"elo": 2000}, "Bra": {"elo": 1900}}

    @pytest.fixture
    def groups(self):
        return {
            "groups": {
                "A": {"teams": ["Arg", "Bra"], "matches": [
                    {"match_id": "GS_A_01", "team_a": "Arg", "team_b": "Bra"},
                ]},
            }
        }

    @pytest.fixture
    def bracket(self):
        return []

    @pytest.fixture
    def played(self):
        return {}

    @pytest.fixture
    def played_groups(self):
        return {}

    def test_uses_blend_params_when_available(self, teams, groups, bracket, played, played_groups):
        """blend_params.match_probs is used instead of raw Elo."""
        from src.engine import gather_signal_data

        blend_params = self._make_blend_params({"GS_A_01": 0.723})
        result = gather_signal_data(
            teams=teams, groups=groups, bracket=bracket,
            odds_cache=None, cb_cache=None,
            form_cache=None, lineup_cache=None,
            xg_overrides=None, played=played, played_groups=played_groups,
            blend_params=blend_params,
        )
        assert len(result) == 1
        assert result[0]["blended"] == 0.723

    def test_falls_back_to_elo_without_blend_params(self, teams, groups, bracket, played, played_groups):
        """Without blend_params, falls back to Elo expected_score."""
        from src.engine import gather_signal_data
        from src.elo import expected_score

        result = gather_signal_data(
            teams=teams, groups=groups, bracket=bracket,
            odds_cache=None, cb_cache=None,
            form_cache=None, lineup_cache=None,
            xg_overrides=None, played=played, played_groups=played_groups,
        )
        assert len(result) == 1
        elo_p = expected_score(2000, 1900)
        assert result[0]["blended"] == round(elo_p, 4)

    def test_blend_params_per_match_fallback(self, teams, groups, bracket, played, played_groups):
        """Match absent from match_probs falls back to Elo."""
        from src.engine import gather_signal_data
        from src.elo import expected_score

        blend_params = self._make_blend_params({"OTHER_MATCH": 0.8})
        result = gather_signal_data(
            teams=teams, groups=groups, bracket=bracket,
            odds_cache=None, cb_cache=None,
            form_cache=None, lineup_cache=None,
            xg_overrides=None, played=played, played_groups=played_groups,
            blend_params=blend_params,
        )
        assert len(result) == 1
        elo_p = expected_score(2000, 1900)
        assert result[0]["blended"] == round(elo_p, 4)

    def test_no_match_probs_fallback_to_elo(self, teams, groups, bracket, played, played_groups):
        """blend_params without match_probs key falls back to Elo."""
        from src.engine import gather_signal_data
        from src.elo import expected_score

        blend_params = {"calibration_params": {}, "blend_weights": {}}
        result = gather_signal_data(
            teams=teams, groups=groups, bracket=bracket,
            odds_cache=None, cb_cache=None,
            form_cache=None, lineup_cache=None,
            xg_overrides=None, played=played, played_groups=played_groups,
            blend_params=blend_params,
        )
        assert len(result) == 1
        elo_p = expected_score(2000, 1900)
        assert result[0]["blended"] == round(elo_p, 4)

    def test_signals_dict_structure(self, teams, groups, bracket, played, played_groups):
        """Verify all signals are present in the output dict."""
        from src.engine import gather_signal_data
        from src.elo import expected_score

        odds_cache = self._make_cache("GS_A_01", 0.7)
        cb_cache = self._make_cache("GS_A_01", 0.5)
        form_cache = self._make_cache("GS_A_01", 0.55)
        lineup_cache = self._make_cache("GS_A_01", 0.52)

        result = gather_signal_data(
            teams=teams, groups=groups, bracket=bracket,
            odds_cache=odds_cache, cb_cache=cb_cache,
            form_cache=form_cache, lineup_cache=lineup_cache,
            xg_overrides=None, played=played, played_groups=played_groups,
        )
        assert len(result) == 1
        signals = result[0]["signals"]
        elo_p = expected_score(2000, 1900)
        assert signals["elo"] == elo_p
        assert signals["odds"] == 0.7
        assert signals["catboost"] == 0.5
        assert signals["form"] == 0.55
        assert signals["lineup"] == 0.52

    def test_missing_team_fallback_to_05(self, groups, bracket, played, played_groups):
        """If team missing from teams, elo falls back to 0.5."""
        from src.engine import gather_signal_data

        teams = {"Arg": {"elo": 2000}}  # Bra missing
        result = gather_signal_data(
            teams=teams, groups=groups, bracket=bracket,
            odds_cache=None, cb_cache=None,
            form_cache=None, lineup_cache=None,
            xg_overrides=None, played=played, played_groups=played_groups,
        )
        assert len(result) == 1
        entry = result[0]
        assert entry["blended"] == 0.5
