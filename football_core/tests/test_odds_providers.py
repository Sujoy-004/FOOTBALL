"""Phase 13B — generic live odds-provider layer tests.

Covers the ``football_core.odds`` abstraction: provider interface + contract,
The Odds API adapter parsing (events, bookmakers, h2h extraction,
deterministic primary-book selection, duplicate books), BSD adapter, provider
resolution (``ODDS_PROVIDER`` modes + auto precedence + failures), canonical
fixture mapping with competition isolation, kickoff mismatch, validation,
provider_last_update freshness, storage state, and the MarketOddsSignal /
market_only contract. Network-free: transports are injected with stub HTTP /
event fixtures (allowed in unit tests; never used for runtime verification).
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from football_core import odds as core
from football_core.odds import (
    BSD,
    THE_ODDS_API,
    LEAGUE_IDS,
    SPORT_KEYS,
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
    BSDOddsProvider,
    OddsProvider,
    ProviderNotConfiguredError,
    ProviderParseError,
    ProviderUnavailableError,
    TheOddsApiOddsProvider,
    acquire_odds_store,
    canonicalize_names,
    decorate_matches,
    load_odds,
    odds_status_summary,
    record_status,
    resolve_odds_provider,
    usable_odds,
    validate_1x2,
)
from football_core.predictors.odds import remove_vig
from football_core.signal import PredictionContext

NOW = datetime(2026, 9, 23, 8, 0, tzinfo=timezone.utc)

ALIASES = {
    "FC Barcelona": ["Barcelona"],
    "Real Madrid CF": ["Real Madrid"],
    "Málaga CF": ["Malaga", "Málaga"],
    "RCD Espanyol de Barcelona": ["Espanyol"],
    "Athletic Club": ["Athletic", "Athletic Bilbao"],
    "Club Atlético de Madrid": ["Atletico", "Atlético Madrid"],
    "Real Betis Balompié": ["Real Betis", "Betis"],
    "Sevilla FC": ["Sevilla"],
    "Getafe CF": ["Getafe"],
}

FIXTURES = [
    {"match_id": "1", "home_team": "FC Barcelona", "away_team": "Real Madrid CF",
     "event_date": "2026-10-10T19:00:00Z", "status": "scheduled"},
    {"match_id": "2", "home_team": "Málaga CF", "away_team": "RCD Espanyol de Barcelona",
     "event_date": "2026-10-09T19:00:00Z", "status": "scheduled"},
    {"match_id": "3", "home_team": "Athletic Club", "away_team": "Club Atlético de Madrid",
     "event_date": "2026-10-10T12:00:00Z", "status": "scheduled"},
    {"match_id": "4", "home_team": "Real Betis Balompié", "away_team": "Sevilla FC",
     "event_date": "2026-10-11T12:00:00Z", "status": "finished"},
]

_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


def make_bookmarker(key, title, last_update, home, away, h, d, a):
    return {
        "key": key, "title": title, "last_update": last_update,
        "markets": [{"key": "h2h", "outcomes": [
            {"name": home, "price": h}, {"name": "Draw", "price": d},
            {"name": away, "price": a}]}]}


def make_event(eid="ev1", home="Malaga", away="Espanyol", kickoff="2026-10-09T19:00:00Z",
               books=None):
    return {
        "id": eid, "commence_time": kickoff, "home_team": home, "away_team": away,
        "bookmakers": books or [make_bookmarker("pinnacle", "Pinnacle",
                                                "2026-10-08T10:00:00Z", home, away,
                                                2.67, 3.25, 2.73)]}


def _normalized(eid="ev1", home="Malaga", away="Espanyol",
                kickoff="2026-10-09T19:00:00Z", books=None) -> dict:
    """Run a raw event through the adapter exactly as production does."""
    prov = TheOddsApiOddsProvider("k")
    return prov.fetch_events(
        "laliga", http_fn=lambda u, p: _FakeResp(
            [make_event(eid=eid, home=home, away=away, kickoff=kickoff, books=books)]))[0]


class _FakeResp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


def _seed(data_dir: Path) -> dict[str, str]:
    (data_dir / "team_aliases.json").write_text(
        json.dumps(ALIASES, ensure_ascii=False), encoding="utf-8")


def _store(data_dir: Path, fixtures=None, events=None, provider="the-odds-api",
           bookmaker="pinnacle", now=NOW, endpoint=""):
    fixture_rows = [dict(f) for f in (fixtures if fixtures is not None else FIXTURES)]
    return core.acquire_odds_store(
        events or [], fixture_rows, core._alias_lookup(data_dir),
        data_dir=data_dir, season_token="2026/27", now=now, provider=provider,
        bookmaker=bookmaker, competition="laliga",
        store_path=core.default_season_dir(data_dir, "2026/27") / "odds.json",
        endpoint=endpoint, iso_note="test", aggregation="primary_book_deterministic")


# ── provider interface / contract ────────────────────────────────────────


def test_provider_interface_contract():
    assert isinstance(TheOddsApiOddsProvider("k"), OddsProvider)
    assert isinstance(BSDOddsProvider("k"), OddsProvider)
    assert TheOddsApiOddsProvider("k").name == "the-odds-api"
    assert BSDOddsProvider("k").name == "bsd"

    class Bogus(OddsProvider):
        pass

    with pytest.raises(NotImplementedError):
        Bogus().fetch_events("laliga")


def test_sport_and_league_keys_are_competition_config():
    assert SPORT_KEYS["laliga"] == "soccer_spain_la_liga"
    assert SPORT_KEYS["ucl"] == "soccer_uefa_champs_league"
    assert SPORT_KEYS["world_cup"] == "soccer_fifa_world_cup"
    assert LEAGUE_IDS["laliga"] == 3 and LEAGUE_IDS["ucl"] == 7 and LEAGUE_IDS["world_cup"] == 27


# ── The Odds API adapter: parsing/selection ──────────────────────────────


class TestTheOddsApiProvider:
    def test_fetches_and_normalizes_events(self):
        resp = _FakeResp([make_event()])
        prov = TheOddsApiOddsProvider("k", primary_book="pinnacle")
        events = prov.fetch_events("laliga", http_fn=lambda u, p: resp)
        assert len(events) == 1
        ev = events[0]
        assert ev["id"] == "ev1"
        assert ev["home_team"] == "Malaga" and ev["away_team"] == "Espanyol"
        assert ev["event_date"] == "2026-10-09T19:00:00Z"
        assert (ev["odds_home"], ev["odds_draw"], ev["odds_away"]) == (2.67, 3.25, 2.73)
        assert ev["bookmaker_key"] == "pinnacle"
        assert ev["provider_last_update"] == "2026-10-08T10:00:00Z"
        assert ev["provider"] == "the-odds-api"
        assert ev["n_books"] == 1

    def test_endpoint_contains_sport_key(self):
        prov = TheOddsApiOddsProvider("k")
        assert "soccer_spain_la_liga" in prov.endpoint_for("laliga")
        assert "soccer_uefa_champs_league" in prov.endpoint_for("ucl")

    def test_h2h_outcomes_matched_by_folded_name_not_order(self):
        ev = make_event(home="M\u00e1laga", away="RCD Espanyol",
                        books=[make_bookmarker("pinnacle", "Pinnacle",
                                               "2026-10-08T10:00:00Z",
                                               "M\u00e1laga", "RCD Espanyol",
                                               2.2, 3.4, 3.1)])
        prov = TheOddsApiOddsProvider("k")
        out = prov.fetch_events("laliga", http_fn=lambda u, p: _FakeResp([ev]))[0]
        assert out["odds_home"] == 2.2 and out["odds_draw"] == 3.4 and out["odds_away"] == 3.1

    def test_primary_book_preferred(self):
        books = [
            make_bookmarker("marathonbet", "Marathon", "2026-10-08T11:00:00Z",
                            "Malaga", "Espanyol", 5.0, 5.0, 5.0),
            make_bookmarker("pinnacle", "Pinnacle", "2026-10-08T10:00:00Z",
                            "Malaga", "Espanyol", 2.67, 3.25, 2.73),
        ]
        out = TheOddsApiOddsProvider("k", primary_book="pinnacle").fetch_events(
            "laliga", http_fn=lambda u, p: _FakeResp([make_event(books=books)]))[0]
        assert out["odds_home"] == 2.67 and out["bookmaker_key"] == "pinnacle"

    def test_primary_absent_uses_most_recent_book(self):
        books = [
            make_bookmarker("bet365", "Bet365", "2026-10-08T09:00:00Z",
                            "Malaga", "Espanyol", 2.9, 3.3, 2.5),
            make_bookmarker("marathonbet", "Marathon", "2026-10-08T11:00:00Z",
                            "Malaga", "Espanyol", 2.71, 3.3, 2.7),
        ]
        out = TheOddsApiOddsProvider("k", primary_book="pinnacle").fetch_events(
            "laliga", http_fn=lambda u, p: _FakeResp([make_event(books=books)]))[0]
        assert out["bookmaker_key"] == "marathonbet"

    def test_last_update_ties_break_lexically(self):
        books = [
            make_bookmarker("zzz_book", "ZZZ", "2026-10-08T10:00:00Z",
                            "Malaga", "Espanyol", 2.71, 3.3, 2.7),
            make_bookmarker("aaa_book", "AAA", "2026-10-08T10:00:00Z",
                            "Malaga", "Espanyol", 2.6, 3.4, 2.8),
        ]
        out = TheOddsApiOddsProvider("k", primary_book="missing").fetch_events(
            "laliga", http_fn=lambda u, p: _FakeResp([make_event(books=books)]))[0]
        assert out["bookmaker_key"] == "aaa_book"

    def test_incomplete_h2h_book_skipped_and_next_used(self):
        incomplete = {"key": "pinnacle", "title": "Pinnacle", "last_update": "2026-10-08T10:00:00Z",
                      "markets": [{"key": "h2h", "outcomes": [
                          {"name": "Malaga", "price": 1.2}, {"name": "Draw", "price": 3.0}]}]}
        books = [incomplete]
        filled = make_bookmarker("marathonbet", "Marathon", "2026-10-08T09:00:00Z",
                                 "Malaga", "Espanyol", 2.71, 3.3, 2.7)
        out = TheOddsApiOddsProvider("k").fetch_events(
            "laliga", http_fn=lambda u, p: _FakeResp([make_event(books=books + [filled])]))[0]
        assert out["bookmaker_key"] == "marathonbet"

    def test_no_usable_book_leaves_odds_absent(self):
        ev = make_event(books=[make_bookmarker("pinnacle", "Pinnacle",
                                               "2026-10-08T10:00:00Z",
                                               "Other", "Teams", 1.8, 3.4, 4.0)])
        out = TheOddsApiOddsProvider("k").fetch_events(
            "laliga", http_fn=lambda u, p: _FakeResp([ev]))[0]
        assert out["odds_home"] is None and out["odds_away"] is None

    def test_http_failure_raises_unavailable(self):
        prov = TheOddsApiOddsProvider("k")
        with pytest.raises(ProviderUnavailableError):
            prov.fetch_events("laliga", http_fn=lambda u, p: _FakeResp([], status=404))

    def test_malformed_json_raises_parse_error(self):
        prov = TheOddsApiOddsProvider("k")
        with pytest.raises(ProviderParseError):
            prov.fetch_events("laliga",
                              http_fn=lambda u, p: _FakeResp(ValueError("boom")))

    def test_non_list_response_raises_parse_error(self):
        prov = TheOddsApiOddsProvider("k")
        with pytest.raises(ProviderParseError):
            prov.fetch_events("laliga", http_fn=lambda u, p: _FakeResp({"events": []}))

    def test_unknown_competition_raises_not_configured(self):
        prov = TheOddsApiOddsProvider("k")
        with pytest.raises(ProviderNotConfiguredError):
            prov.fetch_events("mystery_league")


# ── BSD adapter ──────────────────────────────────────────────────────────


class TestBSDOddsProvider:
    def test_normalizes_flat_events(self):
        raw = [{"id": "e1", "home_team": "Malaga", "away_team": "Espanyol",
                "event_date": "2026-10-09T19:00:00Z", "status": "notstarted",
                "odds_home": 2.1, "odds_draw": 3.3, "odds_away": 3.4}]
        prov = BSDOddsProvider("k")
        events = prov.fetch_events("laliga", fetch_fn=lambda: raw)
        ev = events[0]
        assert (ev["odds_home"], ev["odds_draw"], ev["odds_away"]) == (2.1, 3.3, 3.4)
        assert ev["bookmaker_key"] == "bsd" and ev["provider_last_update"] is None

    def test_http_failure_becomes_unavailable(self):
        prov = BSDOddsProvider("k")
        with pytest.raises(ProviderUnavailableError):
            prov.fetch_events("laliga",
                              fetch_fn=lambda: (_ for _ in ()).throw(ConnectionError("down")))

    def test_unknown_competition(self):
        prov = BSDOddsProvider("k")
        with pytest.raises(ProviderNotConfiguredError):
            prov.fetch_events("no_such", fetch_fn=lambda: [])


# ── provider resolution / ODDS_PROVIDER ──────────────────────────────────


class TestResolution:
    def test_unset_is_none(self):
        name, prov = resolve_odds_provider(env={"ODDS_PROVIDER": ""})
        assert name is None and prov is None

    def test_none_is_none(self):
        name, prov = resolve_odds_provider(env={"ODDS_PROVIDER": "none"})
        assert name is None and prov is None

    def test_the_odds_api_mode(self):
        name, prov = resolve_odds_provider(
            env={"ODDS_PROVIDER": "the-odds-api", "THE_ODDS_API_KEY": "key_123"})
        assert name == "the-odds-api" and isinstance(prov, TheOddsApiOddsProvider)

    def test_the_odds_api_missing_key_is_none_provider(self):
        name, prov = resolve_odds_provider(env={"ODDS_PROVIDER": "the-odds-api"})
        assert name == "the-odds-api" and prov is None

    def test_bsd_mode(self):
        name, prov = resolve_odds_provider(
            env={"ODDS_PROVIDER": "bsd", "BSD_API_KEY": "key_123"})
        assert name == "bsd" and isinstance(prov, BSDOddsProvider)

    def test_auto_prefers_the_odds_api(self):
        name, prov = resolve_odds_provider(env={
            "ODDS_PROVIDER": "auto", "THE_ODDS_API_KEY": "toa",
            "BSD_API_KEY": "bsd"})
        assert name == "the-odds-api" and isinstance(prov, TheOddsApiOddsProvider)

    def test_auto_falls_back_to_bsd(self):
        name, prov = resolve_odds_provider(env={"ODDS_PROVIDER": "auto", "BSD_API_KEY": "bsd"})
        assert name == "bsd" and isinstance(prov, BSDOddsProvider)

    def test_auto_with_no_keys_is_none(self):
        name, prov = resolve_odds_provider(env={"ODDS_PROVIDER": "auto"})
        assert name is None and prov is None

    def test_placeholder_keys_ignored(self):
        name, prov = resolve_odds_provider(env={
            "ODDS_PROVIDER": "the-odds-api", "THE_ODDS_API_KEY": "your_key_here"})
        assert prov is None


# ── generic acquisition: mapping / validation / states ───────────────────


class TestAcquisition:
    def test_maps_canonical_fixtures_and_devigs(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized()])
        assert out["state"] == STATE_ODDS_PARTIAL
        assert out["provider"] == "the-odds-api"
        assert out["counts"]["available"] == 1 and out["counts"]["missing"] == 3
        rec = load_odds(tmp_path, "2026/27", store_path=core.default_season_dir(
            tmp_path, "2026/27") / "odds.json")["matches"]["2"]
        assert rec["status"] == STATUS_AVAILABLE
        assert rec["home_team"] == "Málaga CF"
        rv = remove_vig(2.67, 3.25, 2.73)
        assert rec["probability"] == pytest.approx(rv["home"], abs=1e-12)
        assert rec["provider_last_update"] == "2026-10-08T10:00:00Z"
        assert rec["provider"] == "the-odds-api"

    def test_flipped_home_away_rejected(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized(home="Espanyol", away="Malaga")])
        assert out["counts"]["unmappable"] == 1
        assert out["counts"]["available"] == 0

    def test_kickoff_mismatch_rejected(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized(eid="ev2", home="Barcelona",
                                                   away="Real Madrid",
                                                   kickoff="2026-11-02T19:00:00Z")])
        assert out["counts"]["kickoff_mismatch"] == 1

    def test_finished_fixture_skipped(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized(eid="e4", home="Real Betis",
                                                   away="Sevilla",
                                                   kickoff="2026-10-11T19:00:00Z")])
        assert out["counts"]["skipped_status"] == 1

    def test_invalid_odds_record_is_invalid(self, tmp_path):
        _seed(tmp_path)
        books = [make_bookmarker("pinnacle", "Pinnacle", "2026-10-08T10:00:00Z",
                                 "Barcelona", "Real Madrid", 1.2, 1.2, 1.2)]
        out = _store(tmp_path, events=[_normalized(eid="e1", home="Barcelona",
                                                   away="Real Madrid",
                                                   kickoff="2026-10-10T19:00:00Z",
                                                   books=books)])
        assert out["counts"]["invalid"] == 1
        assert out["state"] == STATE_PARSER_ERROR

    def test_unknown_event_unmappable(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized(eid="e-x", home="AC Milan",
                                                   away="Inter")])
        assert out["counts"]["unmappable"] == 1

    def test_two_events_for_one_fixture_last_processed_wins_in_store(self, tmp_path):
        _seed(tmp_path)
        events = [
            _normalized(eid="dup", home="Barcelona", away="Real Madrid",
                        kickoff="2026-10-10T19:00:00Z",
                        books=[make_bookmarker("pinnacle", "P1", "2026-10-08T10:00:00Z",
                                               "Barcelona", "Real Madrid", 1.6, 4.2, 5.0)]),
            _normalized(eid="dup2", home="Barcelona", away="Real Madrid",
                        kickoff="2026-10-10T19:00:00Z",
                        books=[make_bookmarker("pinnacle", "P2", "2026-10-08T11:00:00Z",
                                               "Barcelona", "Real Madrid", 2.0, 3.4, 3.6)]),
        ]
        out = _store(tmp_path, events=events)
        assert out["counts"]["available"] == 2
        store = load_odds(tmp_path, "2026/27", store_path=core.default_season_dir(
            tmp_path, "2026/27") / "odds.json")
        assert store["matches"]["1"]["odds_home"] == 2.0

    def test_long_wait_store_path_is_runtime(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[make_event()])
        assert out["store_path"].endswith(os.path.join("seasons", "2026_27", "odds.json"))

    def test_empty_feed_is_missing(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[])
        assert out["state"] == STATE_ODDS_MISSING
        assert out["counts"]["missing"] == 4


# ── post-kickoff provider_last_update freshness ──────────────────────────


class TestProviderLastUpdate:
    def test_post_kickoff_provider_update_is_stale(self, tmp_path):
        _seed(tmp_path)
        books = [make_bookmarker("pinnacle", "P", "2026-10-10T20:00:00Z",
                                 "Malaga", "Espanyol", 2.0, 3.4, 3.6)]
        out = _store(tmp_path, events=[_normalized(eid="e1", home="Malaga",
                                                   away="Espanyol", books=books)])
        assert out["counts"]["stale"] == 1 and out["counts"]["available"] == 0
        rec = load_odds(tmp_path, "2026/27", store_path=core.default_season_dir(
            tmp_path, "2026/27") / "odds.json")["matches"]["2"]
        assert rec["status"] == STATUS_STALE
        assert usable_odds(rec, NOW) is None

    def test_pre_kickoff_provider_update_is_available(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized(eid="e1", home="Malaga",
                                                   away="Espanyol")])
        assert out["counts"]["available"] == 1
        rec = load_odds(tmp_path, "2026/27", store_path=core.default_season_dir(
            tmp_path, "2026/27") / "odds.json")["matches"]["2"]
        assert record_status(rec, NOW) == STATUS_AVAILABLE

    def test_only_available_record_can_age_to_stale(self):
        assert record_status(None, NOW) == STATUS_MISSING
        missing = {"status": STATUS_MISSING, "event_kickoff": "2026-09-20T19:00:00Z"}
        assert record_status(missing, NOW) == STATUS_MISSING


# ── competition isolation ────────────────────────────────────────────────


class TestCompetitionIsolation:
    def test_ucl_event_never_leaks_into_laliga(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized(eid="ucl1", home="Barcelona",
                                                   away="Bayern Munich",
                                                   kickoff="2026-10-13T16:45:00Z")])
        assert out["counts"]["unmappable"] == 1
        assert out["counts"]["available"] == 0

    def test_same_team_name_maps_only_to_own_competition(self, tmp_path):
        _seed(tmp_path)
        out = _store(tmp_path, events=[_normalized()])
        assert out["counts"]["available"] == 1


# ── MarketOddsSignal / market_only contract ──────────────────────────────


class TestMarketIntegration:
    def test_decorate_and_market_only_non_uniform(self, tmp_path):
        _seed(tmp_path)
        _store(tmp_path, events=[_normalized()])
        store = load_odds(tmp_path, "2026/27", store_path=core.default_season_dir(
            tmp_path, "2026/27") / "odds.json")
        match = {"match_id": "2", "team_a": "Málaga CF", "team_b": "RCD Espanyol de Barcelona"}
        decorate_matches([match], store, NOW)
        assert "odds_home" in match

        from competitions.laliga.src.pipeline import build_signal_engine
        engine = build_signal_engine({}, strategy="market_only")
        bp = engine.evaluate(match, PredictionContext(fixtures=[], elo_ratings={}))
        rv = remove_vig(2.67, 3.25, 2.73)
        assert bp.home_prob == pytest.approx(rv["home"], abs=1e-6)
        assert bp.home_prob != pytest.approx(1 / 3, abs=1e-6)

    def test_missing_odds_fall_back_to_uniform(self, tmp_path):
        _seed(tmp_path)
        _store(tmp_path, events=[])
        store = load_odds(tmp_path, "2026/27", store_path=core.default_season_dir(
            tmp_path, "2026/27") / "odds.json")
        match = {"match_id": "2", "team_a": "X", "team_b": "Y"}
        decorate_matches([match], store, NOW)
        assert "odds_home" not in match

        from competitions.laliga.src.pipeline import build_signal_engine
        bp = build_signal_engine({}, strategy="market_only").evaluate(
            match, PredictionContext(fixtures=[], elo_ratings={}))
        assert bp.home_prob == pytest.approx(1 / 3, abs=1e-6)


# ── observations ─────────────────────────────────────────────────────────


def test_validate_1x2_overround_gate():
    assert validate_1x2(2.0, 3.5, 4.0) == (True, None)
    ok, reason = validate_1x2(1.01, 1.01, 1.01)
    assert ok is False and reason == "implausible_overround"


def test_summary_available_state(tmp_path):
    _seed(tmp_path)
    fixtures = [dict(f) for f in FIXTURES[:1]]
    out = core.acquire_odds_store(
        [_normalized(home="Barcelona", away="Real Madrid",
                     kickoff="2026-10-10T19:00:00Z")],
        fixtures, core._alias_lookup(tmp_path), data_dir=tmp_path,
        season_token="2026/27", now=NOW, provider="the-odds-api",
        bookmaker="pinnacle", competition="laliga",
        store_path=core.default_season_dir(tmp_path, "2026/27") / "odds.json",
        endpoint="x", iso_note="", aggregation="x")
    assert out["state"] == STATE_ODDS_AVAILABLE

    store = load_odds(tmp_path, "2026/27", store_path=core.default_season_dir(
        tmp_path, "2026/27") / "odds.json")
    s = odds_status_summary(store, now=NOW)
    assert s["state"] == STATE_ODDS_AVAILABLE and s["provider"] == "the-odds-api"


# ── LaLiga entry-point wiring (generic mode, hermetic) ───────────────────


class TestLaLigaEntryPoint:
    def test_the_odds_api_mode_flows_through(self, tmp_path, monkeypatch):
        from competitions.laliga.src import seasons as _season_store
        _season_store.write_fixtures({"provider": "T", "fixtures": FIXTURES},
                                     tmp_path, "2026/27")
        _seed(tmp_path)

        class FakeOddsProvider:
            name = "the-odds-api"

            def fetch_events(self, competition):
                return [_normalized(eid="ev1", home="Malaga", away="Espanyol")]

            def endpoint_for(self, competition):
                return "https://example.test/odds"

        monkeypatch.setattr(core, "resolve_odds_provider",
                            lambda mode=None, **kw: ("the-odds-api", FakeOddsProvider()))
        from competitions.laliga.src.odds import acquire_laliga_odds, load_odds as ll_load
        out = acquire_laliga_odds(tmp_path, "2026/27", "", odds_mode="auto", now=NOW)
        assert out["state"] == STATE_ODDS_PARTIAL
        assert out["provider"] == "the-odds-api"
        assert out["counts"]["available"] == 1
        rec = ll_load(tmp_path, "2026/27")["matches"]["2"]
        assert rec["status"] == STATUS_AVAILABLE and rec["provider"] == "the-odds-api"

    def test_none_mode_is_not_configured(self, tmp_path):
        from competitions.laliga.src import seasons as _season_store
        _season_store.write_fixtures({"provider": "T", "fixtures": FIXTURES},
                                     tmp_path, "2026/27")
        from competitions.laliga.src.odds import acquire_laliga_odds
        out = acquire_laliga_odds(tmp_path, "2026/27", "some_key", odds_mode="none", now=NOW)
        assert out["state"] == STATE_NOT_CONFIGURED
        assert out["reason"] == "odds_provider_none"

    def test_configured_but_missing_credential_not_configured(self, tmp_path, monkeypatch):
        from competitions.laliga.src import seasons as _season_store
        _season_store.write_fixtures({"provider": "T", "fixtures": FIXTURES},
                                     tmp_path, "2026/27")
        monkeypatch.setattr(core, "resolve_odds_provider",
                            lambda mode=None, **kw: ("the-odds-api", None))
        from competitions.laliga.src.odds import acquire_laliga_odds
        out = acquire_laliga_odds(tmp_path, "2026/27", "", odds_mode="the-odds-api", now=NOW)
        assert out["state"] == STATE_NOT_CONFIGURED
        assert out["reason"] == "no_odds_credential"

    def test_configured_but_unavailable_on_http_failure(self, tmp_path, monkeypatch):
        from competitions.laliga.src import seasons as _season_store
        _season_store.write_fixtures({"provider": "T", "fixtures": FIXTURES},
                                     tmp_path, "2026/27")

        class Failing:
            name = "the-odds-api"

            def fetch_events(self, competition):
                raise core.ProviderUnavailableError("http 500")

            def endpoint_for(self, competition):
                return "x"

        monkeypatch.setattr(core, "resolve_odds_provider",
                            lambda mode=None, **kw: ("the-odds-api", Failing()))
        from competitions.laliga.src.odds import acquire_laliga_odds
        out = acquire_laliga_odds(tmp_path, "2026/27", "", odds_mode="auto", now=NOW)
        assert out["state"] == STATE_CONFIGURED_BUT_UNAVAILABLE