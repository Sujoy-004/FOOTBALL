"""Tests for form.py — Elo residual computation and form signal pipeline.

All tests use inline fixtures (no real data files). Ledger operations
are monkeypatched to avoid real disk writes.
"""

from datetime import datetime, timezone

import pytest

from src.predictors.form import (
    _build_team_residuals,
    _compute_match_form_signal,
    _compute_residual,
    _sigmoid,
    compute_form_signal,
)


# ─── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def sample_teams():
    """Minimal teams dict with Elo ratings for 4 teams."""
    return {
        "Brazil": {"elo": 2100},
        "Argentina": {"elo": 2115},
        "Germany": {"elo": 2050},
        "France": {"elo": 2063},
    }


@pytest.fixture
def sample_groups():
    """Groups dict with one group of 2 teams and 1 match."""
    return {
        "groups": {
            "A": {
                "teams": ["Brazil", "Argentina"],
                "matches": [
                    {
                        "match_id": "GS_A_01",
                        "team_a": "Brazil",
                        "team_b": "Argentina",
                        "winner": None,
                        "score_a": None,
                        "score_b": None,
                    },
                ],
            }
        }
    }


@pytest.fixture
def sample_played_groups():
    """Played group matches with results for residual computation."""
    return {
        "GS_A_01": {
            "match_id": "GS_A_01",
            "team_a": "Brazil",
            "team_b": "Argentina",
            "winner": "Brazil",
            "score_a": 2,
            "score_b": 1,
            "completed_at": "2026-06-15T20:00:00Z",
        },
        "GS_A_02": {
            "match_id": "GS_A_02",
            "team_a": "Germany",
            "team_b": "France",
            "winner": "France",
            "score_a": 0,
            "score_b": 3,
            "completed_at": "2026-06-15T18:00:00Z",
        },
    }


@pytest.fixture
def sample_played():
    """Empty played (bracket) dict — no bracket matches completed yet."""
    return {}


# ─── Sigmoid Tests ───────────────────────────────────────────────────


class TestSigmoid:
    """_sigmoid: basic sigmoid function behavior."""

    def test_sigmoid_zero(self):
        """sigmoid(0) == 0.5."""
        assert _sigmoid(0) == 0.5

    def test_sigmoid_positive(self):
        """sigmoid(1) > 0.5."""
        assert _sigmoid(1) > 0.5

    def test_sigmoid_negative(self):
        """sigmoid(-1) < 0.5."""
        assert _sigmoid(-1) < 0.5

    def test_sigmoid_symmetric(self):
        """sigmoid(-x) == 1 - sigmoid(x)."""
        assert abs(_sigmoid(-2) - (1 - _sigmoid(2))) < 1e-10

    def test_sigmoid_overflow_positive(self):
        """Large positive input returns 1.0 (overflow to 0 handled)."""
        assert _sigmoid(1000) == 1.0

    def test_sigmoid_overflow_negative(self):
        """Large negative input returns 0.0 (overflow to 0 handled)."""
        assert _sigmoid(-1000) == 0.0


# ─── Residual Tests ──────────────────────────────────────────────────


