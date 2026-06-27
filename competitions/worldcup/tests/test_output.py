"""Tests for the console output module (Phase 5)."""

import io
import sys
from unittest.mock import patch

import pytest

from src.output import (
    _compute_trend_arrow,
    print_ai_previews,
    print_probability_table,
    print_delta_summary,
    print_simulation_duration,
    print_header,
    print_match_alert,
    print_elo_changes,
    print_heartbeat,
    print_auto_refresh,
    print_shutdown_banner,
    print_error,
    print_governance_dashlet,
    print_drift_alert,
    coverage_audit,
    print_coverage_audit,
    print_match_detail_table,
    print_focus_card,
    wilson_score_ci,
    format_ci,
    wilson_ci_from_prob,
    _supports_color,
)


@pytest.fixture
def full_probs():
    """Returns a 32-team probs dict for table tests."""
    names = [
        "Argentina", "Brazil", "France", "England", "Spain",
        "Germany", "Netherlands", "Portugal", "Belgium", "Croatia",
        "Italy", "Uruguay", "Denmark", "Switzerland", "Mexico", "USA",
        "Senegal", "Japan", "Morocco", "Serbia", "Poland", "Korea",
        "Nigeria", "Australia", "Japan_2", "Iran", "Ghana", "Cameroon",
        "Costa_Rica", "Saudi_Arabia", "Ecuador", "Wales",
    ]
    probs = {}
    for i, name in enumerate(names):
        champion = max(0.001, round(1.0 / (32 + i * 0.5), 4))
        probs[name] = {
            "qf": round(champion * (32 - i) / 16, 4),
            "sf": round(champion * (32 - i) / 24, 4),
            "final": round(champion * (32 - i) / 28, 4),
            "champion": champion,
        }
    return probs


@pytest.fixture
def small_probs():
    """Returns a 5-team probs dict for delta tests."""
    return {
        "Argentina": {"qf": 0.9, "sf": 0.7, "final": 0.5, "champion": 0.30},
        "Brazil": {"qf": 0.8, "sf": 0.6, "final": 0.4, "champion": 0.25},
        "France": {"qf": 0.7, "sf": 0.5, "final": 0.3, "champion": 0.20},
        "Germany": {"qf": 0.6, "sf": 0.4, "final": 0.2, "champion": 0.15},
        "England": {"qf": 0.5, "sf": 0.3, "final": 0.1, "champion": 0.10},
    }


def _capture(func, *args, **kwargs):
    """Run func(*args, **kwargs) and return captured stdout string."""
    buf = io.StringIO()
    real = sys.stdout
    sys.stdout = buf
    try:
        func(*args, **kwargs)
    finally:
        sys.stdout = real
    return buf.getvalue()


class TestProbabilityTable:
    """Tests for print_probability_table()."""

    def test_top5_table(self, full_probs):
        output = _capture(print_probability_table, full_probs)
        lines = [l for l in output.split("\n") if l.strip()]
        sorted_teams = sorted(full_probs, key=lambda n: full_probs[n]["champion"], reverse=True)
        top5 = sorted_teams[:5]
        for name in top5:
            assert any(name in line for line in lines), f"Top-5 team {name} not found"

    def test_first_call_no_deltas(self, full_probs):
        output = _capture(print_probability_table, full_probs, None)
        assert "Delta" not in output, "Delta column should not appear when prev_probs=None"
        assert "▲" not in output, "No ▲ symbol on first call"
        assert "▼" not in output, "No ▼ symbol on first call"

    def test_delta_symbol_and_color(self, full_probs):
        prev = full_probs.copy()
        cur = {k: dict(v) for k, v in full_probs.items()}
        cur["Argentina"]["champion"] += 0.01
        cur["Spain"]["champion"] -= 0.0003
        output = _capture(print_probability_table, cur, prev)
        assert "▲" in output, "Should show ▲ for increased probability"
        assert "▼" in output, "Should show ▼ for decreased probability"
        if _supports_color():
            assert "\033[32m" in output or "\033[1;32m" in output, "Green ANSI for positive"

    def test_remaining_teams(self, full_probs):
        output = _capture(print_probability_table, full_probs)
        assert "other teams" in output, "Should show remaining teams summary"
        assert "best:" in output, "Should show best remaining team"
        sorted_teams = sorted(full_probs, key=lambda n: full_probs[n]["champion"], reverse=True)
        best_remaining = sorted_teams[5]
        expected_val = full_probs[best_remaining]["champion"]
        assert f"{expected_val:.3f}" in output, "Should show best remaining prob"


