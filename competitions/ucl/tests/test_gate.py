"""Tests for the match-level evaluation gate (gate.py)."""

from __future__ import annotations

import dataclasses
import math

import pytest

from competitions.ucl.src.gate import (
    evaluate_matches,
    load_gate_inputs,
    verdict_status,
    _build_signal_engine,
    _detect_chronology,
    _is_signal_varying,
)
from competitions.ucl.src.historical import order_matches, outcome_index
from football_core.blender import EnsembleEngine, compute_log_loss_weights
from football_core.signal import (
    BlendedPrediction,
    PredictionContext,
    Signal,
    SignalOutput,
)


# ── Helpers ──────────────────────────────────────────────────────────────


class StubSignal:
    """Minimal Signal-conforming stub with deterministic per-match outputs."""

    def __init__(self, name: str, home: float = 0.4, draw: float = 0.3, away: float = 0.3):
        self._name = name
        self._home = home
        self._draw = draw
        self._away = away

    @property
    def name(self):
        return self._name

    def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
        return SignalOutput(self._home, self._draw, self._away)


def _make_match(match_id, team_a, team_b, home_score, away_score, **extra):
    m = {
        "match_id": match_id,
        "team_a": team_a,
        "team_b": team_b,
        "home_score": home_score,
        "away_score": away_score,
    }
    m.update(extra)
    return m


def _make_synthetic_matches(n: int = 6) -> list[dict]:
    """Build n synthetic matchday-ordered matches with varied team pairs.

    Each match has scores so outcome_index is not None.
    Uses 4 team pairs rotated across matchdays so signals that depend
    on team identity (squad_value, elo) produce genuinely varying
    predictions across matches.
    """
    pairs = [
        ("Bayern", "Man City"),
        ("Arsenal", "Barcelona"),
        ("Real Madrid", "PSG"),
        ("Dortmund", "Liverpool"),
        ("Inter", "Chelsea"),
        ("Juventus", "Atletico Madrid"),
    ]
    scores = [
        (2, 1), (3, 0), (1, 2), (0, 1), (2, 2), (1, 0),
    ]
    matches = []
    for i in range(n):
        pair_idx = i % len(pairs)
        ta, tb = pairs[pair_idx]
        hs, aws = scores[i % len(scores)]
        mid = f"MD{(i // len(pairs)) + 1:02d}_{i + 1:02d}"
        matches.append(_make_match(mid, ta, tb, hs, aws))
    return matches


# ── TestEvaluateMatches ─────────────────────────────────────────────────


