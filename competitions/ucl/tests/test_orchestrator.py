"""Tests for simulation mode orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from football_core.constants import DEFAULT_ELO


class TestResolvePlayedMatches:
    """Tests for orchestrator.resolve_played_matches()."""

    def test_simulate_mode_returns_none(self):
        """Default simulate mode returns None played_matches."""
        from competitions.ucl.src.orchestrator import resolve_played_matches

        class FakeArgs:
            mode = "simulate"
            replay_data = None
            api_key = None

        result = resolve_played_matches(FakeArgs(), "/data", None)
        assert result is None

    def test_replay_mode_without_data_exits(self):
        """Replay mode without --replay-data exits with error."""
        from competitions.ucl.src.orchestrator import resolve_played_matches

        class FakeArgs:
            mode = "replay"
            replay_data = None
            api_key = None

        with pytest.raises(SystemExit):
            resolve_played_matches(FakeArgs(), "/data", None)

    def test_live_mode_without_key_exits(self, monkeypatch):
        """Live mode without API key exits with error."""
        monkeypatch.delenv("BSD_API_KEY", raising=False)
        from competitions.ucl.src.orchestrator import resolve_played_matches

        class FakeArgs:
            mode = "live"
            replay_data = None
            api_key = None

        with pytest.raises(SystemExit) as exc:
            resolve_played_matches(FakeArgs(), "/data", None)
        assert exc.value.code == 1


# ── Exchange 10: real per-team ClubElo coverage in the signals payload ──────


def _shell_data_dir(tmp_path):
    """A 2026/27 season store with 144 draw fixtures and ZERO played results.

    Mirrors the live state that reaches the no-results shell branch of
    ``run_deterministic_compute``: active pointer at 2026/27, a season store
    holding the authoritative draw fixtures, and an empty results ledger. The
    root 2025/26 stores stay present so the rolling_form historical path is
    exercised (it must NOT gain ClubElo coverage keys).
    """
    import shutil

    from competitions.ucl.src.seasons import set_current_season

    repo_data = Path(__file__).resolve().parents[1] / "data"
    dp = tmp_path / "data"
    shutil.copytree(repo_data, dp)
    seasons = dp / "seasons"
    if seasons.is_dir():
        shutil.rmtree(seasons)
    sd = seasons / "2026_27"
    sd.mkdir(parents=True)
    shutil.copy(repo_data / "fixtures.json", sd / "fixtures.json")
    (sd / "results.json").write_text(json.dumps({"matches": []}), encoding="utf-8")
    set_current_season(dp, "2026/27", basis="draw", provider="test")
    return dp


def _season_team_names(dp) -> list[str]:
    """Team names for the shell season store's fixture schedule (expect 36)."""
    from competitions.ucl.src.provider import RepoFixtureProvider

    provider = RepoFixtureProvider(
        fixtures_path=str(dp / "seasons" / "2026_27" / "fixtures.json")
    ).load()
    return [t.name for t in provider.teams]


class TestShellRefinedEloCoverage:
    """No-results shell branch: refined_elo coverage is MEASURED, not hardcoded."""

    def test_live_fetch_2026_27_reports_measured_22_of_36(self, tmp_path, monkeypatch):
        """Fetch path: 22 real ClubElo ratings + 14x1500.0 => 22/36 carrier.

        Regression for the old hardcoded ``n_matches=144, available=144,
        available_pct=100.0`` which implied full ClubElo coverage.
        """
        import competitions.ucl.src.orchestrator as orch

        dp = _shell_data_dir(tmp_path)
        names = _season_team_names(dp)
        assert len(names) == 36, "draw fixtures must describe 36 teams"

        # Simulate a SUCCESSFUL live fetch: every team present, unresolved
        # clubs at the exact DEFAULT_ELO placeholder (fetch_team_elos fills
        # every requested team; see football_core/elo_fetcher.py).
        elo_ratings = {t: 1520.0 + i for i, t in enumerate(names[:22])}
        elo_ratings.update({t: float(DEFAULT_ELO) for t in names[22:]})
        monkeypatch.setattr(orch, "_resolve_elo_ratings", lambda _n: elo_ratings)

        result = orch.run_deterministic_compute(str(dp), bsd_api_key="")
        re = result["signals"]["refined_elo"]

        # Existing per-match availability semantics are untouched.
        assert re["n_matches"] == 144
        assert re["available"] == 144
        assert re["available_pct"] == 100.0
        # NEW honest per-team coverage metadata.
        assert re["coverage"] == 22
        assert re["coverage_total"] == 36
        assert re["coverage_pct"] == 61.1
        assert re["provenance"] == "clubelo"
        # rolling_form keys off HISTORICAL RESULTS, not Elo rating coverage:
        # per-team ClubElo coverage does not apply to it (documented decision).
        assert "coverage" not in result["signals"]["rolling_form"]
        assert "provenance" not in result["signals"]["rolling_form"]

    def test_coefficient_fallback_reports_zero_clubelo_coverage(
        self, tmp_path, monkeypatch
    ):
        """Offline/snapshot fallback => coefficient values are NOT ClubElo."""
        import competitions.ucl.src.orchestrator as orch

        dp = _shell_data_dir(tmp_path)
        monkeypatch.setattr(orch, "_resolve_elo_ratings", lambda _n: {})

        result = orch.run_deterministic_compute(str(dp), bsd_api_key="")
        re = result["signals"]["refined_elo"]

        assert re["n_matches"] == 144
        assert re["available"] == 144
        assert re["available_pct"] == 100.0
        assert re["coverage"] == 0
        assert re["coverage_total"] == 36
        assert re["coverage_pct"] == 0.0
        assert re["provenance"] == "coefficient_derived"
        # The coefficient-derived values (1400-1800 band) must NOT be counted.
        assert all(1400.0 <= v <= 1800.0 for v in result["elo_ratings"].values())
        assert any(
            b.get("step") == "Elo fallback (coefficients)" for b in result["boot"]
        )
        # When provenance is coefficient_derived the UI must not present
        # ClubElo coverage — a 0-coverage entry is the honest signal.
        assert re["coverage"] == 0