class TestDeltaSummary:
    """Tests for print_delta_summary()."""

    def test_top3_risers_fallers(self, small_probs):
        prev = {
            k: dict(v) for k, v in small_probs.items()
        }
        cur = {
            "Argentina": dict(small_probs["Argentina"]),
            "Brazil": dict(small_probs["Brazil"]),
            "France": dict(small_probs["France"]),
            "Germany": dict(small_probs["Germany"]),
            "England": dict(small_probs["England"]),
        }
        cur["Argentina"]["champion"] = 0.35
        cur["Brazil"]["champion"] = 0.20
        cur["France"]["champion"] = 0.18
        cur["Germany"]["champion"] = 0.12
        cur["England"]["champion"] = 0.15
        output = _capture(print_delta_summary, cur, prev)
        assert "Risers" in output, "Should show risers header"
        assert "Fallers" in output, "Should show fallers header"
        assert "+" in output or "▲" in output, "Should show positive deltas"

    def test_no_deltas_when_prev_none(self, small_probs):
        output = _capture(print_delta_summary, small_probs, None)
        assert not output.strip(), "Should produce no output when prev is None"


class TestAnsiFallback:
    """Tests for ANSI/no-color behavior."""

    @patch("src.output._supports_color", return_value=False)
    def test_no_ansi_when_piped(self, mock_color, full_probs):
        output = _capture(print_probability_table, full_probs)
        assert "\033[" not in output, "No ANSI escape codes when piped"

    @patch("src.output._supports_color", return_value=False)
    def test_symbols_preserved(self, mock_color, full_probs):
        prev = full_probs.copy()
        cur = {k: dict(v) for k, v in full_probs.items()}
        cur["Argentina"]["champion"] += 0.0005
        cur["Spain"]["champion"] -= 0.0003
        output = _capture(print_probability_table, cur, prev)
        assert "▲" in output or "▼" in output, "Symbols ▲▼ preserved without color"


class TestSimulationDuration:
    """Tests for print_simulation_duration()."""

    def test_duration_format(self):
        output = _capture(print_simulation_duration, 0.8)
        assert "done in" in output, "Should contain done in phrase"
        assert "0.8" in output, "Should show duration value"

    def test_duration_bold_green(self):
        output = _capture(print_simulation_duration, 1.5)
        if _supports_color():
            assert "\033[1;32m" in output, "Should use bold green ANSI for duration"


class TestHeader:
    """Tests for print_header()."""

    def test_header_format(self):
        teams = {"Arg": {}, "Bra": {}}
        bracket = [{"match_id": "1"}]
        played = {"m1": {}}
        aliases = {"Arg": ["Argentina"]}
        output = _capture(print_header, teams, bracket, played, aliases)
        assert "WORLD CUP DYNAMIC PREDICTOR" in output
        assert "Polling API every" in output
        assert "Loaded 2 teams, 1 bracket matches, 1 played matches, 1 aliases" in output
        if _supports_color():
            assert "\033[1;36m" in output, "Bold cyan for banner"

    @patch("src.output._supports_color", return_value=False)
    def test_header_no_ansi_when_piped(self, mock_color):
        output = _capture(print_header, {}, [], {}, {})
        assert "\033[" not in output, "No ANSI when piped"


class TestMatchAlert:
    """Tests for print_match_alert()."""

    def test_match_block(self):
        match = {
            "team_a": "Argentina", "team_b": "Nigeria",
            "home_score": 2, "away_score": 1,
            "winner": "Argentina",
        }
        output = _capture(print_match_alert, match)
        assert "NEW MATCH DETECTED!" in output
        assert "Argentina" in output
        assert "Nigeria" in output
        assert "2 - 1" in output
        assert "Winner: Argentina" in output
        if _supports_color():
            assert "\033[1;33m" in output, "Bold yellow ANSI"

    def test_match_with_different_score(self):
        match = {
            "team_a": "Brazil", "team_b": "France",
            "home_score": 3, "away_score": 0,
            "winner": "Brazil",
        }
        output = _capture(print_match_alert, match)
        assert "3 - 0" in output


