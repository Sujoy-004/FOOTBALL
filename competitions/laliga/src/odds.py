"""LaLiga live bookmaker market-odds ingestion.

Phase 13B turned the Phase-13A odds contract into a competition-agnostic layer
(``football_core.odds``): ``OddsProvider`` base + ``TheOddsApiOddsProvider``
(h2h / decimal / EU books) + ``BSDOddsProvider``, one provider-selection
mechanism (``ODDS_PROVIDER``), and one acquisition/mapping/de-vig/freshness/
store core reused by every competition.

This module is the LaLiga entry point. It keeps the original public API (so
the pipeline, simulation and existing tests are untouched) and multiplexes
three ingestion modes:

- ``ODDS_PROVIDER`` unset  -> legacy BSD-only path (unchanged behavior).
- ``ODDS_PROVIDER=the-odds-api|bsd`` -> exactly the named provider.
- ``ODDS_PROVIDER=auto`` -> the-odds-api when a key exists, else BSD.
- ``ODDS_PROVIDER=none``  -> odds ingestion disabled (NOT_CONFIGURED).

``DATA_PROVIDER`` is untouched and keeps its meaning (fixtures/results only).

Contract notes (inherited from ``football_core.odds``):

- Market: pre-match 1X2 decimal odds (``odds_home/draw/away``); normalization
  is the shared ``remove_vig`` primitive; enrichment is a plain key-merge onto
  match dicts, so ``MarketOddsSignal`` / ``market_only`` work unchanged.
- Freshness: record valid only when captured *before* the target kickoff and
  within ``ODDS_MAX_AGE_HOURS``. The provider's own market timestamp is kept
  separately as ``provider_last_update`` (BSD exposes none; The Odds API
  exposes it per selected book) and must also precede kickoff.
- Storage: competition-scoped, atomic store
  ``<data_dir>/seasons/<season>/odds.json`` (gitignored runtime data).

Per-record statuses: AVAILABLE / STALE / MISSING / INVALID / UNAVAILABLE.
Aggregate states: NOT_CONFIGURED / CONNECTED / CONFIGURED_BUT_UNAVAILABLE /
ODDS_AVAILABLE / ODDS_PARTIAL / ODDS_MISSING / ODDS_STALE / PARSER_ERROR.

All acquisition is best-effort: missing/invalid odds never raise and never
fail the enclosing refresh.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from football_core.data_providers.bsd_provider import BSDDataProvider
from football_core.fetcher import fold_team_key
from football_core.predictors.odds import remove_vig
from football_core import odds as core

from competitions.laliga.src import seasons as _season_store
from competitions.laliga.src.constants import DATA_DIR, LALIGA_BSD_LEAGUE_ID, SHIPPED_SEASON

MARKET = core.MARKET
PROVIDER_NAME = "BSD"
BOOKMAKER = "BSD"
ODDS_ENDPOINT = f"https://sports.bzzoiro.com/api/events/?league_id={LALIGA_BSD_LEAGUE_ID}"

ODDS_MAX_AGE_HOURS = core.ODDS_MAX_AGE_HOURS
MIN_DECIMAL_ODDS = core.MIN_DECIMAL_ODDS
MAX_IMPLIED_SUM = core.MAX_IMPLIED_SUM

STATUS_AVAILABLE = core.STATUS_AVAILABLE
STATUS_STALE = core.STATUS_STALE
STATUS_MISSING = core.STATUS_MISSING
STATUS_INVALID = core.STATUS_INVALID
STATUS_UNAVAILABLE = core.STATUS_UNAVAILABLE

STATE_NOT_CONFIGURED = core.STATE_NOT_CONFIGURED
STATE_CONNECTED = core.STATE_CONNECTED
STATE_CONFIGURED_BUT_UNAVAILABLE = core.STATE_CONFIGURED_BUT_UNAVAILABLE
STATE_ODDS_AVAILABLE = core.STATE_ODDS_AVAILABLE
STATE_ODDS_PARTIAL = core.STATE_ODDS_PARTIAL
STATE_ODDS_MISSING = core.STATE_ODDS_MISSING
STATE_ODDS_STALE = core.STATE_ODDS_STALE
STATE_PARSER_ERROR = core.STATE_PARSER_ERROR

parse_utc = core.parse_utc
_odds_key_usable = core._odds_key_usable
_valid_decimal = core._valid_decimal
validate_1x2 = core.validate_1x2
_alias_lookup = core._alias_lookup
_canonicalize = core.canonicalize_names
_fixture_lookup = core._fixture_lookup
_atomic_write_odds = core._atomic_write_odds
_aggregate_state = core._aggregate_state
usable_odds = core.usable_odds
record_status = core.record_status
decorate_matches = core.decorate_matches
odds_status_summary = core.odds_status_summary


def load_odds(data_dir=DATA_DIR, season_token: str | None = None) -> dict:
    """Read the LaLiga-scoped odds store (empty dict when absent/corrupt)."""
    season_token = season_token or _season_store.active_season(data_dir)
    return core.load_odds(data_dir, season_token,
                          store_path=_season_store.season_dir(data_dir, season_token) / "odds.json")


def _record_for_fixture(fixture: dict, now: datetime) -> dict:
    return core._missing_record(fixture, now, provider=PROVIDER_NAME,
                                bookmaker=BOOKMAKER, market=MARKET,
                                endpoint=ODDS_ENDPOINT)


def _available_record(fixture: dict, event: dict, odds_home, odds_draw, odds_away,
                      now: datetime) -> dict:
    return core._available_record(fixture, event, odds_home, odds_draw, odds_away,
                                  now, provider=PROVIDER_NAME, market=MARKET,
                                  endpoint=ODDS_ENDPOINT)


def _not_configured(base: dict, reason: str, now: datetime) -> dict:
    return {**base, "state": STATE_NOT_CONFIGURED, "reason": reason,
            "fetched_at": now.isoformat(), "store_path": None, "matches": {},
            "counts": {"available": 0, "missing": 0, "invalid": 0, "stale": 0,
                       "skipped_status": 0, "unmappable": 0, "kickoff_mismatch": 0}}


def _unavailable(base: dict, exc: Exception, now: datetime) -> dict:
    logger = core.logger
    logger.warning("odds provider fetch raised: %s", exc)
    return {**base, "state": STATE_CONFIGURED_BUT_UNAVAILABLE,
            "reason": f"{exc.__class__.__name__}: {exc}",
            "fetched_at": now.isoformat(), "store_path": None, "matches": {},
            "counts": {"available": 0, "missing": 0, "invalid": 0, "stale": 0,
                       "skipped_status": 0, "unmappable": 0, "kickoff_mismatch": 0}}


def _parser_error(base: dict, exc: Exception, now: datetime) -> dict:
    core.logger.warning("odds provider parse failure: %s", exc)
    return {**base, "state": STATE_PARSER_ERROR,
            "reason": f"{exc.__class__.__name__}: {exc}",
            "fetched_at": now.isoformat(), "store_path": None, "matches": {},
            "counts": {"available": 0, "missing": 0, "invalid": 0, "stale": 0,
                       "skipped_status": 0, "unmappable": 0, "kickoff_mismatch": 0}}


def acquire_laliga_odds(
    data_dir=DATA_DIR,
    season_token: str | None = None,
    bsd_api_key: str = "",
    *,
    provider: BSDDataProvider | None = None,
    fetch_fn=None,
    now: datetime | None = None,
    odds_mode: str | None = None,
) -> dict:
    """Pull live market odds for the LaLiga season and persist the store.

    ``fetch_fn`` injects a legacy BSD-style event stub (used by tests);
    ``provider`` injects an existing BSD transport; ``odds_mode`` overrides
    ``ODDS_PROVIDER`` (used by callers who must not touch the environment).

    Never raises: every failure mode is folded into the returned summary's
    ``state``. Returns the acquisition summary (state, counts, store path).
    """
    now = now or datetime.now(timezone.utc)
    season_token = season_token or _season_store.active_season(data_dir)
    mode = (odds_mode if odds_mode is not None
            else (os.getenv("ODDS_PROVIDER") or "")).strip().lower()

    fixtures = [f for f in _season_store.read_fixtures(data_dir, season_token).get("fixtures", [])
                if isinstance(f, dict)]
    alias = _alias_lookup(data_dir)

    # ── injected transport stub (tests / legacy flat events) ────────────
    if fetch_fn is not None:
        base = {"market": MARKET, "provider": PROVIDER_NAME, "season": season_token,
                "competition": "laliga", "schema": 1, "_runtime": True}
        try:
            events = list(fetch_fn() or [])
        except Exception as exc:
            return _unavailable(base, exc, now)
        return _run_store(events, fixtures, alias, data_dir, season_token, now,
                          provider=PROVIDER_NAME, bookmaker=BOOKMAKER,
                          market=MARKET, competition="laliga")

    # ── ODDS_PROVIDER modes ──────────────────────────────────────────────
    if mode in (core.THE_ODDS_API, core.BSD, "auto"):
        name, odds_provider = core.resolve_odds_provider(mode=mode)
        base = {"market": MARKET, "provider": name if name else "none",
                "season": season_token, "competition": "laliga",
                "schema": 1, "_runtime": True}
        if odds_provider is None:
            return _not_configured(base, "no_odds_credential", now)
        try:
            events = list(odds_provider.fetch_events("laliga") or [])
        except core.ProviderUnavailableError as exc:
            return _unavailable(base, exc, now)
        except (core.ProviderParseError, ValueError, TypeError) as exc:
            return _parser_error(base, exc, now)
        bookmaker = (odds_provider.primary_book
                     if isinstance(odds_provider, core.TheOddsApiOddsProvider) else "BSD")
        iso_note = ("provider_last_update kept per record (selected book); "
                    "fetched_at is capture time")
        return _run_store(events, fixtures, alias, data_dir, season_token, now,
                          provider=name or "none", bookmaker=bookmaker,
                          market=MARKET, competition="laliga", iso_note=iso_note,
                          endpoint=odds_provider.endpoint_for("laliga"),
                          aggregation="primary_book_deterministic"
                          if isinstance(odds_provider, core.TheOddsApiOddsProvider)
                          else "latest_event_wins_single_book")

    if mode == "none":
        base = {"market": MARKET, "provider": "none", "season": season_token,
                "competition": "laliga", "schema": 1, "_runtime": True}
        return _not_configured(base, "odds_provider_none", now)

    # ── legacy default: BSD (mode unset) ─────────────────────────────────
    base = {"market": MARKET, "provider": PROVIDER_NAME, "season": season_token,
            "competition": "laliga", "schema": 1, "_runtime": True}
    key = _odds_key_usable(bsd_api_key)
    if key is None and provider is None:
        return _not_configured(base, "no_odds_credential", now)
    try:
        if provider is None:
            provider = BSDDataProvider(key, league_id=LALIGA_BSD_LEAGUE_ID)
        events = list(provider.fetch_matches() or [])
    except Exception as exc:
        return _unavailable(base, exc, now)
    return _run_store(events, fixtures, alias, data_dir, season_token, now,
                      provider=PROVIDER_NAME, bookmaker=BOOKMAKER,
                      market=MARKET, competition="laliga")


def _run_store(events, fixtures, alias, data_dir, season_token, now, *,
               provider: str, bookmaker: str, market: str, competition: str,
               iso_note: str = "", endpoint: str = "", aggregation: str = "") -> dict:
    store_path = _season_store.season_dir(data_dir, season_token) / "odds.json"
    return core.acquire_odds_store(
        events, fixtures, alias, data_dir=data_dir, season_token=season_token,
        now=now, provider=provider, bookmaker=bookmaker, market=market,
        competition=competition, store_path=store_path, endpoint=endpoint,
        iso_note=iso_note or (
            "BSD exposes no separate odds timestamp; fetched_at is odds capture time"),
        aggregation=aggregation or "latest_event_wins_single_book")