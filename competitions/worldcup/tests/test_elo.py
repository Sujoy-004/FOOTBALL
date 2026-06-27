"""Tests for the Elo rating engine.

Covers expected_score and update_ratings with 9 test cases:
equal ratings, table values, 400-gap, standard update, underdog win,
custom K, large gap, invalid winner, and no-mutation contract.
"""

import pytest

from src.elo import apply_elo_update, compute_k_factor, expected_score, update_ratings


# ─── expected_score tests ────────────────────────────────────────────────


class TestExpectedScore:
    """Tests for the expected_score function."""

    def test_equal_ratings(self):
        """Equal ratings should return 0.5 exactly."""
        assert expected_score(1500, 1500) == 0.5

    def test_table_values(self):
        """Should match eloratings.net expected score table (3 decimal places)."""
        assert round(expected_score(1600, 1500), 3) == 0.640
        assert round(expected_score(1500, 1600), 3) == 0.360

    def test_400_point_gap(self):
        """400-point gap should give expected score of ~0.909."""
        assert round(expected_score(1900, 1500), 3) == 0.909


# ─── update_ratings tests ────────────────────────────────────────────────


class TestUpdateRatings:
    """Tests for the update_ratings function."""

    def test_standard_update(self):
        """Argentina(2100) beats Nigeria(1800) → Arg ~2109, Nig ~1791."""
        elos = {"Argentina": 2100, "Nigeria": 1800, "France": 2050}
        result = update_ratings("Argentina", "Nigeria", "Argentina", elos, K=60)
        assert round(result["Argentina"], 0) == 2109
        assert round(result["Nigeria"], 0) == 1791
        # Unchanged team should not appear in result
        assert "France" not in result

    def test_underdog_wins(self):
        """Nigeria(1800) beats Argentina(2100) → larger swing for underdog."""
        elos = {"Argentina": 2100, "Nigeria": 1800}
        result = update_ratings("Argentina", "Nigeria", "Nigeria", elos, K=60)
        assert round(result["Nigeria"], 0) == 1851
        assert round(result["Argentina"], 0) == 2049

    def test_custom_k_factor(self):
        """K=40 produces changes that are 2/3 of K=60 changes."""
        elos = {"Argentina": 2100, "Nigeria": 1800}
        result = update_ratings("Argentina", "Nigeria", "Argentina", elos, K=40)
        assert round(result["Argentina"], 0) == 2106

    def test_large_elo_gap(self):
        """800+ point gap should not crash and return reasonable values."""
        elos = {"Strong": 2300, "Weak": 1500}
        result = update_ratings("Strong", "Weak", "Strong", elos, K=60)
        assert 0 < result["Strong"] < 3000
        assert 0 < result["Weak"] < 3000

    def test_invalid_winner_raises_error(self):
        """Winner that is neither team_a nor team_b should raise ValueError."""
        elos = {"A": 2000, "B": 1900}
        with pytest.raises(ValueError, match="must be"):
            update_ratings("A", "B", "C", elos)

    def test_does_not_mutate_input(self):
        """update_ratings should NOT modify the input elos dict (immutability)."""
        elos = {"A": 2000, "B": 1900}
        before_a = elos["A"]
        update_ratings("A", "B", "A", elos, K=60)
        assert elos["A"] == before_a  # unchanged

    def test_draw_equal_ratings(self):
        """Draw with equal ratings → both change by same amount toward 0.5."""
        elos = {"A": 2000, "B": 2000}
        result = update_ratings("A", "B", None, elos, K=60)
        assert result["A"] == result["B"]  # symmetric
        assert result["A"] == 2000.0       # 2000 + 60*(0.5-0.5) = 2000

    def test_draw_favored_team_loses_elo(self):
        """Draw when A is heavily favored → A loses Elo, B gains."""
        elos = {"A": 2200, "B": 1800}
        result = update_ratings("A", "B", None, elos, K=60)
        e_a = expected_score(2200, 1800)
        assert result["A"] < 2200  # A underperformed
        assert result["B"] > 1800  # B overperformed
        expected_a = 2200 + 60 * (0.5 - e_a)
        expected_b = 1800 + 60 * (0.5 - (1 - e_a))
        assert round(result["A"], 1) == round(expected_a, 1)
        assert round(result["B"], 1) == round(expected_b, 1)

    def test_pk_split(self):
        """PK win: pk_winner receives 0.75 result, loser 0.25."""
        elos = {"A": 2000, "B": 2000}
        result = update_ratings("A", "B", "A", elos, K=60, pk_winner="A")
        assert result["A"] == 2015.0  # 2000 + 60*(0.75-0.5)
        assert result["B"] == 1985.0  # 2000 + 60*(0.25-0.5)

    def test_pk_winner_invalid(self):
        """Invalid pk_winner should raise ValueError with descriptive message."""
        elos = {"A": 2000, "B": 1900}
        with pytest.raises(ValueError, match="pk_winner"):
            update_ratings("A", "B", None, elos, K=60, pk_winner="C")

    def test_apply_elo_update_mutates_teams(self):
        """apply_elo_update mutates teams dict in-place and returns changes."""
        teams = {"Arg": {"elo": 2100}, "Nig": {"elo": 1800}}
        match = {"team_a": "Arg", "team_b": "Nig", "winner": "Arg"}
        updates = apply_elo_update(match, teams)
        assert teams["Arg"]["elo"] > 2100
        assert teams["Nig"]["elo"] < 1800
        assert updates["Arg"]["old"] == 2100
        assert updates["Arg"]["new"] == teams["Arg"]["elo"]

    def test_apply_elo_update_draw(self):
        """apply_elo_update works with winner=None (draw)."""
        teams = {"Arg": {"elo": 2100}, "Nig": {"elo": 1800}}
        match = {"team_a": "Arg", "team_b": "Nig", "winner": None, "home_score": 1, "away_score": 1}
        e_a = expected_score(2100, 1800)
        apply_elo_update(match, teams)
        expected = 2100 + 60 * (0.5 - e_a)
        assert round(teams["Arg"]["elo"], 1) == round(expected, 1)

    def test_apply_elo_update_k_multiplier(self):
        """GD=2 should use K=90 (1.5 * 60) instead of default K=60."""
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        match = {"team_a": "A", "team_b": "B", "winner": "A",
                 "home_score": 3, "away_score": 1}
        e_a = expected_score(2000, 1900)
        expected_new_a = 2000 + 90 * (1.0 - e_a)  # K=90, not K=60
        apply_elo_update(match, teams)
        assert round(teams["A"]["elo"], 1) == round(expected_new_a, 1)

    def test_apply_elo_update_pk(self):
        """PK mode: winner set, GD=0, is_draw=False → 0.75/0.25 split with K=60."""
        teams = {"A": {"elo": 2000}, "B": {"elo": 2000}}
        match = {"team_a": "A", "team_b": "B", "winner": "A",
                 "is_draw": False, "home_score": 1, "away_score": 1}
        apply_elo_update(match, teams)
        assert round(teams["A"]["elo"], 1) == 2015.0  # 2000 + 60*(0.75-0.5)
        assert round(teams["B"]["elo"], 1) == 1985.0  # 2000 + 60*(0.25-0.5)

    def test_apply_elo_update_draw_gd0(self):
        """True draw (winner=None) with GD=0 → K=60, unchanged from previous behavior."""
        teams = {"A": {"elo": 2100}, "B": {"elo": 1800}}
        match = {"team_a": "A", "team_b": "B", "winner": None,
                 "home_score": 1, "away_score": 1}
        e_a = expected_score(2100, 1800)
        apply_elo_update(match, teams)
        expected_a = 2100 + 60 * (0.5 - e_a)
        assert round(teams["A"]["elo"], 1) == round(expected_a, 1)