class TestEloChanges:
    """Tests for print_elo_changes()."""

    def test_elo_format(self):
        updates = {
            "Argentina": {"old": 2100, "new": 2112},
            "Nigeria": {"old": 1850, "new": 1838},
        }
        output = _capture(print_elo_changes, updates)
        assert "Updating Elo:" in output
        assert "Argentina" in output
        assert "2100" in output
        assert "2112" in output
        assert "+12" in output or "12" in output


class TestHeartbeat:
    """Tests for print_heartbeat()."""

    def test_heartbeat_single_line(self):
        output = _capture(print_heartbeat)
        lines = [l for l in output.split("\n") if l.strip()]
        assert len(lines) == 1, "Heartbeat should be exactly one line"

    def test_heartbeat_content(self):
        output = _capture(print_heartbeat)
        assert "Polling" in output
        assert "no new matches" in output


class TestAutoRefresh:
    """Tests for print_auto_refresh()."""

    def test_auto_refresh_text(self):
        output = _capture(print_auto_refresh)
        assert "Auto-refresh simulation" in output


class TestShutdownBanner:
    """Tests for print_shutdown_banner()."""

    def test_shutdown_banner_all_teams(self, small_probs):
        output = _capture(print_shutdown_banner, small_probs)
        for team in small_probs:
            assert team in output, f"Team {team} should appear in shutdown table"

    def test_shutdown_banner_format(self, small_probs):
        output = _capture(print_shutdown_banner, small_probs)
        assert "FINAL CHAMPIONSHIP PROBABILITIES" in output
        assert "State saved. Goodbye." in output
        if _supports_color():
            assert "\033[1;32m" in output, "Bold green for shutdown banner"

    def test_shutdown_banner_no_deltas(self, small_probs):
        output = _capture(print_shutdown_banner, small_probs)
        assert "Delta" not in output, "No delta column in shutdown table"
        assert "▲" not in output, "No delta symbols in shutdown"


class TestError:
    """Tests for print_error()."""

    def test_error_format(self):
        buf = io.StringIO()
        real = sys.stderr
        sys.stderr = buf
        try:
            print_error("API error. Timeout. Retry in 60s. Using cached data.")
        finally:
            sys.stderr = real
        output = buf.getvalue()
        assert "⚠" in output
        if _supports_color():
            assert "\033[1;31m" in output, "Bold red for errors"


class TestTimestampConsistency:
    """Tests that all output blocks have timestamps."""

    @patch("src.output._supports_color", return_value=False)
    def test_all_block_timestamps(self, mock_color, small_probs):
        teams = {"Arg": {}, "Bra": {}}
        bracket = [{"match_id": "1"}]
        played = {"m1": {}}
        aliases = {"Arg": ["Argentina"]}
        match = {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0, "winner": "A"}
        elo_updates = {"Arg": {"old": 2000, "new": 2010}}

        funcs_and_args = [
            (print_elo_changes, [elo_updates]),
            (print_heartbeat, []),
            (print_auto_refresh, []),
        ]
        for func, args in funcs_and_args:
            output = _capture(func, *args)
            assert "[20" in output, f"{func.__name__} should have timestamp"

        buf = io.StringIO()
        real = sys.stderr
        sys.stderr = buf
        try:
            print_error("test error")
        finally:
            sys.stderr = real
        assert "[20" in buf.getvalue(), "print_error should have timestamp"


class TestNoColorFlag:
    """Tests for --no-color integration with output module (Phase 6)."""

    def test_no_color_true_disables_ansi(self):
        """Setting output.NO_COLOR = True disables ANSI codes."""
        import src.output as output_mod
        output_mod.NO_COLOR = True
        try:
            assert output_mod._supports_color() is False, (
                "NO_COLOR=True should force _supports_color() to False"
            )
        finally:
            output_mod.NO_COLOR = False  # restore for other tests

    def test_no_color_false_defers_to_tty(self):
        """When NO_COLOR=False, _supports_color() defers to isatty()."""
        import src.output as output_mod
        saved = output_mod.NO_COLOR
        output_mod.NO_COLOR = False
        try:
            # Mock isatty to return True — _supports_color should also return True
            original_isatty = sys.stdout.isatty
            sys.stdout.isatty = lambda: True
            try:
                assert output_mod._supports_color() is True
            finally:
                sys.stdout.isatty = original_isatty
        finally:
            output_mod.NO_COLOR = saved

    def test_default_is_false(self):
        """NO_COLOR is False by default on fresh import."""
        import src.output as output_mod
        assert output_mod.NO_COLOR is False, "Default NO_COLOR should be False"