class TestFormResiduals:
    """_compute_residual: Elo residual for a single match."""

    def test_basic_residual(self, sample_teams):
        """Brazil beats Argentina → positive residual for Brazil, negative for Argentina."""
        match = {
            "team_a": "Brazil",
            "team_b": "Argentina",
            "winner": "Brazil",
            "score_a": 2,
            "score_b": 1,
        }
        res_a, res_b, err = _compute_residual(match, sample_teams)
        assert err is None
        # Brazil (elo 2100) beating Argentina (elo 2115) is a slight upset
        # actual_a = 1.0, expected_a = expected_score(2100, 2115, 0) ≈ 0.478
        # residual_a = 1.0 - 0.478 = 0.522
        # residual_b ≈ -0.522
        assert 0.4 < res_a < 0.6  # Brazil outperformed expectation
        assert res_b < -0.4  # Argentina underperformed
        # residuals are zero-sum
        assert abs(res_a + res_b) < 1e-10

    def test_draw_residual(self, sample_teams):
        """Draw → actual_a = 0.5, residual is small."""
        match = {
            "team_a": "Brazil",
            "team_b": "Argentina",
            "winner": None,
            "is_draw": True,
            "score_a": 1,
            "score_b": 1,
        }
        res_a, res_b, err = _compute_residual(match, sample_teams)
        assert err is None
        # draw: actual_a = 0.5
        assert abs(res_a + res_b) < 1e-10

    def test_missing_team_name(self, sample_teams):
        """Missing team_a or team_b → error reason."""
        match = {"team_a": None, "team_b": "Argentina", "winner": None}
        res_a, res_b, err = _compute_residual(match, sample_teams)
        assert err == "missing_team_name"
        assert res_a == 0.0
        assert res_b == 0.0

    def test_team_not_in_teams_data(self, sample_teams):
        """Team not found in teams dict → error reason."""
        match = {
            "team_a": "Brazil",
            "team_b": "Atlantis",
            "winner": None,
        }
        res_a, res_b, err = _compute_residual(match, sample_teams)
        assert err is not None and "team_not_in_teams_data" in err
        assert res_a == 0.0
        assert res_b == 0.0


class TestBuildTeamResiduals:
    """_build_team_residuals: per-team residual history from played matches."""

    def test_basic_build(self, sample_teams, sample_played_groups):
        """Two matches played → four team residual entries."""
        result = _build_team_residuals({}, sample_played_groups, sample_teams)
        assert "Brazil" in result
        assert "Argentina" in result
        assert "Germany" in result
        assert "France" in result
        assert len(result["Brazil"]) == 1
        assert len(result["Argentina"]) == 1

    def test_results_sorted_by_recency(self, sample_teams):
        """Multiple matches for same team → sorted descending by completed_at."""
        played_groups = {
            "M1": {
                "team_a": "Brazil",
                "team_b": "Germany",
                "winner": "Brazil",
                "completed_at": "2026-06-14T20:00:00Z",
            },
            "M2": {
                "team_a": "Brazil",
                "team_b": "Argentina",
                "winner": "Brazil",
                "completed_at": "2026-06-16T20:00:00Z",
            },
        }
        result = _build_team_residuals({}, played_groups, sample_teams)
        assert len(result["Brazil"]) == 2
        dates = [e["completed_at"] for e in result["Brazil"]]
        assert dates == sorted(dates, reverse=True)

    def test_skips_non_dict_match(self, sample_teams):
        """Non-dict entries in played/played_groups are silently skipped."""
        played_groups = {
            "M1": "not_a_dict",
        }
        result = _build_team_residuals({}, played_groups, sample_teams)
        assert result == {}


# ─── Compute Match Form Signal Tests ─────────────────────────────────


class TestComputeMatchFormSignal:
    """_compute_match_form_signal: form signal for a single pairing."""

    def test_basic_available(self, sample_teams):
        """Both teams have residuals → available=True with a probability."""
        team_residuals = {
            "Brazil": [{"residual": 0.3, "completed_at": "2026-06-15T20:00:00Z"}],
            "Argentina": [{"residual": -0.2, "completed_at": "2026-06-15T20:00:00Z"}],
        }
        result = _compute_match_form_signal(
            "Brazil", "Argentina", team_residuals, sample_teams,
            k=1.0, window=5,
        )
        assert result["available"] is True
        assert result["probability"] is not None
        assert 0 < result["probability"] < 1

    def test_team_not_found(self, sample_teams):
        """Team not in teams dict → available=False with reason."""
        team_residuals = {}
        result = _compute_match_form_signal(
            "Brazil", "Atlantis", team_residuals, sample_teams,
            k=1.0, window=5,
        )
        assert result["available"] is False
        assert "team_not_found" in result["reason"]

    def test_unavailable_if_no_matches(self, sample_teams):
        """Team with zero match history → available=False."""
        team_residuals = {
            "Brazil": [{"residual": 0.3, "completed_at": "2026-06-15T20:00:00Z"}],
            "Argentina": [],
        }
        result = _compute_match_form_signal(
            "Brazil", "Argentina", team_residuals, sample_teams,
            k=1.0, window=5,
        )
        assert result["available"] is False
        assert "no_match_history" in result["reason"]


