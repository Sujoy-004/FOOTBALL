"""Tests for the console output module (Phase 5)."""

import io
import sys
from unittest.mock import patch

import pytest

from src.output import (
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
        output = _capture(print_error, "API error. Timeout. Retry in 60s. Using cached data.")
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
            (print_error, ["test error"]),
        ]
        for func, args in funcs_and_args:
            output = _capture(func, *args)
            assert "[20" in output, f"{func.__name__} should have timestamp"