# ─── Governance Dashlet Tests (Plan 16-02) ────────────────────────────────


class TestGovernanceDashlet:
    """Tests for print_governance_dashlet()."""

    def _sample_versions(self):
        return {
            "data_version": "D3",
            "model_version": "M2",
            "run_version": "R47",
            "last_data_change": "2026-06-18T12:00:00",
            "last_model_change": "2026-06-18T12:00:00",
            "last_run_timestamp": "2026-06-18T12:30:00",
        }

    def _sample_brier(self):
        return {"elo": 0.108, "market_odds": 0.097, "catboost": 0.101, "form": 0.112, "lineup_strength": 0.118}

    def _sample_weights(self):
        return {"elo": 0.25, "market_odds": 0.25, "catboost": 0.20, "form": 0.15, "lineup_strength": 0.15}

    def test_dashlet_cold_start_format(self):
        """Cold-start: shows COLD START, PENDING, DISABLED, READY, version strings, match count."""
        output = _capture(
            print_governance_dashlet,
            self._sample_versions(),
            "COLD START",
            19,
            self._sample_brier(),
            self._sample_weights(),
        )
        assert "MODEL GOVERNANCE" in output
        assert "COLD START" in output
        assert "Data Version" in output
        assert "D3" in output
        assert "Model Version" in output
        assert "M2" in output
        assert "Run Version" in output
        assert "R47" in output
        assert "19 / 30" in output
        assert "PENDING" in output
        assert "DISABLED" in output
        assert "READY" in output

    def test_dashlet_active_format(self):
        """Active: shows HEALTHY, per-signal Brier table, drift status column."""
        output = _capture(
            print_governance_dashlet,
            self._sample_versions(),
            "HEALTHY",
            50,
            self._sample_brier(),
            self._sample_weights(),
        )
        assert "MODEL GOVERNANCE" in output
        assert "HEALTHY" in output
        assert "elo" in output
        assert "0.108" in output
        assert "OK" in output

    def test_dashlet_drift_format(self):
        """Drift: shows DRIFT DETECTED alert section."""
        drift_results = {
            "market_odds": {
                "signal": "market_odds",
                "rolling_mean": 0.132,
                "reference_baseline": 0.094,
                "sigma": 0.0135,
                "threshold": 0.121,
                "drifted": True,
                "delta": 0.011,
            }
        }
        output = _capture(
            print_governance_dashlet,
            self._sample_versions(),
            "DRIFT",
            50,
            self._sample_brier(),
            self._sample_weights(),
            drift_results=drift_results,
        )
        assert "DRIFT DETECTED" in output
        assert "market_odds" in output
        assert "0.094" in output  # reference
        assert "0.132" in output  # rolling
        assert "0.121" in output  # threshold

    def test_dashlet_backtest_summary(self):
        """Backtest summary line printed when provided."""
        output = _capture(
            print_governance_dashlet,
            self._sample_versions(),
            "HEALTHY",
            50,
            self._sample_brier(),
            self._sample_weights(),
            backtest_summary="2018 Brier=0.127",
        )
        assert "2018 Brier=0.127" in output


class TestDriftAlert:
    """Tests for print_drift_alert()."""

    def test_drift_alert_format(self):
        """All 5 fields printed: signal, reference, rolling, threshold, delta."""
        drift_info = {
            "signal": "market_odds",
            "reference_baseline": 0.094,
            "rolling_mean": 0.132,
            "threshold": 0.121,
            "delta": 0.011,
        }
        output = _capture(print_drift_alert, drift_info)
        assert "DRIFT DETECTED" in output
        assert "market_odds" in output
        assert "0.094" in output
        assert "0.132" in output
        assert "0.121" in output
        assert "0.011" in output


# ─── AI Preview Display Tests (Phase 18) ────────────────────────────────────