# ─── Form Signal (Integration) Tests ─────────────────────────────────


class TestFormSignal:
    """compute_form_signal: full pipeline integration."""

    def test_basic_signal(self, sample_teams, sample_groups, sample_played_groups, sample_played, monkeypatch):
        """Two teams with history in groups → valid probability in result."""
        # Patch ledger_upsert in state to avoid disk writes
        ledger_calls = []
        monkeypatch.setattr(
            "src.state.ledger_upsert",
            lambda mid, key, entry: ledger_calls.append((mid, key, entry)),
        )
        result = compute_form_signal(
            teams=sample_teams,
            groups=sample_groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=[],
        )
        assert "matches" in result
        assert "GS_A_01" in result["matches"]
        entry = result["matches"]["GS_A_01"]
        assert entry["available"] is True
        assert entry["probability"] is not None
        assert 0 < entry["probability"] < 1

    def test_form_delta_sign(self, sample_teams, sample_groups, sample_played_groups, sample_played, monkeypatch):
        """Team with positive residual (good form) favored over negative residual."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
        # Brazil won (positive residual), Argentina lost (negative residual)
        result = compute_form_signal(
            teams=sample_teams,
            groups=sample_groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=[],
        )
        entry = result["matches"]["GS_A_01"]
        # Brazil has positive residual from their win → favored as team_a
        assert entry["probability"] > 0.5

    def test_available_flag(self, sample_teams, sample_groups, sample_played_groups, sample_played, monkeypatch):
        """Both teams have match history → available=True."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
        result = compute_form_signal(
            teams=sample_teams,
            groups=sample_groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=[],
        )
        assert result["matches"]["GS_A_01"]["available"] is True

    def test_unavailable_if_no_matches(self, sample_teams, monkeypatch):
        """One team has 0 played matches → available=False."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
        groups = {
            "groups": {
                "A": {
                    "teams": ["Brazil", "France"],
                    "matches": [
                        {"match_id": "GS_A_01", "team_a": "Brazil", "team_b": "France",
                         "winner": None},
                    ],
                }
            }
        }
        # Only Brazil has played matches (from sample_played_groups which is not passed)
        result = compute_form_signal(
            teams=sample_teams,
            groups=groups,
            played={},
            played_groups={
                "GS_A_02": {
                    "match_id": "GS_A_02",
                    "team_a": "Brazil",
                    "team_b": "Germany",
                    "winner": "Brazil",
                    "completed_at": "2026-06-15T20:00:00Z",
                },
            },
            bracket=[],
        )
        assert result["matches"]["GS_A_01"]["available"] is False

    def test_bracket_matches_included(self, sample_teams, sample_played_groups, sample_played, monkeypatch):
        """Bracket with resolved teams → predictions included."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
        groups = {"groups": {}}
        bracket = [
            {"match_id": "R16_1", "team_a": "Brazil", "team_b": "Germany", "winner": None},
        ]
        result = compute_form_signal(
            teams=sample_teams,
            groups=groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=bracket,
        )
        assert "R16_1" in result["matches"]
        assert result["matches"]["R16_1"]["available"] is True

    def test_unresolved_bracket_slot_skipped(self, sample_teams, sample_played_groups, sample_played, monkeypatch):
        """Bracket entry with None team_a/team_b → skipped gracefully."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
        groups = {"groups": {}}
        bracket = [
            {"match_id": "QF_1", "team_a": None, "team_b": None, "winner": None},
        ]
        result = compute_form_signal(
            teams=sample_teams,
            groups=groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=bracket,
        )
        assert "QF_1" not in result["matches"]

    def test_has_timestamp_keys(self, sample_teams, sample_groups, sample_played_groups, sample_played, monkeypatch):
        """Result dict has fetched_at and expires_at keys."""
        monkeypatch.setattr("src.state.ledger_upsert", lambda *a, **kw: None)
        result = compute_form_signal(
            teams=sample_teams,
            groups=sample_groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=[],
        )
        assert "fetched_at" in result
        assert "expires_at" in result


# ─── Window Size Tests ───────────────────────────────────────────────


class TestWindowSize:
    """Form rolling window behavior."""

    def test_window_size_limits(self, sample_teams):
        """10 matches with window=5 → only last 5 used."""
        team_residuals = {
            "Brazil": [
                {"residual": 0.1, "completed_at": f"2026-06-{15-i:02d}T20:00:00Z"}
                for i in range(10)
            ],
            "Argentina": [
                {"residual": -0.1, "completed_at": f"2026-06-{15-i:02d}T20:00:00Z"}
                for i in range(10)
            ],
        }
        result = _compute_match_form_signal(
            "Brazil", "Argentina", team_residuals, sample_teams,
            k=1.0, window=5,
        )
        assert result["available"] is True

    def test_zero_matches_returns_unavailable(self, sample_teams):
        """Team with no matches → available=False."""
        team_residuals = {
            "Brazil": [],
            "Argentina": [],
        }
        result = _compute_match_form_signal(
            "Brazil", "Argentina", team_residuals, sample_teams,
            k=1.0, window=5,
        )
        assert result["available"] is False

    def test_fewer_than_window(self, sample_teams):
        """2 matches, window=5 → uses all 2 (still available)."""
        team_residuals = {
            "Brazil": [
                {"residual": 0.2, "completed_at": "2026-06-15T20:00:00Z"},
                {"residual": 0.3, "completed_at": "2026-06-16T20:00:00Z"},
            ],
            "Argentina": [
                {"residual": -0.1, "completed_at": "2026-06-15T20:00:00Z"},
                {"residual": -0.2, "completed_at": "2026-06-16T20:00:00Z"},
            ],
        }
        result = _compute_match_form_signal(
            "Brazil", "Argentina", team_residuals, sample_teams,
            k=1.0, window=5,
        )
        assert result["available"] is True
        assert result["probability"] > 0.5  # Brazil has positive residual trend


# ─── Ledger Tests ────────────────────────────────────────────────────


class TestFormLedger:
    """Ledger upsert from compute_form_signal."""

    def test_ledger_upsert_called(self, sample_teams, sample_groups, sample_played_groups, sample_played, monkeypatch):
        """compute_form_signal calls ledger_upsert for each match result."""
        ledger_calls = []
        monkeypatch.setattr(
            "src.state.ledger_upsert",
            lambda mid, key, entry: ledger_calls.append((mid, key)),
        )
        compute_form_signal(
            teams=sample_teams,
            groups=sample_groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=[],
        )
        assert len(ledger_calls) >= 1
        # All calls should have signal_key "form"
        for mid, key in ledger_calls:
            assert key == "form"

    def test_ledger_key_form(self, sample_teams, sample_groups, sample_played_groups, sample_played, monkeypatch):
        """Ledger upsert uses signal key 'form'."""
        ledger_calls = []
        monkeypatch.setattr(
            "src.state.ledger_upsert",
            lambda mid, key, entry: ledger_calls.append((mid, key)),
        )
        compute_form_signal(
            teams=sample_teams,
            groups=sample_groups,
            played=sample_played,
            played_groups=sample_played_groups,
            bracket=[],
        )
        assert all(key == "form" for _, key in ledger_calls)
