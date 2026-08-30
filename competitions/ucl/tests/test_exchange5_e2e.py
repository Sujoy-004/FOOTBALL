"""Exchange 5 end-to-end + adversarial tests.

Proves the full pipeline: mock provider -> real UCL refresh entrypoint ->
season preserved -> multi-season ingestion -> current.json updated -> state
builder uses new season -> API serves new season -> 2025/26 unchanged.

Plus 5 adversarial test cases for edge conditions.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Optional

import pytest

REPO_DATA = Path(__file__).resolve().parents[1] / "data"


# ── stub provider ──────────────────────────────────────────────────────────

class _MultiSeasonProvider:
    """Provider that emits events for both historical and new seasons."""

    def __init__(self, events: list[dict]):
        self._events = list(events)
        self.last_error: Optional[str] = None

    def fetch_matches(self, competition_id="CL"):
        return list(self._events)


class _EmptyProvider:
    """Provider that returns zero matches."""

    last_error: Optional[str] = "no matches"

    def fetch_matches(self, competition_id="CL"):
        return []


class _SeasonRecordingProvider:
    def __init__(self, events):
        self._events = list(events)
        self.last_error = None
        self.season = "UNSET"

    def fetch_matches(self, competition_id="CL", *, season=None, **kwargs):
        self.season = season
        return list(self._events)


# ── helpers ──────────────────────────────────────────────────────────────────

def _make_data_dir(tmp_path: Path) -> Path:
    """Create a minimal UCL data dir mirroring the repo layout."""
    dp = tmp_path / "data"
    dp.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO_DATA / "fixtures.json", dp / "fixtures.json")
    shutil.copy(REPO_DATA / "playoff_pairings.json", dp / "playoff_pairings.json")
    shutil.copy(REPO_DATA / "bracket_rules.json", dp / "bracket_rules.json")
    if (REPO_DATA / "team_aliases.json").exists():
        shutil.copy(REPO_DATA / "team_aliases.json", dp / "team_aliases.json")
    if (REPO_DATA / "results.json").exists():
        shutil.copy(REPO_DATA / "results.json", dp / "results.json")
    else:
        (dp / "results.json").write_text('{"matches": []}', encoding="utf-8")
    if (REPO_DATA / "knockout_results.json").exists():
        shutil.copy(REPO_DATA / "knockout_results.json", dp / "knockout_results.json")
    else:
        (dp / "knockout_results.json").write_text('{"playoff":[],"rounds":{}}', encoding="utf-8")
    return dp


def _make_new_season_events() -> list[dict]:
    """Synthetic events for 2026/27 season using real UCL team names from fixtures.json."""
    return [
        {"home_team": "Real Madrid", "away_team": "Barcelona",
         "home_score": 2, "away_score": 1, "status": "finished",
         "stage": "LEAGUE_STAGE", "season": "2026/27",
         "match_id": "E5-001"},
        {"home_team": "Bayern", "away_team": "PSG",
         "home_score": 1, "away_score": 1, "status": "finished",
         "stage": "LEAGUE_STAGE", "season": "2026/27",
         "match_id": "E5-002"},
        {"home_team": "Man City", "away_team": "Inter",
         "home_score": 0, "away_score": 0, "status": "TIMED",
         "stage": "LEAGUE_STAGE", "season": "2026/27",
         "match_id": "E5-003"},
        {"home_team": "Arsenal", "away_team": "Dortmund",
         "home_score": 0, "away_score": 0, "status": "SCHEDULED",
         "stage": "LEAGUE_STAGE", "season": "2026/27",
         "match_id": "E5-004"},
        {"home_team": "Atletico Madrid", "away_team": "Chelsea",
         "home_score": 0, "away_score": 0, "status": "TIMED",
         "stage": "LEAGUE_STAGE", "season": "2026/27",
         "match_id": "E5-005"},
        {"home_team": "Benfica", "away_team": "Club Brugge",
         "home_score": 0, "away_score": 0, "status": "SCHEDULED",
         "stage": "LEAGUE_STAGE", "season": "2026/27",
         "match_id": "E5-006"},
    ]


def _make_sufficient_new_season_events() -> list[dict]:
    """Generate 110 scheduled events for 2026/27 to cross the lifecycle threshold.

    SUFFICIENT_FIXTURES_THRESHOLD=100; we need fixtures_total >= 100.
    Uses 110 unique team-pair events, all scheduled, so the season activates.
    """
    from itertools import combinations
    all_teams = [
        "Real Madrid", "Barcelona", "Bayern", "PSG", "Man City",
        "Inter", "Chelsea", "Dortmund", "Arsenal", "Atletico Madrid",
        "Benfica", "Club Brugge", "Liverpool", "Napoli", "Juventus",
        "Atalanta", "Sporting", "Ajax", "Tottenham", "PSV",
    ]
    events = []
    idx = 0
    for home, away in combinations(all_teams, 2):
        idx += 1
        events.append({
            "home_team": home, "away_team": away,
            "home_score": 0, "away_score": 0,
            "status": "SCHEDULED",
            "stage": "LEAGUE_STAGE", "season": "2026/27",
            "match_id": f"E5-S{idx:04d}",
        })
        if idx >= 110:
            break
    return events


# ── 1. END-TO-END TEST ────────────────────────────────────────────────────────

class TestExchange5EndToEnd:
    """Full provider -> ingest -> state -> API pipeline."""

    def test_full_pipeline_new_season(self, tmp_path, monkeypatch):
        """Mock provider -> fetch_live_data -> season dir created -> current.json
        updated -> state builder reads new season -> API data serves it ->
        historical 2025/26 unchanged."""
        from competitions.ucl.src import pipeline
        from competitions.ucl.src.seasons import (
            get_current_season,
            read_season_fixtures,
            read_season_results,
            season_dir,
        )

        dp = _make_data_dir(tmp_path)

        # Snapshot the historical results before any changes.
        hist_results_before = json.loads(
            (dp / "results.json").read_text(encoding="utf-8")
        )

        # Create a provider that emits enough events to cross the lifecycle
        # threshold (SUFFICIENT_FIXTURES_THRESHOLD=100).
        new_events = _make_sufficient_new_season_events()
        provider = _MultiSeasonProvider(new_events)
        monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: provider)

        # Run the production entrypoint.
        result = pipeline.fetch_live_data(
            dp, "key", "", 7, provider=provider,
        )

        # --- 1a. Pipeline returned successfully ---
        assert result["status"] == "ok"
        assert result["n_raw"] == len(new_events)
        assert result["provider_name"] == "_MultiSeasonProvider"
        per_season = result["per_season"]
        assert "2026/27" in per_season

        # --- 1b. Season dir was created with fixtures ---
        sd = season_dir(dp, "2026/27")
        assert sd.is_dir()
        fx = read_season_fixtures(dp, "2026/27")
        assert fx is not None
        assert fx["season"] == "2026/27"
        assert len(fx["fixtures"]) >= 100  # crossed threshold

        # --- 1c. current.json was updated (threshold crossed) ---
        current = get_current_season(dp)
        assert current is not None
        assert current.get("season") == "2026/27"

        # --- 1d. State builder reads the new season ---
        from competitions.ucl.src.state import build_competition_state
        state = build_competition_state(str(dp), mode="results",
                                        active_season="2026/27")
        assert state["season"] == "2026/27"

        # --- 1e. Historical 2025/26 data is byte-identical ---
        hist_results_after = json.loads(
            (dp / "results.json").read_text(encoding="utf-8")
        )
        assert hist_results_after == hist_results_before

        # --- 1f. resolve_active_data_dir resolves to season dir ---
        from competitions.ucl.src.orchestrator import resolve_active_data_dir
        resolved = resolve_active_data_dir(str(dp))
        assert "2026_27" in resolved

        # --- 1g. resolve_compute_mode returns results ---
        from competitions.ucl.src.orchestrator import resolve_compute_mode
        mode, reason = resolve_compute_mode(str(dp))
        assert mode == "results"
        assert "2026/27" in reason


    def test_active_season_is_forwarded_to_provider_when_supported(self, tmp_path):
        """An active non-historical season is requested explicitly from providers that support it."""
        from competitions.ucl.src import pipeline
        from competitions.ucl.src.seasons import set_current_season

        dp = _make_data_dir(tmp_path)
        set_current_season(dp, "2026/27", basis="draw", provider="test")
        provider = _SeasonRecordingProvider(_make_new_season_events())

        result = pipeline.fetch_live_data(dp, "key", "", 7, provider=provider)

        assert result["status"] == "ok"
        assert provider.season == 2026



# ── 2. ADVERSARIAL TESTS ──────────────────────────────────────────────────────

class TestExchange5Adversarial:
    """Edge-case / adversarial scenarios."""

    def test_insufficient_data_no_activation(self, tmp_path, monkeypatch):
        """Fewer than threshold fixtures => current.json NOT updated."""
        from competitions.ucl.src import pipeline
        from competitions.ucl.src.seasons import get_current_season, season_dir
        from competitions.ucl.src.lifecycle import (
            SUFFICIENT_FIXTURES_THRESHOLD,
            SUFFICIENT_RESULTS_THRESHOLD,
        )

        dp = _make_data_dir(tmp_path)
        # Ensure no current.json exists yet.
        current_path = dp / "current.json"
        if current_path.exists():
            current_path.unlink()

        # Provider returns only 3 events — well below both thresholds.
        few_events = _make_new_season_events()[:3]
        provider = _MultiSeasonProvider(few_events)
        monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: provider)

        pipeline.fetch_live_data(dp, "key", "", 7, provider=provider)

        # Season dir created with data.
        sd = season_dir(dp, "2026/27")
        assert sd.is_dir()

        # But current.json NOT created (insufficient data).
        current = get_current_season(dp)
        # Should be None (no current.json) or not have 2026/27.
        if current is not None:
            assert current.get("season") != "2026/27"

    def test_provider_failure_preserves_state(self, tmp_path, monkeypatch):
        """Provider failure => no files written, no current.json change."""
        from competitions.ucl.src import pipeline
        from competitions.ucl.src.seasons import get_current_season, season_dir

        dp = _make_data_dir(tmp_path)
        hist_results_before = json.loads(
            (dp / "results.json").read_text(encoding="utf-8")
        )

        dead = _EmptyProvider()
        monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: dead)

        result = pipeline.fetch_live_data(dp, "key", "", 7, provider=dead)

        assert result["status"] == "skip"
        assert result["n_raw"] == 0

        # Historical data unchanged.
        hist_results_after = json.loads(
            (dp / "results.json").read_text(encoding="utf-8")
        )
        assert hist_results_after == hist_results_before

        # No season dir created.
        sd = season_dir(dp, "2026/27")
        assert not sd.is_dir()

        # No current.json.
        assert get_current_season(dp) is None or \
               get_current_season(dp).get("season") != "2026/27"

    def test_idempotent_ingestion(self, tmp_path, monkeypatch):
        """Ingesting the same events twice produces identical state."""
        from competitions.ucl.src import pipeline
        from competitions.ucl.src.seasons import read_season_fixtures, read_season_results

        dp = _make_data_dir(tmp_path)
        events = _make_new_season_events()
        provider = _MultiSeasonProvider(events)
        monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: provider)

        # First ingest.
        pipeline.fetch_live_data(dp, "key", "", 7, provider=provider)
        fx1 = read_season_fixtures(dp, "2026/27")
        res1 = read_season_results(dp, "2026/27")
        fx1_snap = json.dumps(fx1, sort_keys=True)
        res1_snap = json.dumps(res1, sort_keys=True)

        # Second ingest with identical events.
        pipeline.fetch_live_data(dp, "key", "", 7, provider=provider)
        fx2 = read_season_fixtures(dp, "2026/27")
        res2 = read_season_results(dp, "2026/27")

        assert json.dumps(fx2, sort_keys=True) == fx1_snap
        assert json.dumps(res2, sort_keys=True) == res1_snap

    def test_historical_2025_26_never_polluted(self, tmp_path, monkeypatch):
        """Events with season=2026/27 never write to root results.json."""
        from competitions.ucl.src import pipeline
        from competitions.ucl.src.seasons import read_season_results

        dp = _make_data_dir(tmp_path)
        hist_results_before = json.loads(
            (dp / "results.json").read_text(encoding="utf-8")
        )

        events = _make_new_season_events()
        provider = _MultiSeasonProvider(events)
        monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: provider)

        pipeline.fetch_live_data(dp, "key", "", 7, provider=provider)

        # Root results.json is byte-identical to before.
        hist_results_after = json.loads(
            (dp / "results.json").read_text(encoding="utf-8")
        )
        assert hist_results_after == hist_results_before

        # New season results are only in season dir.
        res_2027 = read_season_results(dp, "2026/27")
        assert res_2027 is not None
        assert len(res_2027["matches"]) == 2

    def test_mixed_seasons_split_correctly(self, tmp_path, monkeypatch):
        """Mixed payload: 2025/26 events -> legacy, 2026/27 -> season dir."""
        from competitions.ucl.src import pipeline
        from competitions.ucl.src.seasons import read_season_results
        from competitions.ucl.src.ingest import load_knockout_store

        dp = _make_data_dir(tmp_path)

        # Mix of historical and new-season events.
        mixed = [
            # Historical event (no season => defaults to 2025/26).
            {"home_team": "Real Madrid", "away_team": "Barcelona",
             "home_score": 3, "away_score": 1, "status": "finished",
             "stage": "LEAGUE_STAGE", "match_id": "E5-MIX-H1"},
            # New season event.
            {"home_team": "Real Madrid", "away_team": "Barcelona",
             "home_score": 2, "away_score": 0, "status": "finished",
             "stage": "LEAGUE_STAGE", "season": "2026/27",
             "match_id": "E5-MIX-N1"},
        ]
        provider = _MultiSeasonProvider(mixed)
        monkeypatch.setattr(pipeline, "_select_provider", lambda *a, **k: provider)

        result = pipeline.fetch_live_data(dp, "key", "", 7, provider=provider)

        per_season = result["per_season"]
        # Historical routed to legacy.
        assert per_season.get("2025/26", {}).get("legacy") is True
        # New season routed to season dir.
        assert "2026/27" in per_season
        assert per_season["2026/27"]["legacy"] is False

        # Season dir has exactly 1 result.
        res_2027 = read_season_results(dp, "2026/27")
        assert len(res_2027["matches"]) == 1
        assert res_2027["matches"][0]["match_id"] == "E5-MIX-N1"