class TestAiPreviews:
    """Tests for print_ai_previews()."""

    def test_print_ai_previews_shows_text(self):
        """Preview text appears in captured output with header."""
        played = {}
        played_groups = {
            "GS_A_01": {
                "match_id": "GS_A_01",
                "team_a": "Mexico",
                "team_b": "South Africa",
                "ai_preview": "Mexico expected to dominate possession.",
            },
        }
        output = _capture(print_ai_previews, played, played_groups)
        assert "AI Previews" in output
        assert "Mexico" in output
        assert "South Africa" in output
        assert "Mexico expected to dominate possession." in output

    def test_print_ai_previews_no_data(self):
        """No ai_preview entries shows the dim 'No AI previews available.' message."""
        played = {}
        played_groups = {
            "GS_A_01": {
                "match_id": "GS_A_01",
                "team_a": "Mexico",
                "team_b": "South Africa",
            },
        }
        output = _capture(print_ai_previews, played, played_groups)
        assert "No AI previews available." in output

    def test_print_ai_previews_knockout_and_group(self):
        """Both knockout and group match previews appear."""
        played = {
            "M73": {
                "match_id": "M73",
                "team_a": "Argentina",
                "team_b": "Brazil",
                "ai_preview": "Argentina slight favorites.",
            },
        }
        played_groups = {
            "GS_A_01": {
                "match_id": "GS_A_01",
                "team_a": "Mexico",
                "team_b": "South Africa",
                "ai_preview": "Mexico should win comfortably.",
            },
        }
        output = _capture(print_ai_previews, played, played_groups)
        assert "Argentina" in output
        assert "Brazil" in output
        assert "Mexico" in output
        assert "South Africa" in output


def _make_prob_log(*probs: float) -> list[dict]:
    """Helper: create a probability log list from a sequence of champion probs."""
    return [
        {
            "timestamp": "t",
            "probabilities": {
                "Argentina": {"champion": p},
                "Brazil": {"champion": p + 0.01},
                "France": {"champion": p - 0.01},
                "Germany": {"champion": p - 0.02},
                "England": {"champion": p - 0.03},
            },
        }
        for p in probs
    ]


class TestTrendColumn:
    def test_trend_arrow_up(self):
        arrow = _compute_trend_arrow(0.25, "Argentina", _make_prob_log(0.24, 0.24, 0.24, 0.24, 0.24, 0.24))
        assert arrow == "↑"

    def test_trend_arrow_down(self):
        arrow = _compute_trend_arrow(0.23, "Argentina", _make_prob_log(0.24, 0.24, 0.24, 0.24, 0.24, 0.24))
        assert arrow == "↓"

    def test_trend_arrow_flat(self):
        arrow = _compute_trend_arrow(0.242, "Argentina", _make_prob_log(0.24, 0.24, 0.24, 0.24, 0.24, 0.24))
        assert arrow == "→"

    def test_trend_hidden_first_run(self, full_probs):
        output = _capture(print_probability_table, full_probs)
        assert "Trend" not in output

    def test_trend_column_printed(self, full_probs):
        prob_log = [{"timestamp": "1", "probabilities": {"Argentina": {"champion": 0.24}, "Brazil": {"champion": 0.25}, "France": {"champion": 0.20}, "Germany": {"champion": 0.15}, "England": {"champion": 0.10}}}] * 7
        output = _capture(print_probability_table, full_probs, None, prob_log)
        assert "Trend" in output

    def test_trend_hidden_when_insufficient_data(self, full_probs):
        prob_log = [{"timestamp": "1", "probabilities": {"Argentina": {"champion": 0.24}}}] * 3
        output = _capture(print_probability_table, full_probs, None, prob_log)
        assert "Trend" not in output


class TestWilsonCI:
    def test_ci_known_values(self):
        low, high = wilson_score_ci(25000, 50000)
        assert 0.496 <= low <= 0.504
        assert 0.496 <= high <= 0.504

    def test_ci_extreme(self):
        low, high = wilson_score_ci(0, 50000)
        assert low >= 0.0
        assert high >= 0.0

    def test_ci_zero_n(self):
        assert wilson_score_ci(0, 0) == (0.0, 0.0)

    def test_format_ci(self):
        import re
        result = format_ci(25000, 50000)
        assert re.match(r"\[\d\.\d{3} — \d\.\d{3}\]", result)

    def test_wilson_ci_from_prob(self):
        result = wilson_ci_from_prob(0.5, 50000)
        assert result is not None
        assert isinstance(result, str)


