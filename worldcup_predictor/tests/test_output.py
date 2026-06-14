"""Tests for the console output module (Phase 5)."""

import io
import sys
from unittest.mock import patch

import pytest

from src.output import (
    print_probability_table,
    print_delta_summary,
    print_simulation_duration,
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
        cur["Brazil"]["champion"] -= 0.005
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
        output = _capture(print_probability_table, full_probs, full_probs)
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
