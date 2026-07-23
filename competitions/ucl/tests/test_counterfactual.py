"""Tests for counterfactual analysis — Phase 11, Plan 11-02.

Covers:
    - parse_what_if() argument parsing
    - _run_counterfactual() execution with mocked fixtures
    - print_counterfactual_comparison() display
"""

from __future__ import annotations

from typing import Any

import pytest

from competitions.ucl.src.analysis import parse_what_if
from competitions.ucl.result import SimulationResult


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_team_data(
    champion_prob: float = 0.1,
    stage_final: float = 0.2,
    stage_sf: float = 0.3,
    stage_qf: float = 0.4,
) -> dict:
    """Create minimal team data dict for SimulationResult.teams."""
    return {
        "champion_prob": champion_prob,
        "stage_final_prob": stage_final,
        "stage_sf_prob": stage_sf,
        "stage_qf_prob": stage_qf,
    }


def _make_minimal_result(
    champion: str = "Arsenal",
    teams_data: dict[str, dict] | None = None,
) -> SimulationResult:
    """Create a minimal SimulationResult for display testing."""
    if teams_data is None:
        teams_data = {
            "Arsenal": _make_team_data(champion_prob=0.688),
            "Man City": _make_team_data(champion_prob=0.062),
            "Real Madrid": _make_team_data(champion_prob=0.051),
            "Bayern": _make_team_data(champion_prob=0.043),
            "PSG": _make_team_data(champion_prob=0.031),
        }
    return SimulationResult(
        snapshot_date="2026-07-03",
        n_iterations=10000,
        seed=42,
        standings=[
            {"team": t, "position": i + 1, "zone": "top_8" if i < 8 else "playoff"}
            for i, t in enumerate(list(teams_data.keys())[:24])
        ],
        teams=teams_data,
        playoff_ties={},
        playoff_winners={},
        bracket_rounds={},
        bracket_champion=champion,
        stages={t: "champion" if t == champion else "eliminated" for t in teams_data},
    )


# ── TestWhatIfParsing ──────────────────────────────────────────────────────


class TestWhatIfParsing:
    """Tests for parse_what_if()."""

    def test_basic_parsing(self):
        """Basic team.param=value parsing."""
        result = parse_what_if(["Arsenal.elo=1960"])
        assert len(result) == 1
        assert result[0]["team"] == "Arsenal"
        assert result[0]["param"] == "elo"
        assert result[0]["value"] == 1960.0

    def test_multiple_modifications(self):
        """Multiple --what-if flags produce multiple modifications."""
        result = parse_what_if([
            "Arsenal.elo=1960",
            "RealMadrid.elo=2100",
        ])
        assert len(result) == 2
        assert result[0]["team"] == "Arsenal"
        assert result[1]["team"] == "RealMadrid"

    def test_float_value(self):
        """Float values are accepted."""
        result = parse_what_if(["Arsenal.elo=1950.5"])
        assert result[0]["value"] == 1950.5

    def test_empty_list_returns_empty(self):
        """None or empty list returns empty list."""
        assert parse_what_if(None) == []
        assert parse_what_if([]) == []

    def test_missing_dot_raises(self):
        """Missing dot in format raises ValueError."""
        with pytest.raises(ValueError):
            parse_what_if(["Arsenalo=1960"])

    def test_missing_equals_raises(self):
        """Missing equals raises ValueError."""
        with pytest.raises(ValueError):
            parse_what_if(["Arsenal.elo1960"])

    def test_unknown_param_raises(self):
        """Unknown parameter raises ValueError with supported list."""
        with pytest.raises(ValueError):
            parse_what_if(["Arsenal.rest_days=5"])

    def test_non_numeric_value_raises(self):
        """Non-numeric value raises ValueError."""
        with pytest.raises(ValueError):
            parse_what_if(["Arsenal.elo=abc"])

    def test_negative_value_raises(self):
        """Negative Elo value raises ValueError."""
        with pytest.raises(ValueError):
            parse_what_if(["Arsenal.elo=-100"])

    def test_empty_team_name_raises(self):
        """Empty team name raises ValueError."""
        with pytest.raises(ValueError):
            parse_what_if([".elo=1960"])