def _sample_match_data() -> dict:
    return {
        "match_id": "M73",
        "team_a": "Argentina",
        "team_b": "Brazil",
        "signals": {
            "elo": 0.55, "odds": 0.52, "catboost": 0.53,
            "form": 0.51, "lineup": 0.54, "xg": (2.1, 1.2),
        },
        "blended": 0.53,
    }


def _sample_prev_data() -> dict:
    return {
        "match_id": "M73",
        "blended": 0.50,
    }


def _sample_match_data_focus() -> dict:
    return {
        "match_id": "M73",
        "team_a": "Argentina",
        "team_b": "Brazil",
        "signals": {
            "elo": 0.55, "odds": 0.52, "catboost": 0.53,
            "form": 0.51, "lineup": 0.54, "xg": (2.1, 1.2),
        },
        "blended": 0.53,
        "prev_signals": {"elo": 0.53, "odds": 0.50, "catboost": 0.51, "form": 0.50, "lineup": 0.52},
        "blended_delta": 0.03,
    }


class TestMatchDetailTable:
    def test_empty_shows_no_upcoming(self):
        output = _capture(print_match_detail_table, [])
        assert "No upcoming matches." in output

    def test_table_header_columns(self):
        output = _capture(print_match_detail_table, [_sample_match_data()])
        assert "Match" in output
        assert "Team A" in output
        assert "Team B" in output
        assert "Elo" in output
        assert "Odds" in output
        assert "CB" in output
        assert "Form" in output
        assert "Line" in output
        assert "xG" in output
        assert "Δ" in output

    def test_delta_shows_for_prev_data(self):
        output = _capture(print_match_detail_table, [_sample_match_data()], [_sample_prev_data()])
        assert "▲" in output or "▼" in output or "=" in output


class TestFocusCard:
    def test_signal_section_header(self):
        output = _capture(print_focus_card, _sample_match_data_focus())
        assert "Signal" in output
        assert "Prob" in output
        assert "Δ" in output
        assert "CI" in output

    def test_upcoming_match_context(self):
        output = _capture(print_focus_card, _sample_match_data_focus())
        assert "Context/stat data available after match completion." in output
        assert "Match Context" not in output
        assert "Match Stats" not in output

    def test_played_match_context(self):
        match_data = _sample_match_data_focus()
        match_entry = {
            "stats": {
                "fouls_home": 12, "fouls_away": 8,
                "corner_kicks_home": 7, "corner_kicks_away": 3,
            },
            "context": {
                "venue": "Estadio Azteca",
                "referee": "Wilton Pereira Sampaio",
                "venue_city": "Mexico City",
                "home_coach": "Gerardo Martino",
                "away_coach": "Hugo Broos",
            },
        }
        output = _capture(print_focus_card, match_data, match_entry)
        assert "Match Context" in output
        assert "Estadio Azteca" in output
        assert "Wilton Pereira Sampaio" in output

    def test_played_match_stats(self):
        match_data = _sample_match_data_focus()
        match_entry = {
            "stats": {
                "fouls_home": 12, "fouls_away": 8,
                "corner_kicks_home": 7, "corner_kicks_away": 3,
            },
            "context": {},
        }
        output = _capture(print_focus_card, match_data, match_entry)
        assert "Match Stats" in output
        assert "Fouls" in output
        assert "Corners" in output

    def test_missing_stats_played(self):
        match_data = _sample_match_data_focus()
        match_entry = {"context": {}}
        output = _capture(print_focus_card, match_data, match_entry)
        assert "Match Stats" not in output


class TestCoverageAudit:
    def test_meaningful_denominator_is_47(self):
        result = coverage_audit()
        assert result["meaningful"]["total"] == 47

    def test_meaningful_target_60(self):
        result = coverage_audit()
        assert result["meaningful"]["target"] == 60.0
        assert isinstance(result["meaningful"]["target_met"], bool)

    def test_by_category_keys(self):
        result = coverage_audit()
        assert "Prediction" in result["by_category"]
        assert "Display" in result["by_category"]
        assert "Operational" in result["by_category"]

    def test_print_output_format(self):
        output = _capture(print_coverage_audit)
        assert "Coverage Audit" in output
        assert "Meaningful" in output
        assert "Raw" in output