class TestCompletedSeasonSignalCoverage:
    """pipeline.compute_signal_eval: refined_elo carries the same 4 keys."""

    def test_completed_season_36_of_36_clubelo(self):
        from competitions.ucl.src.orchestrator import build_signal_engine
        from competitions.ucl.src.pipeline import compute_signal_eval

        repo_data = Path(__file__).resolve().parents[1] / "data"
        from competitions.ucl.src.provider import RepoFixtureProvider

        provider = RepoFixtureProvider(
            fixtures_path=str(repo_data / "fixtures.json")
        ).load()
        names = [t.name for t in provider.teams]
        assert len(names) == 36

        elo_ratings = {t: 1510.0 + i for i, t in enumerate(names)}
        engine = build_signal_engine(elo_ratings)
        results = [
            {"team_a": names[0], "team_b": names[1],
             "home_score": 2, "away_score": 0, "match_id": "MD01_01"},
            {"team_a": names[2], "team_b": names[3],
             "home_score": 1, "away_score": 1, "match_id": "MD01_02"},
        ]
        stats = compute_signal_eval(results, engine, elo_ratings, elo_provenance="clubelo")
        re = stats["refined_elo"]

        assert re["coverage"] == 36
        assert re["coverage_total"] == 36
        assert re["coverage_pct"] == 100.0
        assert re["provenance"] == "clubelo"
        # Existing per-match semantics + accuracy keys untouched.
        assert re["n_matches"] == 2
        assert re["available"] == 2
        assert re["available_pct"] == 100.0
        assert "accuracy" in re and "brier" in re

    def test_compute_signal_eval_coefficient_provenance_not_clubelo(self):
        """A coefficient-derived ratings dict must not be presented as ClubElo."""
        from competitions.ucl.src.orchestrator import build_signal_engine
        from competitions.ucl.src.pipeline import compute_signal_eval

        names = ["Team A", "Team B"]
        # Coefficient band values — none are ClubElo data.
        elo_ratings = {names[0]: 1450.0, names[1]: 1740.0}
        engine = build_signal_engine(elo_ratings)
        results = [
            {"team_a": names[0], "team_b": names[1],
             "home_score": 1, "away_score": 0, "match_id": "MD01_01"},
        ]
        stats = compute_signal_eval(
            results, engine, elo_ratings, elo_provenance="coefficient_derived"
        )
        re = stats["refined_elo"]
        assert re["coverage"] == 0
        assert re["coverage_total"] == 2
        assert re["coverage_pct"] == 0.0
        assert re["provenance"] == "coefficient_derived"


class TestEloCoverageBoundary:
    """The exact DEFAULT_ELO (1500.0) boundary and provenance edge cases."""

    def test_exact_placeholder_excluded_but_real_values_near_it_counted(self):
        from competitions.ucl.src.pipeline import compute_elo_coverage

        names = ["A", "B", "C", "D", "E"]
        ratings = {
            "A": 1499.5,          # real value below the placeholder
            "B": float(DEFAULT_ELO),  # exact placeholder => NOT covered
            "C": 1500.5,          # real value above the placeholder
            "D": float(DEFAULT_ELO),  # exact placeholder => NOT covered
            # "E" missing entirely => NOT covered (never default-filled)
        }
        out = compute_elo_coverage(names, ratings, "clubelo")
        assert out["coverage"] == 2
        assert out["coverage_total"] == 5
        assert out["coverage_pct"] == 40.0
        assert out["provenance"] == "clubelo"

    def test_partial_coverage_never_defaults_missing_team(self):
        from competitions.ucl.src.pipeline import compute_elo_coverage

        ratings = {"A": 1520.0, "B": float(DEFAULT_ELO)}
        out = compute_elo_coverage(["A", "B", "C"], ratings, "clubelo")
        assert out["coverage"] == 1
        assert out["coverage_total"] == 3
        assert out["provenance"] == "clubelo"

    def test_unavailable_provenance_zero_coverage(self):
        from competitions.ucl.src.pipeline import compute_elo_coverage

        out = compute_elo_coverage(["A", "B"], {}, "unavailable")
        assert out["coverage"] == 0
        assert out["coverage_total"] == 2
        assert out["coverage_pct"] == 0.0
        assert out["provenance"] == "unavailable"

    def test_empty_team_names_is_safe(self):
        from competitions.ucl.src.pipeline import compute_elo_coverage

        out = compute_elo_coverage([], {}, "clubelo")
        assert out == {
            "coverage": 0, "coverage_total": 0, "coverage_pct": 0.0,
            "provenance": "clubelo",
        }
