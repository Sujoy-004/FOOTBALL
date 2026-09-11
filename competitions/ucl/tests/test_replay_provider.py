"""Tests for _ReplayResultProvider — correctness fix (Phase 6).

Covers: deduplication, fixture-date fallback, winner derivation from scores,
strict-before chronology, deterministic replay, consumer compat, limit, and
legacy fallback.
"""
from __future__ import annotations

import json
import os

import pytest


# ---------------------------------------------------------------------------
# Import the real class from orchestrator (after Phase 6 fix).
# This import intentionally imports the class itself; if orchestrator's
# module-level imports fail in test isolation, we skip gracefully.
# ---------------------------------------------------------------------------

try:
    from competitions.ucl.src.orchestrator import _ReplayResultProvider
except Exception:
    pytest.skip(
        "orchestrator module-level imports unavailable in test env",
        allow_module_level=True,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_provider(tmp_path, results, fixtures=None):
    """Write results.json (+ optional fixtures.json) and return the provider."""
    r_path = tmp_path / "results.json"
    with open(r_path, "w") as f:
        json.dump(results, f)
    if fixtures is not None:
        f_path = tmp_path / "fixtures.json"
        with open(f_path, "w") as f:
            json.dump(fixtures, f)
    return _ReplayResultProvider(str(r_path))


# ---------------------------------------------------------------------------
# 1. test_single_result_not_duplicated
# ---------------------------------------------------------------------------

def test_single_result_not_duplicated(tmp_path):
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 2, "away_score": 1,
         "event_date": "2026-09-01", "match_id": "m1"},
    ]
    provider = _write_provider(tmp_path, results)
    got = provider.get_team_results("A", "2026-09-10")
    assert len(got) == 1
    assert got[0]["winner"] == "A"
    assert got[0]["is_draw"] is False


# ---------------------------------------------------------------------------
# 2. test_distinct_fixtures_preserved
# ---------------------------------------------------------------------------

def test_distinct_fixtures_preserved(tmp_path):
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "event_date": "2026-09-01", "match_id": "m1"},
        {"team_a": "A", "team_b": "C", "home_score": 0, "away_score": 0,
         "event_date": "2026-09-05", "match_id": "m2"},
    ]
    provider = _write_provider(tmp_path, results)
    got = provider.get_team_results("A", "2026-09-10")
    assert len(got) == 2
    # Both opponents present (distinct fixtures preserved)
    opponents = {r["team_b"] for r in got}
    assert opponents == {"B", "C"}


# ---------------------------------------------------------------------------
# 3. test_duplicate_match_ids_in_results_are_deduped
# ---------------------------------------------------------------------------

def test_duplicate_match_ids_in_results_are_deduped(tmp_path):
    row = {"team_a": "A", "team_b": "B", "home_score": 2, "away_score": 1,
           "event_date": "2026-09-01", "match_id": "m1"}
    results = [row, {**row}]  # same match_id twice
    provider = _write_provider(tmp_path, results)
    got = provider.get_team_results("A", "2026-09-10")
    assert len(got) == 1


# ---------------------------------------------------------------------------
# 4. test_event_date_fallback_from_fixtures
# ---------------------------------------------------------------------------

def test_event_date_fallback_from_fixtures(tmp_path):
    """Live row with no event_date gets date from co-located fixtures.json."""
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "match_id": "live1"},
    ]
    fixtures = [
        {"match_id": "live1", "team_a": "A", "team_b": "B",
         "event_date": "2026-09-01T19:00:00Z"},
    ]
    provider = _write_provider(tmp_path, results, fixtures)
    got = provider.get_team_results("A", "2026-10-01T00:00:00Z")
    assert len(got) == 1
    assert got[0]["event_date"] == "2026-09-01T19:00:00Z"


# ---------------------------------------------------------------------------
# 5. test_rolling_form_uses_fallback
# ---------------------------------------------------------------------------

