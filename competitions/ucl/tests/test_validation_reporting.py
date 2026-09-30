"""Skipped-validation reporting (R1) and UNVERIFIED surfacing (R2)."""
from __future__ import annotations

import pytest

from competitions.ucl.src.validation_suite import ValidationResult, ValidationSuite


class _ExplodingEngine:
    """Engine whose evaluate() always throws — every check must be skipped."""

    def evaluate(self, match, context):
        raise RuntimeError("engine offline")


class TestSkippedReporting:
    """A skipped check must be counted, logged and exposed as report['skipped']."""

    def test_run_all_reports_zero_skipped_when_healthy(self, seasons_data):
        from competitions.ucl.tests.test_validation_suite import _MockEngine

        report = ValidationSuite(_MockEngine(), seasons_data).run_all()
        assert report["skipped"] == 0

    def test_run_all_reports_skipped_when_engine_throws(self, seasons_data, caplog):
        with caplog.at_level("WARNING"):
            report = ValidationSuite(_ExplodingEngine(), seasons_data).run_all()
        assert report["skipped"] > 0
        assert any("validation check skipped" in r.message for r in caplog.records)

    def test_tier_results_always_expose_skipped(self, seasons_data):
        from competitions.ucl.tests.test_validation_suite import _MockEngine

        suite = ValidationSuite(_MockEngine(), seasons_data)
        for result in (
            suite.run_tier_1_cross_tournament(),
            suite.run_tier_2_walk_forward(window=2),
        ):
            assert isinstance(result, ValidationResult)
            assert result.skipped == 0

    def test_early_returns_include_skipped(self):
        """Empty/degenerate inputs still return the key."""
        suite = ValidationSuite(_ExplodingEngine(), {})
        assert suite.run_tier_1_cross_tournament().skipped == 0
        assert suite.run_tier_2_walk_forward(window=3).skipped == 0
        assert suite.run_tier_3_replay([]).skipped == 0
        assert suite.run_all()["skipped"] == 0

    def test_replay_reports_skipped(self, seasons_data, caplog):
        matchdays = [
            [m for m in seasons_data["Y2023"]["matches"] if m.get("is_draw")][:1]
        ]
        with caplog.at_level("WARNING"):
            report = ValidationSuite(
                _ExplodingEngine(), seasons_data,
            ).run_all(replay_matchdays=matchdays)
        assert report["skipped"] > 0


class TestUnverifiedSurfacing:
    """The UNVERIFIED gate warning must be emitted, not silently discarded."""

    def test_unverified_warning_printed_and_recorded(self, monkeypatch, capsys):
        import competitions.ucl.main as cli
        import competitions.ucl.src.gate as gate

        monkeypatch.setattr(cli, "_parse_args", lambda argv=None: type(
            "A", (), {"mode": "live", "once": True, "n_iterations": 1, "seed": 1},
        )())
        monkeypatch.setattr("web.common.get_data_provider",
                            lambda *a, **k: type("P", (), {})())
        monkeypatch.setattr(cli, "load_dotenv", lambda *a, **k: None)
        monkeypatch.setattr("competitions.ucl.src.pipeline.fetch_live_data",
                            lambda *a, **k: {
                                "status": "ok", "n_raw": 1, "n_updated": 1,
                                "report": {}, "per_season": {},
                            })
        monkeypatch.setattr("competitions.ucl.src.orchestrator.run_compute_all",
                            lambda *a, **k: {"mode": "test", "n_teams": 8})
        monkeypatch.setenv("FOOTBALL_LIVE", "1")
        monkeypatch.setattr(gate, "load_gate_inputs", lambda: ([], {}))
        monkeypatch.setattr(gate, "evaluate_matches", lambda *a, **k: {
            "verdict": {"status": "UNVERIFIED", "reasons": ["too few matches"]},
        })

        assert cli.main([]) == 0
        out = capsys.readouterr()
        assert "UNVERIFIED" in out.err
        assert "too few matches" in out.err
        assert "Unverified" in out.out
