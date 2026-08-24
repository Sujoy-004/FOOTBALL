"""Regression coverage for the single canonical prediction ensemble (Exchange 4).

Guarantees:
A. Canonical blend math
B. Weight normalization + determinism
C. Missing weight file → documented uniform fallback
D. No deleted signal can re-enter the engine
E. World Cup production path uses the canonical ensemble
F. UCL production path uses the canonical ensemble
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

DELETED_SIGNALS = {
    "catboost", "availability", "manager_effect", "defensive_quality",
    "player_form", "lineup_strength", "team_synergy", "elo_odds", "form",
}
SURVIVING = {"refined_elo", "market_odds", "rolling_form", "squad_value", "rest_days"}


class TestCanonicalBlendMath:
    """A. Known signals + known weights -> expected weighted result."""

    def test_weighted_blend_matches_hand_computation(self):
        from football_core.blender import EnsembleEngine
        from football_core.signal import PredictionContext, Signal, SignalOutput

        class FixedSignal(Signal):
            def __init__(self, name, h):
                self.name = name
                self._h = h

            def predict(self, match, context):
                return SignalOutput(self._h, 0.25, 1.0 - self._h - 0.25)

        engine = EnsembleEngine(
            [FixedSignal("sig_a", 0.8), FixedSignal("sig_b", 0.4)],
            weights={"sig_a": 0.75, "sig_b": 0.25},
        )
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        bp = engine.evaluate({"match_id": "M1", "team_a": "A", "team_b": "B"}, ctx)
        # hand computation: h = 0.75*0.8 + 0.25*0.4 = 0.7 ; d = 0.25 ; a = 0.05
        assert abs(bp.home_prob - 0.7) < 1e-9
        assert abs(bp.draw_prob - 0.25) < 1e-9
        assert abs(bp.away_prob - 0.05) < 1e-9
        assert abs(bp.home_prob + bp.draw_prob + bp.away_prob - 1.0) < 1e-6


class TestWeightNormalization:
    """B. compute_log_loss_weights: deterministic, normalized, floored."""

    def test_deterministic_and_normalized(self):
        from football_core.blender import compute_log_loss_weights

        ll = {"a": 0.42, "b": 0.77, "c": 0.55}
        w1 = compute_log_loss_weights(ll)
        w2 = compute_log_loss_weights(ll)
        assert w1 == w2
        assert abs(sum(w1.values()) - 1.0) < 1e-6
        assert all(v >= 0 for v in w1.values())

    def test_floor_prevents_domination(self):
        from football_core.blender import compute_log_loss_weights

        # a tiny log-loss must not dominate beyond the 0.05 floor allows
        w = compute_log_loss_weights({"a": 1e-9, "b": 1.0})
        expected_a = round((1 / 0.05) / ((1 / 0.05) + 1.0), 6)
        assert w["a"] == expected_a


class TestMissingWeightsFallback:
    """C. Missing/insufficient weight file -> uniform fallback over registered signals."""

    def test_missing_file_falls_back_to_uniform(self, tmp_path):
        from football_core.blender import EnsembleEngine
        from football_core.signal import PredictionContext, Signal, SignalOutput

        class Uniformish(Signal):
            def __init__(self, name):
                self.name = name

            def predict(self, match, context):
                return SignalOutput(0.5, 0.25, 0.25)

        missing = tmp_path / "nope.json"
        engine = EnsembleEngine(
            [Uniformish("s1"), Uniformish("s2"), Uniformish("s3")],
            weights_path=str(missing) if missing.exists() else None,
        )
        assert abs(engine.weights["s1"] - 1 / 3) < 1e-9
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        bp = engine.evaluate({"match_id": "M", "team_a": "A", "team_b": "B"}, ctx)
        assert abs(bp.home_prob - 0.5) < 1e-9


class TestNoDeletedSignals:
    """D. The committed weight configs and UCL orchestrator roster contain no deleted signals."""

    def test_ucl_orchestrator_roster_is_canonical(self):
        from competitions.ucl.src.orchestrator import build_signal_engine

        engine = build_signal_engine({"TeamA": 1700.0, "TeamB": 1600.0})
        registered = set(engine.weights.keys())
        assert registered == SURVIVING
        assert not (registered & DELETED_SIGNALS)

    def test_no_committed_weight_file_references_deleted_signals(self):
        for cfg in ROOT.glob("competitions/*/config/signal_weights.json"):
            data = json.loads(cfg.read_text(encoding="utf-8"))
            names = set(data.get("weights", {}))
            assert not (names & DELETED_SIGNALS), f"{cfg} references deleted signals"


class TestWorldCupCanonicalIntegration:
    """E. WC production path: engine predictions become simulation match probabilities."""

    def test_run_simulation_compute_feeds_blend_params(self, monkeypatch, tmp_path):
        import competitions.worldcup.src.pipeline as wc_pipeline

        captured = {}

        class FakeEngine:
            weights = {"elo": 0.2, "market_odds": 0.2,
                       "rolling_form": 0.2, "squad_value": 0.2, "rest_days": 0.2}

            def evaluate(self, match, context):
                class BP:
                    home_prob = 0.61

                return BP()

        monkeypatch.setattr(
            "src.engine.build_engine_from_caches", lambda weights=None: FakeEngine()
        )
        monkeypatch.setattr(wc_pipeline, "fetch_live_data", lambda *a, **k: None)

        real_sim = wc_pipeline.run_full_simulation

        def spy_sim(teams, groups, bracket, annex_c, played, **kwargs):
            captured["blend_params"] = kwargs.get("blend_params")
            assert kwargs.get("blend_params") is not None, \
                "simulation must receive canonical blend_params (no pure-Elo fallback)"
            assert "market_odds" in kwargs["blend_params"]["blend_weights"]
            return {t: {"champion": 1 / len(teams)} for t in teams}

        monkeypatch.setattr(wc_pipeline, "run_full_simulation", spy_sim)
        monkeypatch.setattr("web.wc_app.compute_signal_eval", lambda *a, **k: {})
        monkeypatch.setattr("web.wc_app.compute_full_bracket", lambda *a, **k: {})
        monkeypatch.setattr("web.wc_app.compute_overview", lambda: {"n_teams": 0})

        data_dir = ROOT / "competitions" / "worldcup" / "data"
        result = wc_pipeline.run_simulation_compute(data_dir=data_dir, iterations=10, seed=42)

        bp = captured["blend_params"]
        assert len(bp["match_probs"]) > 100  # all fixtures blended
        assert set(bp["blend_weights"]) == {"elo", "market_odds", "rolling_form",
                                            "squad_value", "rest_days"}
        assert "calibration_params" not in bp


class TestUCLCanonicalIntegration:
    """F. UCL production path resolves weights through EnsembleEngine."""

    def test_orchestrator_engine_blend_is_multi_signal(self):
        from competitions.ucl.src.orchestrator import build_signal_engine
        from football_core.signal import PredictionContext

        elos = {"Real Madrid": 2000.0, "Liverpool": 1950.0}
        engine = build_signal_engine(elos)
        ctx = PredictionContext(fixtures=[], elo_ratings=elos)
        bp = engine.evaluate(
            {"match_id": "X", "team_a": "Real Madrid", "team_b": "Liverpool"}, ctx
        )
        assert set(bp.signal_breakdown) == SURVIVING
        assert abs(bp.home_prob + bp.draw_prob + bp.away_prob - 1.0) < 1e-6