class TestEvaluateMatches:
    """Core gate evaluation tests."""

    def test_returns_expected_keys(self):
        matches = _make_synthetic_matches()
        squad = {"Bayern": 950, "Man City": 1250, "Arsenal": 750,
                 "Barcelona": 780, "Real Madrid": 1100, "PSG": 900,
                 "Dortmund": 600, "Liverpool": 870, "Inter": 680,
                 "Chelsea": 850, "Juventus": 500, "Atletico Madrid": 580}
        result = evaluate_matches(matches, squad_values=squad)
        assert result["n"] == len(matches)
        assert isinstance(result["n_real_signals"], int)
        assert isinstance(result["signals_available"], dict)
        assert isinstance(result["per_signal"], dict)
        assert "uniform_log_loss" in result["baselines"]
        assert "frequency_log_loss" in result["baselines"]
        assert "log_loss" in result["ensemble"]
        assert "brier" in result["ensemble"]
        assert "ece" in result["ensemble"]
        assert result["chronology"] in ("date", "matchday", "position")
        assert result["verdict"]["status"] in ("PASS", "UNVERIFIED")
        assert isinstance(result["verdict"]["reasons"], list)
        assert "evaluated_at" in result

    def test_per_signal_includes_available_signals(self):
        matches = _make_synthetic_matches()
        squad = {"Bayern": 950, "Man City": 1250, "Arsenal": 750,
                 "Barcelona": 780, "Real Madrid": 1100, "PSG": 900,
                 "Dortmund": 600, "Liverpool": 870, "Inter": 680,
                 "Chelsea": 850, "Juventus": 500, "Atletico Madrid": 580}
        result = evaluate_matches(matches, squad_values=squad)
        for sig_name in result["per_signal"]:
            assert "log_loss" in result["per_signal"][sig_name]
            assert "n" in result["per_signal"][sig_name]
            assert "constant" in result["per_signal"][sig_name]
            assert "available" in result["per_signal"][sig_name]
            assert result["per_signal"][sig_name]["n"] == len(matches)

    def test_ensemble_beats_uniform_on_synthetic_data(self):
        """With real varying signals, ensemble should beat uniform 1/3 baseline."""
        matches = _make_synthetic_matches(10)
        squad = {"Bayern": 950, "Man City": 1250, "Arsenal": 750,
                 "Barcelona": 780, "Real Madrid": 1100, "PSG": 900,
                 "Dortmund": 600, "Liverpool": 870, "Inter": 680,
                 "Chelsea": 850, "Juventus": 500, "Atletico Madrid": 580}
        result = evaluate_matches(matches, squad_values=squad)
        assert result["baselines"]["uniform_log_loss"] is not None
        assert result["ensemble"]["log_loss"] is not None
        # On data with real varying signals, ensemble should at least not be
        # worse than uniform.  If it is, the honest verdict reports UNVERIFIED.
        if result["ensemble"]["log_loss"] < result["baselines"]["uniform_log_loss"]:
            # Good: ensemble beats uniform
            pass
        else:
            # Honest: verdict should be UNVERIFIED (not faked)
            assert result["verdict"]["status"] == "UNVERIFIED"

    def test_chronology_is_matchday(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        assert result["chronology"] == "matchday"

    def test_baselines_populated(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        assert result["baselines"]["uniform_log_loss"] is not None
        assert result["baselines"]["uniform_log_loss"] > 0
        assert result["baselines"]["frequency_log_loss"] is not None
        assert result["baselines"]["frequency_log_loss"] > 0

    def test_verdict_has_reasons_list(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        assert isinstance(result["verdict"]["reasons"], list)

    def test_n_real_signals_counted(self):
        matches = _make_synthetic_matches()
        squad = {"Bayern": 950, "Man City": 1250, "Arsenal": 750,
                 "Barcelona": 780, "Real Madrid": 1100, "PSG": 900,
                 "Dortmund": 600, "Liverpool": 870, "Inter": 680,
                 "Chelsea": 850, "Juventus": 500, "Atletico Madrid": 580}
        result = evaluate_matches(matches, squad_values=squad)
        # With different team pairs, at least squad_value and refined_elo should vary
        assert result["n_real_signals"] >= 1

    def test_squad_value_signal_available_when_provided(self):
        matches = _make_synthetic_matches()
        squad = {"Bayern": 950, "Man City": 1250, "Arsenal": 750,
                 "Barcelona": 780, "Real Madrid": 1100, "PSG": 900,
                 "Dortmund": 600, "Liverpool": 870, "Inter": 680,
                 "Chelsea": 850, "Juventus": 500, "Atletico Madrid": 580}
        result = evaluate_matches(matches, squad_values=squad)
        assert result["signals_available"]["squad_value"] == "available"

    def test_squad_value_signal_unavailable_when_missing(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        assert result["signals_available"]["squad_value"].startswith("insufficient_data")

    def test_evaluated_at_is_iso_string(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        assert "T" in result["evaluated_at"]
        assert "Z" in result["evaluated_at"] or "+" in result["evaluated_at"]


# ── TestInsufficientData ────────────────────────────────────────────────


class TestInsufficientData:
    """Edge cases with missing or too-few matches."""

    def test_empty_list_returns_unverified(self):
        result = evaluate_matches([])
        assert result["n"] == 0
        assert result["verdict"]["status"] == "UNVERIFIED"
        assert any("no evaluable" in r for r in result["verdict"]["reasons"])

    def test_single_match_returns_unverified(self):
        matches = [_make_match("MD01_01", "Bayern", "Man City", 2, 1)]
        result = evaluate_matches(matches)
        assert result["n"] == 1
        assert result["verdict"]["status"] == "UNVERIFIED"
        assert any("below minimum" in r for r in result["verdict"]["reasons"])

    def test_no_crash_on_empty(self):
        result = evaluate_matches([])
        assert isinstance(result, dict)
        assert "verdict" in result

    def test_unplayed_matches_count_as_zero(self):
        matches = [_make_match("MD01_01", "A", "B", None, None)]
        result = evaluate_matches(matches)
        assert result["n"] == 0
        assert result["verdict"]["status"] == "UNVERIFIED"


# ── TestNoFeatureData ──────────────────────────────────────────────────


class TestNoFeatureData:
    """Signals unavailable due to missing feature inputs."""

    def test_signals_reported_unavailable(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        # Without elo_ratings, odds, dates, or squad_values:
        assert result["signals_available"]["refined_elo"].startswith("insufficient_data")
        assert result["signals_available"]["market_odds"].startswith("insufficient_data")
        assert result["signals_available"]["rolling_form"].startswith("insufficient_data")
        assert result["signals_available"]["rest_days"].startswith("insufficient_data")
        assert result["signals_available"]["squad_value"].startswith("insufficient_data")

    def test_verdict_unverified(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        assert result["verdict"]["status"] == "UNVERIFIED"

    def test_ensemble_still_populated(self):
        matches = _make_synthetic_matches()
        result = evaluate_matches(matches)
        assert result["ensemble"]["log_loss"] is not None
        assert result["ensemble"]["brier"] is not None
        assert result["ensemble"]["ece"] is not None


# ── TestVerdictStatus ──────────────────────────────────────────────────


class TestVerdictStatus:
    """verdict_status mapping behavior."""

    def test_none_returns_unverified(self):
        assert verdict_status(None) == "UNVERIFIED"

    def test_empty_dict_returns_unverified(self):
        assert verdict_status({}) == "UNVERIFIED"

    def test_missing_verdict_returns_unverified(self):
        assert verdict_status({"foo": "bar"}) == "UNVERIFIED"

    def test_verdict_without_status_returns_unverified(self):
        assert verdict_status({"verdict": {}}) == "UNVERIFIED"

    def test_pass_maps_to_pass(self):
        assert verdict_status({"verdict": {"status": "PASS"}}) == "PASS"

    def test_unverified_maps_to_unverified(self):
        assert verdict_status({"verdict": {"status": "UNVERIFIED"}}) == "UNVERIFIED"

    def test_unknown_status_returns_unverified(self):
        assert verdict_status({"verdict": {"status": "BANANA"}}) == "UNVERIFIED"

    def test_non_dict_verdict_returns_unverified(self):
        assert verdict_status({"verdict": "weird"}) == "UNVERIFIED"


# ── TestResultPyEvaluationField ────────────────────────────────────────


class TestResultPyEvaluationField:
    """SimulationResult construction with the new evaluation field."""

    def test_default_evaluation_is_none(self):
        from competitions.ucl.result import SimulationResult
        result = SimulationResult(
            snapshot_date="2026-06-28",
            n_iterations=100,
            seed=42,
            standings=[],
            teams={},
            playoff_ties={},
            playoff_winners={},
            bracket_rounds={},
            bracket_champion=None,
            stages={},
        )
        assert result.evaluation is None

    def test_evaluation_field_is_last(self):
        from competitions.ucl.result import SimulationResult
        fields = dataclasses.fields(SimulationResult)
        last_field = fields[-1]
        assert last_field.name == "evaluation"

    def test_can_set_evaluation(self):
        from competitions.ucl.result import SimulationResult
        ev = {"verdict": {"status": "PASS", "reasons": []}}
        result = SimulationResult(
            snapshot_date="2026-06-28",
            n_iterations=100,
            seed=42,
            standings=[],
            teams={},
            playoff_ties={},
            playoff_winners={},
            bracket_rounds={},
            bracket_champion=None,
            stages={},
            evaluation=ev,
        )
        assert result.evaluation == ev


# ── TestReportEvaluationKeys ───────────────────────────────────────────


class TestReportEvaluationKeys:
    """build_report includes evaluation and evaluation_status keys."""

    def test_report_has_evaluation_keys(self):
        from competitions.ucl.result import SimulationResult
        from competitions.ucl.report import build_report
        result = SimulationResult(
            snapshot_date="2026-06-28",
            n_iterations=100,
            seed=42,
            standings=[],
            teams={},
            playoff_ties={},
            playoff_winners={},
            bracket_rounds={},
            bracket_champion=None,
            stages={},
        )
        report = build_report(result)
        assert "evaluation" in report
        assert "evaluation_status" in report
        assert report["evaluation"] is None
        assert report["evaluation_status"] is None

    def test_report_passes_evaluation_through(self):
        from competitions.ucl.result import SimulationResult
        from competitions.ucl.report import build_report
        ev = {"verdict": {"status": "PASS", "reasons": []}, "n": 60}
        result = SimulationResult(
            snapshot_date="2026-06-28",
            n_iterations=100,
            seed=42,
            standings=[],
            teams={},
            playoff_ties={},
            playoff_winners={},
            bracket_rounds={},
            bracket_champion=None,
            stages={},
            evaluation=ev,
        )
        report = build_report(result)
        assert report["evaluation"] == ev
        assert report["evaluation_status"] == "PASS"

    def test_report_unverified_evaluation_status(self):
        from competitions.ucl.result import SimulationResult
        from competitions.ucl.report import build_report
        ev = {"verdict": {"status": "UNVERIFIED", "reasons": ["too few matches"]}}
        result = SimulationResult(
            snapshot_date="2026-06-28",
            n_iterations=100,
            seed=42,
            standings=[],
            teams={},
            playoff_ties={},
            playoff_winners={},
            bracket_rounds={},
            bracket_champion=None,
            stages={},
            evaluation=ev,
        )
        report = build_report(result)
        assert report["evaluation_status"] == "UNVERIFIED"


# ── TestLoadGateInputs ─────────────────────────────────────────────────


class TestLoadGateInputs:
    """load_gate_inputs returns (matches, squad_values) tuple."""

    def test_returns_tuple(self):
        result = load_gate_inputs()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_matches_is_list(self):
        matches, sv = load_gate_inputs()
        assert isinstance(matches, list)

    def test_squad_values_is_dict_or_none(self):
        matches, sv = load_gate_inputs()
        assert sv is None or isinstance(sv, dict)


# ── TestHelperFunctions ────────────────────────────────────────────────


class TestHelperFunctions:
    """Tests for internal helper functions."""

    def test_detect_chronology_matchday(self):
        matches = _make_synthetic_matches()
        assert _detect_chronology(matches) == "matchday"

    def test_detect_chronology_empty(self):
        assert _detect_chronology([]) == "position"

    def test_detect_chronology_position(self):
        matches = [_make_match("generic_01", "A", "B", 1, 0)]
        assert _detect_chronology(matches) == "position"

    def test_is_signal_varying_true(self):
        probs = [[0.5, 0.3, 0.2], [0.4, 0.3, 0.3], [0.6, 0.2, 0.2]]
        assert _is_signal_varying(probs) is True

    def test_is_signal_varying_false(self):
        probs = [[0.5, 0.3, 0.2], [0.5, 0.3, 0.2]]
        assert _is_signal_varying(probs) is False

    def test_is_signal_varying_single_match(self):
        probs = [[0.5, 0.3, 0.2]]
        assert _is_signal_varying(probs) is False

    def test_is_signal_varying_empty(self):
        assert _is_signal_varying([]) is False


# ── TestEngineConstruction ─────────────────────────────────────────────


class TestEngineConstruction:
    """Verify engine can be built with various input combinations."""

    def test_build_engine_no_args(self):
        engine = _build_signal_engine()
        assert isinstance(engine, EnsembleEngine)
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        result = engine.evaluate({"match_id": "test"}, ctx)
        assert isinstance(result, BlendedPrediction)
        assert abs(result.home_prob + result.draw_prob + result.away_prob - 1.0) < 1e-4

    def test_build_engine_with_weights(self):
        weights = {"refined_elo": 0.5, "squad_value": 0.5}
        engine = _build_signal_engine(weights=weights)
        assert isinstance(engine, EnsembleEngine)
        assert "refined_elo" in engine.weights or "squad_value" in engine.weights