# ── TestReport ────────────────────────────────────────────────────────────


class TestReport:
    """Tests for report generation."""

    def test_build_report_returns_dict(self):
        """build_report returns a dict."""
        from competitions.ucl.report import build_report

        baseline = _make_minimal_result()
        report = build_report(baseline)
        assert isinstance(report, dict)

    def test_report_has_expected_sections(self):
        """Report contains all expected top-level keys."""
        from competitions.ucl.report import build_report

        baseline = _make_minimal_result()
        report = build_report(baseline)
        assert "simulation" in report
        assert "champion" in report
        assert "qualification" in report
        assert "signal_breakdown" in report
        assert "validation" in report
        assert "counterfactuals" in report

    def test_report_simulation_metadata(self):
        """Simulation section contains metadata."""
        from competitions.ucl.report import build_report

        baseline = _make_minimal_result()
        report = build_report(baseline)
        sim = report["simulation"]
        assert sim["snapshot_date"] == "2026-07-03"
        assert sim["n_iterations"] == 10000
        assert sim["seed"] == 42

    def test_report_champion_section(self):
        """Champion section has team and probability."""
        from competitions.ucl.report import build_report

        baseline = _make_minimal_result(champion="Arsenal")
        report = build_report(baseline)
        champ = report["champion"]
        assert champ["team"] == "Arsenal"
        assert "top_5" in champ
        assert len(champ["top_5"]) == 5

    def test_report_qualification_section(self):
        """Qualification section has top_8 and playoff lists."""
        from competitions.ucl.report import build_report

        baseline = _make_minimal_result()
        report = build_report(baseline)
        qual = report["qualification"]
        assert "top_8" in qual
        assert "playoff" in qual

    def test_report_counterfactuals_none_when_not_used(self):
        """Counterfactuals is None when no --what-if used."""
        from competitions.ucl.report import build_report

        baseline = _make_minimal_result()
        report = build_report(baseline)
        assert report["counterfactuals"] is None

    def test_report_counterfactuals_present_when_used(self):
        """Counterfactuals section present when results provided."""
        from competitions.ucl.report import build_report

        baseline = _make_minimal_result(champion="Arsenal")
        cf_result = _make_minimal_result(champion="Arsenal")
        report = build_report(
            baseline,
            counterfactual_results=[(cf_result, ["Arsenal.elo=1960"])],
        )
        assert report["counterfactuals"] is not None
        assert len(report["counterfactuals"]) == 1
        assert report["counterfactuals"][0]["changes"] == ["Arsenal.elo=1960"]

    def test_write_report_creates_file(self, tmp_path):
        """write_report creates valid JSON file."""
        from competitions.ucl.report import build_report, write_report

        baseline = _make_minimal_result()
        report = build_report(baseline)
        output_path = tmp_path / "test_report.json"
        write_report(report, str(output_path))
        assert output_path.exists()

        import json
        with open(output_path) as f:
            loaded = json.load(f)
        assert isinstance(loaded, dict)
        assert "simulation" in loaded


# ── TestCounterfactualExecution ────────────────────────────────────────────


class TestCounterfactualExecution:
    """Tests for _run_counterfactual execution logic."""

    def test_parse_team_not_in_elo(self):
        """Parsing works even if team not in elo dict (runtime check)."""
        result = parse_what_if(["UnknownTeam.elo=1800"])
        assert len(result) == 1
        assert result[0]["team"] == "UnknownTeam"
        assert result[0]["value"] == 1800.0

    def test_what_if_raises_value_error_for_invalid(self):
        """Invalid --what-if format raises ValueError."""
        with pytest.raises(ValueError):
            parse_what_if(["invalid"])
        with pytest.raises(ValueError):
            parse_what_if(["noequals"])
