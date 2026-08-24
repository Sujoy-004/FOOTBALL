"""Exchange 2: World Cup must consume the canonical core signal system.

Locks down the migration away from the local _CacheSignal (hardcoded
draw=0.25) and duplicated _EloSignal, without renaming the historical
"elo" signal identity that weights/calibration/UI depend on.
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest

ENGINE_PATH = (
    Path(__file__).resolve().parent.parent
    / "competitions" / "worldcup" / "src" / "engine.py"
)


class TestNoHardcodedFallbacks:
    def test_engine_has_no_hardcoded_draw_constant(self):
        src = ENGINE_PATH.read_text(encoding="utf-8")
        assert "0.25" not in src, "WC engine regressed to hardcoded draw=0.25"

    def test_engine_no_local_duplicate_signal_classes(self):
        src = ENGINE_PATH.read_text(encoding="utf-8")
        assert "_EloSignal" not in src
        assert "_CacheSignal" not in src


from football_core.signals.cached import CachedProbabilitySignal  # noqa: E402
from football_core.signals.refined_elo import RefinedEloSignal  # noqa: E402
from football_core.signal import PredictionContext  # noqa: E402


def _ctx(elo=None):
    return PredictionContext(fixtures=[], elo_ratings=elo or {}, played_results=[])


MATCH = {"match_id": "M1", "team_a": "A", "team_b": "B"}


class TestCachedProbabilitySignal:
    def test_uses_cached_draw_when_present(self):
        sig = CachedProbabilitySignal("squad_value", {"M1": {
            "probability": 0.55, "draw_probability": 0.30, "available": True}})
        out = sig.predict(MATCH, _ctx())
        assert abs(out.home_prob - 0.55) < 1e-12
        assert abs(out.draw_prob - 0.30) < 1e-12
        assert abs(out.home_prob + out.draw_prob + out.away_prob - 1.0) < 1e-12

    def test_default_draw_is_uniform_third_not_quarter(self):
        sig = CachedProbabilitySignal("market_odds", {"M1": {
            "probability": 0.4, "available": True}})
        out = sig.predict(MATCH, _ctx())
        assert abs(out.draw_prob - 1.0 / 3.0) < 1e-9

    def test_clamp_keeps_distribution_valid_for_heavy_favourite(self):
        sig = CachedProbabilitySignal("market_odds", {"M1": {"probability": 0.9}})
        out = sig.predict(MATCH, _ctx())
        assert out.away_prob >= 0.0
        assert out.home_prob + out.draw_prob + out.away_prob <= 1.0 + 1e-9

    def test_unavailable_entry_returns_uniform_without_error(self, caplog):
        sig = CachedProbabilitySignal("rest_days", {"M1": {
            "probability": None, "available": False, "reason": "no_date_info"}})
        import logging
        with caplog.at_level(logging.ERROR):
            out = sig.predict(MATCH, _ctx())
        assert (out.home_prob, out.draw_prob, out.away_prob) == (1 / 3, 1 / 3, 1 / 3)
        assert not any(rec.levelname == "ERROR" for rec in caplog.records)

    def test_none_probability_entry_uniform_no_exception(self):
        """Regression: rest_days caches carry probability:null which used to
        raise TypeError inside the old WC _CacheSignal."""
        sig = CachedProbabilitySignal("rest_days", {"M1": {"probability": None}})
        out = sig.predict(MATCH, _ctx())
        assert out.away_prob == pytest.approx(1 / 3)

    def test_missing_match_uniform(self):
        sig = CachedProbabilitySignal("rolling_form", {})
        out = sig.predict(MATCH, _ctx())
        assert (out.home_prob, out.away_prob) == (1 / 3, 1 / 3)


class TestEloIdentityPreserved:
    def test_name_override(self):
        assert RefinedEloSignal(name="elo").name == "elo"
        assert RefinedEloSignal().name == "refined_elo"

    def test_math_matches_historical_wc_elo_signal(self):
        """Fuzz equivalence against the deleted WC _EloSignal formula."""
        from football_core.elo import expected_score

        def old_formula(home, away):
            hp = expected_score(home, away, home_advantage=100)
            dp = max(0.0, 1.0 - abs(hp - 0.5) * 2.0) * 0.35
            return hp, dp

        rng = random.Random(7)
        for _ in range(50):
            h, a = rng.uniform(1200, 2100), rng.uniform(1200, 2100)
            ctx = _ctx({"A": h, "B": a})
            out = RefinedEloSignal(name="elo").predict(MATCH, ctx)
            hp, dp = old_formula(h, a)
            assert out.home_prob == pytest.approx(hp, abs=1e-12)
            assert out.draw_prob == pytest.approx(dp, abs=1e-12)
            assert out.away_prob == pytest.approx(1.0 - hp - dp, abs=1e-12)


class TestWCEngineIntegration:
    def _build(self, caches):
        from competitions.worldcup.src.engine import build_signal_engine
        return build_signal_engine(**caches)

    def test_weight_names_preserve_elo_identity(self):
        engine = self._build({
            "odds_cache": {"matches": {}}, "rolling_form_cache": {"matches": {}},
            "squad_value_cache": {"matches": {}}, "rest_days_cache": {"matches": {}},
        })
        assert set(engine.weights.keys()) == {
            "elo", "market_odds", "rolling_form", "squad_value", "rest_days"}

    def test_blend_uses_cache_draw_not_constant(self):
        engine = self._build({
            "odds_cache": {"matches": {}},
            "rolling_form_cache": {"matches": {}},
            "squad_value_cache": {"matches": {"M1": {
                "probability": 0.6, "draw_probability": 0.28, "available": True}}},
            "rest_days_cache": {"matches": {}},
        })
        bp = engine.evaluate(MATCH, _ctx())
        # squad_value contributes its own draw estimate into the blend
        sd = bp.signal_breakdown["squad_value"]
        assert sd["draw"] == pytest.approx(0.28, abs=1e-3)
        # rest_days unavailable -> uniform thirds contribution, no crash
        rd = bp.signal_breakdown["rest_days"]
        assert rd["home"] == pytest.approx(1 / 3, abs=1e-3)

    def test_rest_days_null_entries_no_error_spam(self, caplog):
        import logging
        engine = self._build({
            "odds_cache": {"matches": {}}, "rolling_form_cache": {"matches": {}},
            "squad_value_cache": {"matches": {}},
            "rest_days_cache": {"matches": {"M1": {"probability": None}}},
        })
        with caplog.at_level(logging.ERROR):
            engine.evaluate(MATCH, _ctx())
        assert not any(r.levelname == "ERROR" for r in caplog.records)


class TestOddsWriterCarriesDraw:
    def test_parse_odds_response_includes_draw_probability(self):
        from football_core.predictors.odds import parse_odds_response
        event = {
            "id": 1, "status": "scheduled",
            "home_team": "A", "away_team": "B",
            "group_name": "Group A", "round_number": 1,
            "odds_home": 2.0, "odds_draw": 3.5, "odds_away": 4.0,
        }
        alias_lookup = {"a": "A", "b": "B"}
        groups = {"A": {"matches": [
            {"match_id": "GS_A_01", "team_a": "A", "team_b": "B"}]}}
        result = parse_odds_response([event], alias_lookup, groups)
        entry = result["GS_A_01"]
        assert entry["available"] is True
        assert "draw_probability" in entry
        assert 0.0 < entry["draw_probability"] < 1.0
        assert entry["probability"] + entry["draw_probability"] < 1.0