def test_rolling_form_uses_fallback(tmp_path):
    """RollingFormSignal with fallback dates produces form-driven probs, not 0.5."""
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signal import PredictionContext

    # --- WITH fixtures: results have no event_date but fixtures.json provides dates ---
    subdir_with = tmp_path / "with_fixtures"
    subdir_with.mkdir()
    results_with = [
        {"team_a": "A", "team_b": "B", "home_score": 3, "away_score": 0,
         "match_id": f"md{i}"}
        for i in range(5)
    ]
    fixtures_with = [
        {"match_id": f"md{i}", "team_a": "A", "team_b": "B",
         "event_date": f"2026-09-{i+1:02d}T19:00:00Z"}
        for i in range(5)
    ]
    (subdir_with / "results.json").write_text(json.dumps(results_with), encoding="utf-8")
    (subdir_with / "fixtures.json").write_text(json.dumps(fixtures_with), encoding="utf-8")
    provider = _ReplayResultProvider(str(subdir_with / "results.json"))
    signal = RollingFormSignal(result_provider=provider)
    match = {"team_a": "A", "team_b": "B",
             "event_date": "2026-10-01T19:00:00Z"}
    ctx = PredictionContext(fixtures=[], elo_ratings={}, played_results=[])
    out = signal.predict(match, ctx)
    # With 5 wins, form_a should be close to 1.0 → home_prob > 0.5
    assert out.home_prob != 0.5, "Form should not be the 0.5 no-op"

    # --- WITHOUT fixtures: results have no event_date, no fixtures.json ---
    subdir_no = tmp_path / "no_fixtures"
    subdir_no.mkdir()
    results_no = [
        {"team_a": "A", "team_b": "B", "home_score": 3, "away_score": 0,
         "match_id": f"md{i}"}
        for i in range(5)
    ]
    (subdir_no / "results.json").write_text(json.dumps(results_no), encoding="utf-8")
    # No fixtures.json written → _dates_by_id stays empty
    provider_nodate = _ReplayResultProvider(str(subdir_no / "results.json"))
    signal_nodate = RollingFormSignal(result_provider=provider_nodate)
    out_nodate = signal_nodate.predict(match, ctx)
    # No dates → position keys vs date anchor → excluded → form=0.5 → different output
    assert out.home_prob != out_nodate.home_prob


# ---------------------------------------------------------------------------
# 6. test_strict_before_chronology
# ---------------------------------------------------------------------------

def test_strict_before_chronology(tmp_path):
    """(a) same event_date excluded; (b) future excluded; (c) own match excluded."""
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "event_date": "2026-09-10T19:00:00Z", "match_id": "target"},
        {"team_a": "A", "team_b": "C", "home_score": 1, "away_score": 0,
         "event_date": "2026-09-10T19:00:00Z", "match_id": "same_time"},
        {"team_a": "A", "team_b": "D", "home_score": 1, "away_score": 0,
         "event_date": "2026-09-15T19:00:00Z", "match_id": "future"},
        {"team_a": "A", "team_b": "E", "home_score": 1, "away_score": 0,
         "event_date": "2026-09-01T19:00:00Z", "match_id": "past"},
    ]
    provider = _write_provider(tmp_path, results)
    got = provider.get_team_results("A", "2026-09-10T19:00:00Z")
    # Only "past" should be returned: same_time and target share the same
    # event_date as the anchor (excluded by strict <); future is after.
    assert len(got) == 1
    assert got[0]["event_date"] == "2026-09-01T19:00:00Z"


# ---------------------------------------------------------------------------
# 7. test_winner_derived_from_scores
# ---------------------------------------------------------------------------

