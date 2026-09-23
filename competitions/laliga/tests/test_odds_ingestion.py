"""Phase 13J — LaLiga live market-odds ingestion tests.

Covers the odds contract, BSD acquisition + canonical fixture mapping,
validation/de-vig, freshness (pre-kickoff, max-age), the competition-scoped
store, ``MarketOddsSignal`` enrichment (market_only non-uniform), observability
states, UCL/WC isolation, and the pipeline refresh wiring. Network-free: a
``fetch_fn`` stub feeds events with fabricated odds (allowed in unit tests;
never used for runtime verification).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from competitions.laliga.src import seasons as _season_store
from competitions.laliga.src.odds import (
    ODDS_MAX_AGE_HOURS,
    STATUS_AVAILABLE,
    STATUS_INVALID,
    STATUS_MISSING,
    STATUS_STALE,
    STATE_CONFIGURED_BUT_UNAVAILABLE,
    STATE_NOT_CONFIGURED,
    STATE_ODDS_AVAILABLE,
    STATE_ODDS_MISSING,
    STATE_ODDS_PARTIAL,
    STATE_PARSER_ERROR,
    acquire_laliga_odds,
    decorate_matches,
    load_odds,
    odds_status_summary,
    record_status,
    usable_odds,
    validate_1x2,
)
from competitions.laliga.src.pipeline import build_signal_engine
from football_core.predictors.odds import remove_vig
from football_core.signal import PredictionContext

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
FIXTURES = [
    {"match_id": "1", "home_team": "FC Barcelona", "away_team": "Real Madrid CF",
     "event_date": "2026-09-27T19:00:00Z", "status": "scheduled", "matchday": 9},
    {"match_id": "2", "home_team": "Sevilla FC", "away_team": "Villarreal CF",
     "event_date": "2026-09-26T19:00:00Z", "status": "timed", "matchday": 9},
    {"match_id": "3", "home_team": "Athletic Club", "away_team": "Getafe CF",
     "event_date": "2026-09-26T17:30:00Z", "status": "finished", "matchday": 9},
]
ALIASES = {
    "FC Barcelona": ["Barcelona", "FC Barcelona"],
    "Real Madrid CF": ["Real Madrid", "Real Madrid CF"],
    "Sevilla FC": ["Sevilla", "Sevilla FC"],
    "Villarreal CF": ["Villarreal", "Villarreal CF"],
    "Athletic Club": ["Athletic", "Athletic Club"],
    "Getafe CF": ["Getafe", "Getafe CF"],
}


def _seed_data_dir(tmp_path) -> str:
    data_dir = tmp_path / "laliga_data"
    season_store = _season_store
    season_store.write_fixtures(
        {"provider": "Test", "fixtures": FIXTURES}, data_dir, "2026/27"
    )
    (data_dir / "team_aliases.json").write_text(
        __import__("json").dumps(ALIASES, ensure_ascii=False), encoding="utf-8"
    )
    return str(data_dir)


def _event(mid: str, home: str, away: str, status: str = "notstarted",
           odds=(2.0, 3.5, 4.0), kickoff: str = "2026-09-27T19:00:00Z", eid: str = "E1"):
    return {
        "id": eid, "home_team": home, "away_team": away, "status": status,
        "event_date": kickoff, "odds_home": odds and odds[0], "odds_draw": odds and odds[1],
        "odds_away": odds and odds[2], "league": {"id": 3},
    }


# ── 1. validation ────────────────────────────────────────────────────────


class TestValidation:
    def test_valid_odds_pass(self):
        assert validate_1x2(2.0, 3.5, 4.0) == (True, None)

    @pytest.mark.parametrize("odds", [(None, 3.5, 4.0), ("2.0", 3.5, 4.0),
                                      (1.0, 3.5, 4.0), (0.0, 3.5, 4.0),
                                      (float("nan"), 3.5, 4.0), (-1.0, 3.5, 4.0)])
    def test_bad_marginal_odds_rejected(self, odds):
        ok, reason = validate_1x2(*odds)
        assert ok is False and reason is not None

    def test_implausible_overround_rejected(self):
        ok, reason = validate_1x2(1.01, 1.01, 1.01)
        assert ok is False and reason == "implausible_overround"


# ── 2. no credentials / provider failures ────────────────────────────────


class TestCredentialsAndFailures:
    def test_no_key_and_no_transport_is_not_configured(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        out = acquire_laliga_odds(data_dir, "2026/27", "", now=NOW)
        assert out["state"] == STATE_NOT_CONFIGURED
        assert out["reason"] == "no_odds_credential"
        assert not (load_odds(data_dir, "2026/27") or {}).get("matches")

    def test_placeholder_key_is_not_configured(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        out = acquire_laliga_odds(data_dir, "2026/27", "your_bsd_key_here", now=NOW)
        assert out["state"] == STATE_NOT_CONFIGURED

    def test_transport_raise_is_unavailable(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)

        def boom():
            raise ConnectionError("refused")

        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=boom, now=NOW)
        assert out["state"] == STATE_CONFIGURED_BUT_UNAVAILABLE
        assert out["reason"].startswith("ConnectionError")


# ── 3. acquisition, mapping, de-vig, store ───────────────────────────────


class TestAcquisition:
    def test_available_record_mapped_de_vigged_and_persisted(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Barcelona", "Real Madrid", odds=(1.6, 4.2, 5.0))]
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        assert out["state"] == STATE_ODDS_PARTIAL
        assert out["counts"]["available"] == 1
        assert out["counts"]["missing"] == 2

        store = load_odds(data_dir, "2026/27")
        rec = store["matches"]["1"]
        assert rec["status"] == STATUS_AVAILABLE
        assert rec["home_team"] == "FC Barcelona"
        assert rec["away_team"] == "Real Madrid CF"
        assert rec["event_id"] == "E1"
        assert rec["normalized"] is True
        rv = remove_vig(1.6, 4.2, 5.0)
        assert rec["probability"] == pytest.approx(rv["home"], abs=1e-12)
        assert rec["draw_probability"] == pytest.approx(rv["draw"], abs=1e-12)
        assert rec["away_probability"] == pytest.approx(rv["away"], abs=1e-12)

    def test_unmappable_team_counted(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "AC Milan", "Inter", eid="E1")]
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        assert out["counts"]["unmappable"] == 1
        assert out["counts"]["available"] == 0

    def test_flipped_home_away_is_unmappable(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Real Madrid", "Barcelona", eid="E1")]
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        assert out["counts"]["unmappable"] == 1
        assert out["matches"]["1"]["status"] == STATUS_MISSING

    def test_finished_fixture_skipped(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Athletic", "Getafe", status="finished", odds=(1.5, 4.0, 6.0), eid="E1")]
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        assert out["counts"]["skipped_status"] == 1
        assert out["matches"]["3"]["status"] == STATUS_MISSING

    def test_missing_odds_record_is_missing(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Barcelona", "Real Madrid", odds=None, eid="E1")]
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        assert out["matches"]["1"]["status"] == STATUS_MISSING
        assert out["counts"]["missing"] == 3

    @pytest.mark.parametrize("bad", ["1.60", -1, 1.0])
    def test_invalid_odds_record_is_invalid(self, tmp_path, bad):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Barcelona", "Real Madrid", odds=(bad, 4.2, 5.0), eid="E1")]
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        assert out["matches"]["1"]["status"] == STATUS_INVALID
        assert out["counts"]["invalid"] == 1

    def test_duplicate_event_ids_deduped(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [
            _event("E1", "Barcelona", "Real Madrid", odds=(1.6, 4.2, 5.0), eid="dup"),
            _event("E2", "Barcelona", "Real Madrid", odds=(9.0, 9.0, 9.0), eid="dup"),
        ]
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        assert out["n_events"] == 1
        assert out["counts"]["available"] == 1

    def test_latest_event_wins_for_same_fixture(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [
            _event("E1", "Barcelona", "Real Madrid", odds=(1.6, 4.2, 5.0), eid="a"),
            _event("E2", "Barcelona", "Real Madrid", odds=(2.0, 3.4, 3.6), eid="b"),
        ]
        acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        rec = load_odds(data_dir, "2026/27")["matches"]["1"]
        assert rec["event_id"] == "b"
        assert rec["odds_home"] == 2.0

    def test_empty_feed_is_missing_state(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        out = acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: [], now=NOW)
        assert out["state"] == STATE_ODDS_MISSING
        assert out["counts"]["missing"] == 3
        store = load_odds(data_dir, "2026/27")
        assert store["matches"]["2"]["status"] == STATUS_MISSING


# ── 4. freshness rules ───────────────────────────────────────────────────


class TestFreshness:
    def _record(self, fetched_at: str, kickoff: str):
        return {
            "match_id": "1", "home_team": "FC Barcelona", "away_team": "Real Madrid CF",
            "status": STATUS_AVAILABLE, "odds_home": 1.6, "odds_draw": 4.2,
            "odds_away": 5.0, "fetched_at": fetched_at, "event_kickoff": kickoff,
        }

    def test_pre_kickoff_within_age_is_usable(self):
        odds = usable_odds(self._record(NOW.isoformat(), "2026-09-27T19:00:00Z"), NOW)
        assert odds == (1.6, 4.2, 5.0)

    def test_post_kickoff_is_not_usable_and_stale(self):
        rec = self._record(NOW.isoformat(), "2026-09-20T19:00:00Z")
        assert usable_odds(rec, NOW) is None
        assert record_status(rec, NOW) == STATUS_STALE

    def test_older_than_max_age_is_not_usable_and_stale(self):
        old = (NOW - timedelta(hours=ODDS_MAX_AGE_HOURS + 1)).isoformat()
        rec = self._record(old, "2026-09-30T19:00:00Z")
        assert usable_odds(rec, NOW) is None
        assert record_status(rec, NOW) == STATUS_STALE

    def test_missing_and_invalid_statuses(self):
        assert record_status(None, NOW) == STATUS_MISSING
        invalid = {"status": STATUS_INVALID, "fetched_at": NOW.isoformat()}
        assert record_status(invalid, NOW) == STATUS_INVALID

    def test_missing_record_post_kickoff_stays_missing(self):
        rec = {"status": STATUS_MISSING, "fetched_at": NOW.isoformat(),
               "event_kickoff": "2026-09-20T19:00:00Z"}
        assert record_status(rec, NOW) == STATUS_MISSING

    def test_available_within_window(self):
        rec = self._record((NOW - timedelta(hours=2)).isoformat(), "2026-09-30T19:00:00Z")
        assert record_status(rec, NOW) == STATUS_AVAILABLE


# ── 5. MarketOddsSignal enrichment (market_only) ─────────────────────────


class TestSignalEnrichment:
    def test_decorate_merges_usable_odds_only(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Barcelona", "Real Madrid", odds=(1.6, 4.2, 5.0), eid="E1")]
        acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        matches = [{"match_id": "1", "team_a": "FC Barcelona", "team_b": "Real Madrid CF"},
                   {"match_id": "9", "team_a": "X", "team_b": "Y"}]
        decorate_matches(matches, load_odds(data_dir, "2026/27"), NOW)
        assert matches[0]["odds_home"] == 1.6
        assert "odds_home" not in matches[1]

    def test_worldcup_match_id_not_decorated(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Barcelona", "Real Madrid", odds=(1.6, 4.2, 5.0), eid="E1")]
        acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        wc_match = {"match_id": "WC-ARG-BRA", "team_a": "Argentina", "team_b": "Brazil"}
        decorate_matches([wc_match], load_odds(data_dir, "2026/27"), NOW)
        assert wc_match == {"match_id": "WC-ARG-BRA", "team_a": "Argentina", "team_b": "Brazil"}

    def test_market_only_engine_non_uniform_after_decoration(self, tmp_path):
        data_dir = _seed_data_dir(tmp_path)
        events = [_event("E1", "Barcelona", "Real Madrid", odds=(1.6, 4.2, 5.0), eid="E1")]
        acquire_laliga_odds(data_dir, "2026/27", "deadbeef", fetch_fn=lambda: events, now=NOW)
        match = {"match_id": "1", "team_a": "FC Barcelona", "team_b": "Real Madrid CF"}
        decorate_matches([match], load_odds(data_dir, "2026/27"), NOW)

        engine = build_signal_engine({}, strategy="market_only")
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        bp = engine.evaluate(match, ctx)
        assert (bp.home_prob, bp.draw_prob, bp.away_prob) != pytest.approx((1/3, 1/3, 1/3), abs=1e-9)
        rv = remove_vig(1.6, 4.2, 5.0)
        assert bp.home_prob == round(rv["home"], 6)


# ── 6. observability states ──────────────────────────────────────────────


class TestObservability:
    def test_summary_available(self):
        store = {"provider": "BSD", "state": STATE_ODDS_AVAILABLE,
                 "matches": {"1": {"status": STATUS_AVAILABLE,
                                   "fetched_at": "2026-09-22T10:00:00Z",
                                   "event_kickoff": "2026-09-30T19:00:00Z"}}}
        s = odds_status_summary(store, now=NOW)
        assert s["state"] == STATE_ODDS_AVAILABLE
        assert s["counts"]["available"] == 1

    def test_summary_partial_when_mixed(self):
        store = {"provider": "BSD", "state": STATE_ODDS_AVAILABLE, "matches": {
            "1": {"status": STATUS_AVAILABLE, "fetched_at": "2026-09-22T10:00:00Z",
                  "event_kickoff": "2026-09-30T19:00:00Z"},
            "2": {"status": STATUS_MISSING, "fetched_at": "2026-09-22T10:00:00Z"},
        }}
        assert odds_status_summary(store, now=NOW)["state"] == STATE_ODDS_PARTIAL

    def test_summary_parser_error_from_invalid(self):
        store = {"provider": "BSD", "state": STATE_PARSER_ERROR, "matches": {
            "1": {"status": STATUS_INVALID, "fetched_at": "2026-09-22T10:00:00Z"}}}
        assert odds_status_summary(store, now=NOW)["state"] == STATE_PARSER_ERROR

    def test_summary_empty_store_is_missing(self):
        assert odds_status_summary({}, now=NOW)["state"] == STATE_ODDS_MISSING

    def test_summary_legacy_blocking_state_preserved(self):
        store = {"state": STATE_CONFIGURED_BUT_UNAVAILABLE, "provider": "BSD"}
        assert odds_status_summary(store, now=NOW)["state"] == STATE_CONFIGURED_BUT_UNAVAILABLE


# ── 7. pipeline refresh wiring ───────────────────────────────────────────


class TestPipelineWiring:
    def test_fetch_live_data_returns_odds_block(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "lala"
        from competitions.laliga.src import seasons as ss
        ss.write_fixtures({"provider": "T", "fixtures": FIXTURES}, data_dir, "2026/27")
        (data_dir / "team_aliases.json").write_text(
            __import__("json").dumps(ALIASES, ensure_ascii=False), encoding="utf-8"
        )

        class FakeProvider:
            def fetch_matches(self, competition_id=None, **kwargs):
                return [_event("E1", "Barcelona", "Real Madrid", odds=(1.6, 4.2, 5.0), eid="E1")]

        from competitions.laliga.src import pipeline as _pipeline
        real_acquire = _pipeline.acquire_laliga_odds

        def injected_acquire(data_dir_, season_token_, bsd_key_):
            return real_acquire(data_dir_, season_token_, bsd_key_,
                                fetch_fn=lambda: [_event("E1", "Barcelona", "Real Madrid",
                                                    odds=(1.6, 4.2, 5.0), eid="E1")],
                                now=NOW)

        monkeypatch.setattr(_pipeline, "acquire_laliga_odds", injected_acquire)
        summary = _pipeline.fetch_live_data(str(data_dir), bsd_api_key="deadbeef",
                                            provider=FakeProvider())
        assert summary["status"] == "ok"
        odds_status = summary.get("odds")
        assert odds_status["state"] == STATE_ODDS_AVAILABLE
        assert odds_status["counts"]["available"] == 1
        assert odds_status["store_path"].endswith("odds.json")
        assert "matches" not in odds_status
        assert load_odds(str(data_dir), "2026/27")["matches"]["E1"]["status"] == STATUS_AVAILABLE