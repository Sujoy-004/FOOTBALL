"""Tests for live mode — BSD fetch + played_matches injection."""

from __future__ import annotations

import pytest

from competitions.ucl.src.simulation import run_monte_carlo


class TestLiveMode:
    """Tests for live mode data conversion and injection."""

    def test_bsd_provider_load(self, monkeypatch):
        """BSDMatchResultProvider.load() fetches BSD and converts to played_matches."""
        from competitions.ucl.src.result_provider import BSDMatchResultProvider

        mock_results = [
            {"team_a": "Man City", "team_b": "Bayern",
             "home_score": 4, "away_score": 0,
             "winner": "Man City", "is_draw": False,
             "match_id": "MD01_01", "completed_at": "2025-09-17"},
            {"team_a": "Real Madrid", "team_b": "PSG",
             "home_score": 1, "away_score": 1,
             "winner": None, "is_draw": True,
             "match_id": "MD01_02", "completed_at": "2025-09-17"},
        ]

        def mock_fetch(*args, **kwargs):
            return mock_results

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_ucl_matches",
            mock_fetch,
        )

        provider = BSDMatchResultProvider("dummy_key", {}, {})
        result = provider.load()
        assert ("Man City", "Bayern") in result
        assert result[("Man City", "Bayern")] == (4, 0)
        assert ("Real Madrid", "PSG") in result
        assert result[("Real Madrid", "PSG")] == (1, 1)

    def test_live_mode_integration(
        self, monkeypatch, sample_fixture_schedule, sample_elo_dict,
    ):
        """Live mode fetching BSD + injecting into MC produces valid results."""
        from competitions.ucl.src.result_provider import convert_bsd_matches

        mock_bsd_results = [
            {"team_a": "Man City", "team_b": "Bayern",
             "home_score": 3, "away_score": 0,
             "winner": "Man City", "is_draw": False,
             "match_id": "MD01_01", "completed_at": "2025-09-17"},
        ]

        def mock_fetch(*args, **kwargs):
            return mock_bsd_results

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_ucl_matches",
            mock_fetch,
        )

        played_matches = convert_bsd_matches(mock_bsd_results)
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=5, seed=42,
            played_matches=played_matches,
        )
        assert "teams" in result
        assert len(result["teams"]) == 36