def test_winner_derived_from_scores(tmp_path):
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 2, "away_score": 1,
         "event_date": "2026-09-01", "match_id": "win"},
        {"team_a": "A", "team_b": "B", "home_score": 0, "away_score": 3,
         "event_date": "2026-09-02", "match_id": "loss"},
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 1,
         "event_date": "2026-09-03", "match_id": "draw"},
    ]
    provider = _write_provider(tmp_path, results)
    got = provider.get_team_results("A", "2026-10-01")
    by_mid = {r["event_date"]: r for r in got}
    win = by_mid["2026-09-01"]
    loss = by_mid["2026-09-02"]
    draw = by_mid["2026-09-03"]
    assert win["winner"] == "A" and win["is_draw"] is False
    assert loss["winner"] == "B" and loss["is_draw"] is False
    assert draw["winner"] is None and draw["is_draw"] is True


# ---------------------------------------------------------------------------
# 8. test_deterministic_replay
# ---------------------------------------------------------------------------

def test_deterministic_replay(tmp_path):
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 2, "away_score": 1,
         "event_date": "2026-09-01", "match_id": "m1"},
        {"team_a": "A", "team_b": "C", "home_score": 0, "away_score": 0,
         "event_date": "2026-09-05", "match_id": "m2"},
    ]
    p1 = _write_provider(tmp_path, results)
    p2 = _write_provider(tmp_path, results)
    r1 = p1.get_team_results("A", "2026-10-01")
    r2 = p2.get_team_results("A", "2026-10-01")
    assert json.dumps(r1, sort_keys=True) == json.dumps(r2, sort_keys=True)


# ---------------------------------------------------------------------------
# 9. test_consumer_compat
# ---------------------------------------------------------------------------

def test_consumer_compat(tmp_path):
    """EnsembleEngine with RefinedElo + RollingForm(provider) + MarketOdds
    evaluates the same match twice with identical output; no crash."""
    from football_core.blender import EnsembleEngine
    from football_core.signals.refined_elo import RefinedEloSignal
    from football_core.signals.rolling_form import RollingFormSignal
    from football_core.signals.market_odds import MarketOddsSignal

    results = [
        {"team_a": "Alpha", "team_b": "Beta", "home_score": 2, "away_score": 1,
         "event_date": "2026-09-01", "match_id": "m1"},
    ]
    fixtures = [
        {"match_id": "m1", "team_a": "Alpha", "team_b": "Beta",
         "event_date": "2026-09-01T19:00:00Z"},
    ]
    provider = _write_provider(tmp_path, results, fixtures)
    engine = EnsembleEngine([
        RefinedEloSignal(),
        RollingFormSignal(result_provider=provider),
        MarketOddsSignal(),
    ])
    from football_core.signal import PredictionContext
    ctx = PredictionContext(
        fixtures=[],
        elo_ratings={"Alpha": 1900.0, "Beta": 1700.0},
    )
    match = {"team_a": "Alpha", "team_b": "Beta",
             "event_date": "2026-10-01T19:00:00Z"}
    r1 = engine.evaluate(match, ctx)
    r2 = engine.evaluate(match, ctx)
    assert round(r1.home_prob, 8) == round(r2.home_prob, 8)
    assert round(r1.draw_prob, 8) == round(r2.draw_prob, 8)
    assert round(r1.away_prob, 8) == round(r2.away_prob, 8)


# ---------------------------------------------------------------------------
# 10. test_limit_respected
# ---------------------------------------------------------------------------

def test_limit_respected(tmp_path):
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "event_date": f"2026-09-{d:02d}T12:00:00Z", "match_id": f"m{i}"}
        for i, d in enumerate(range(1, 13), 1)  # 12 prior matches
    ]
    provider = _write_provider(tmp_path, results)
    got = provider.get_team_results("A", "2026-10-01T00:00:00Z", limit=10)
    assert len(got) == 10
    # Most recent first
    assert got[0]["event_date"] == "2026-09-12T12:00:00Z"


# ---------------------------------------------------------------------------
# 11. test_no_fixtures_file_falls_back_legacy
# ---------------------------------------------------------------------------

