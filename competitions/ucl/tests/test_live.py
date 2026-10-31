"""Tests for live mode — provider fetch + played_matches injection."""

from __future__ import annotations

from competitions.ucl.src.simulation import run_monte_carlo


class TestLiveMode:
    """Tests for live mode data conversion and injection."""

    def test_live_provider_load(self, monkeypatch):
        """LiveMatchResultProvider.load() fetches matches and converts to played_matches."""
        from competitions.ucl.src.result_provider import LiveMatchResultProvider

        mock_results = [
            {"team_a": "Barcelona", "team_b": "Man City",
             "home_score": 4, "away_score": 0,
             "winner": "Barcelona", "is_draw": False,
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

        provider = LiveMatchResultProvider("dummy_key", {}, {})
        result = provider.load()
        assert ("Barcelona", "Man City") in result
        assert result[("Barcelona", "Man City")] == (4, 0)
        assert ("Real Madrid", "PSG") in result
        assert result[("Real Madrid", "PSG")] == (1, 1)

    def test_live_mode_integration(
        self, monkeypatch, sample_fixture_schedule, sample_elo_dict,
    ):
        """Live mode fetching + injecting into MC produces valid results."""
        from competitions.ucl.src.result_provider import convert_live_matches

        mock_live_results = [
            {"team_a": "Barcelona", "team_b": "Man City",
             "home_score": 3, "away_score": 0,
             "winner": "Barcelona", "is_draw": False,
             "match_id": "MD01_01", "completed_at": "2025-09-17"},
        ]

        def mock_fetch(*args, **kwargs):
            return mock_live_results

        monkeypatch.setattr(
            "competitions.ucl.src.fetcher.fetch_ucl_matches",
            mock_fetch,
        )

        played_matches = convert_live_matches(mock_live_results)
        result = run_monte_carlo(
            sample_fixture_schedule, sample_elo_dict,
            n_iterations=5, seed=42,
            played_matches=played_matches,
        )
        assert "teams" in result
        assert len(result["teams"]) == 36