# ─── compute_k_factor tests ────────────────────────────────────────────────


class TestComputeKFactor:
    """Tests for the compute_k_factor function."""

    def test_gd_0(self):
        """GD=0 (draw) → G=1.0, returns base_K unchanged."""
        assert compute_k_factor(0, 60) == 60.0

    def test_gd_1(self):
        """GD=1 (one-goal win) → G=1.0, returns base_K unchanged."""
        assert compute_k_factor(1, 60) == 60.0

    def test_gd_2(self):
        """GD=2 → G=1.5, returns 1.5 * base_K."""
        assert compute_k_factor(2, 60) == 90.0

    def test_gd_3(self):
        """GD=3 → G=(11+3)/8 = 1.75, returns 1.75 * 60 = 105.0."""
        assert compute_k_factor(3, 60) == 105.0

    def test_gd_7(self):
        """GD=7 → G=(11+7)/8 = 2.25, returns 2.25 * 60 = 135.0."""
        assert compute_k_factor(7, 60) == 135.0

    def test_custom_base_k(self):
        """Custom base_K=40, GD=2 → G=1.5, returns 1.5 * 40 = 60.0."""
        assert compute_k_factor(2, 40) == 60.0


class TestDrawBackfill:
    """Tests for historical draw backfill logic in main._run_draw_backfill.

    All tests monkeypatch state.save_teams/save_elo_applied/save_elo_update_log
    to prevent modification of production data files in data/.
    """

    @pytest.fixture(autouse=True)
    def _mock_saves(self, monkeypatch):
        """Prevent all _run_draw_backfill tests from writing to production data/."""
        monkeypatch.setattr("main.state.save_teams", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_elo_applied", lambda *a, **kw: None)
        monkeypatch.setattr("main.state.save_elo_update_log", lambda *a, **kw: None)

    def test_backfill_detects_draw_candidates(self):
        """Scans played for h==a matches not in elo_applied."""
        from main import _run_draw_backfill
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                          "winner": None, "home_score": 1, "away_score": 1,
                          "completed_at": "2026-06-15T20:00:00Z"}}
        elo_applied = set()
        result = _run_draw_backfill(teams, played, {}, elo_applied)
        assert "M01" in result

    def test_backfill_skips_already_applied(self):
        """Match already in elo_applied is not re-processed."""
        from main import _run_draw_backfill
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                          "winner": None, "home_score": 1, "away_score": 1,
                          "completed_at": "2026-06-15T20:00:00Z"}}
        elo_applied = {"M01"}
        before = teams["A"]["elo"]
        _run_draw_backfill(teams, played, {}, elo_applied)
        assert teams["A"]["elo"] == before

    def test_backfill_skips_non_draws(self):
        """Non-draw matches (h != a) are skipped."""
        from main import _run_draw_backfill
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                          "winner": "A", "home_score": 3, "away_score": 1,
                          "completed_at": "2026-06-15T20:00:00Z"}}
        elo_applied = set()
        result = _run_draw_backfill(teams, played, {}, elo_applied)
        assert "M01" not in result

    def test_backfill_draws_from_played_groups(self):
        """Draws in played_groups are also backfilled."""
        from main import _run_draw_backfill
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played_groups = {"GS_A_01": {"match_id": "GS_A_01", "team_a": "A",
                          "team_b": "B", "winner": None, "home_score": 2,
                          "away_score": 2, "completed_at": "2026-06-14T20:00:00Z"}}
        elo_applied = set()
        result = _run_draw_backfill(teams, {}, played_groups, elo_applied)
        assert "GS_A_01" in result
        assert teams["A"]["elo"] != 2000

    def test_backfill_applies_elo_change(self):
        """Backfilled draw changes Elo for both teams."""
        from main import _run_draw_backfill
        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                          "winner": None, "home_score": 1, "away_score": 1,
                          "completed_at": "2026-06-15T20:00:00Z"}}
        elo_applied = set()
        _run_draw_backfill(teams, played, {}, elo_applied)
        # Draw when A is favored: A should lose Elo, B should gain
        assert teams["A"]["elo"] < 2000
        assert teams["B"]["elo"] > 1900

    def test_backfill_logs_elo_change(self, monkeypatch):
        """Backfilled draw logs change to elo_update_log.json."""
        import json
        from pathlib import Path
        from main import _run_draw_backfill
        from src import constants, state

        # Save original log
        log_path = constants.DATA_DIR / "elo_update_log.json"
        original_log = []
        if log_path.exists():
            with open(log_path, encoding="utf-8") as f:
                original_log = json.load(f)

        teams = {"A": {"elo": 2000}, "B": {"elo": 1900}}
        played = {"M01": {"match_id": "M01", "team_a": "A", "team_b": "B",
                          "winner": None, "home_score": 1, "away_score": 1,
                          "completed_at": "2026-06-15T20:00:00Z"}}
        elo_applied = set()

        # Mock save functions to prevent modifying production data
        saved_log = None
        def mock_save_log(log, data_dir=None):
            nonlocal saved_log
            saved_log = list(log)

        monkeypatch.setattr(state, "save_elo_update_log", mock_save_log)
        monkeypatch.setattr(state, "save_teams", lambda *a, **kw: None)
        monkeypatch.setattr(state, "save_elo_applied", lambda *a, **kw: None)

        _run_draw_backfill(teams, played, {}, elo_applied)

        assert saved_log is not None
        assert len(saved_log) >= 2  # 2 teams updated
        # Check log entry structure
        entry = saved_log[-1]
        assert entry["reason"] == "historical draw backfill"
        assert "team" in entry
        assert "old_value" in entry
        assert "new_value" in entry
        assert "drift_magnitude" in entry

        # Restore original log
        if original_log:
            state.save_elo_update_log(original_log)