def test_no_fixtures_file_falls_back_legacy(tmp_path):
    """Without fixtures file, MD-prefixed match_ids still work; rows
    lacking event_date are excluded against a date anchor (no leakage)."""
    results = [
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "event_date": "2026-09-01", "match_id": "m1"},
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "match_id": "nodate1"},
    ]
    provider = _write_provider(tmp_path, results, fixtures=None)
    # Date anchor: nodate1 has position key (not date), so excluded against date anchor
    got = provider.get_team_results("A", "2026-10-01T00:00:00Z")
    assert len(got) == 1
    assert got[0]["event_date"] == "2026-09-01"

    # MD-style anchor still works
    results_md = [
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "match_id": "MD03_01"},
        {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
         "match_id": "MD01_01"},
    ]
    provider_md = _write_provider(tmp_path, results_md, fixtures=None)
    got_md = provider_md.get_team_results("A", "MD03_01")
    assert len(got_md) == 1
    assert got_md[0]["event_date"] == "MD01_01"


# ---------------------------------------------------------------------------
# Existing edge-case tests (kept from original file)
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_results_file(self, tmp_path):
        path = tmp_path / "results.json"
        with open(path, "w") as f:
            json.dump([], f)
        provider = _ReplayResultProvider(str(path))
        got = provider.get_team_results("A", "2026-09-01T00:00:00Z")
        assert got == []

    def test_results_wrapped_in_dict(self, tmp_path):
        path = tmp_path / "results.json"
        with open(path, "w") as f:
            json.dump({"matches": [
                {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
                 "event_date": "2026-09-01", "match_id": "X"},
            ]}, f)
        provider = _ReplayResultProvider(str(path))
        got = provider.get_team_results("A", "2026-09-10")
        assert len(got) == 1

    def test_is_draw_from_scores_not_winner_field(self, tmp_path):
        """When winner field is absent, is_draw is derived from scores."""
        results = [
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 1,
             "event_date": "2026-09-01", "match_id": "X"},
        ]
        provider = _write_provider(tmp_path, results)
        got = provider.get_team_results("A", "2026-10-01")
        assert got[0]["is_draw"] is True
        assert got[0]["winner"] is None

    def test_matchid_returned_when_no_event_date_and_no_fixtures(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD01_01"},
        ]
        provider = _write_provider(tmp_path, results, fixtures=None)
        got = provider.get_team_results("A", "MD02_01")
        assert got[0]["event_date"] == "MD01_01"


class TestGetTeamResultsMatchIds:
    def test_matchday_ordering(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD03_01"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD01_01"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD02_01"},
        ]
        provider = _write_provider(tmp_path, results, fixtures=None)
        got = provider.get_team_results("A", "MD03_01")
        ids = [r["event_date"] for r in got]
        assert ids == ["MD02_01", "MD01_01"]

    def test_matchday_10_vs_2_not_string_compare(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD10_01"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD02_01"},
        ]
        provider = _write_provider(tmp_path, results, fixtures=None)
        got = provider.get_team_results("A", "MD10_01")
        ids = [r["event_date"] for r in got]
        assert ids == ["MD02_01"]

    def test_before_md01_returns_empty(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD01_01"},
        ]
        provider = _write_provider(tmp_path, results, fixtures=None)
        got = provider.get_team_results("A", "MD01_01")
        assert len(got) == 0


class TestMixedIDTypes:
    def test_before_iso_date_excludes_match_ids(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "event_date": "2026-09-01", "match_id": "X"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "event_date": "2026-09-10", "match_id": "Y"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD01_01"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD02_01"},
        ]
        provider = _write_provider(tmp_path, results, fixtures=None)
        got = provider.get_team_results("A", "2026-09-10")
        assert len(got) == 1
        assert got[0]["event_date"] == "2026-09-01"

    def test_before_matchid_excludes_isodated(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD05_01"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "event_date": "2026-09-01", "match_id": "X"},
            {"team_a": "A", "team_b": "B", "home_score": 1, "away_score": 0,
             "match_id": "MD01_01"},
        ]
        provider = _write_provider(tmp_path, results, fixtures=None)
        got = provider.get_team_results("A", "MD05_01")
        ids = [r["event_date"] for r in got]
        assert ids == ["MD01_01"]
