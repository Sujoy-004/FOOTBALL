"""Generic bookmaker market-odds layer shared by all competitions.

Contract
--------
- ONE normalized record per canonical fixture market: flat keys
  ``odds_home/odds_draw/odds_away`` (decimal 1X2) + vig-removed
  ``probability/draw_probability/away_probability``; provenance fields
  ``provider``, ``bookmaker``, ``provider_event_id``, ``provider_last_update``,
  ``fetched_at``, ``event_kickoff``.
- Normalization reuse: ``football_core.predictors.odds.remove_vig`` (single
  book). No per-provider de-vig.
- Fixture authority stays with the existing fixture/result providers (FDO,
  BSD). Odds providers are enrichment only and never create fixtures: events
  map onto canonical fixtures (folded team pair, kickoff date, home/away
  identity) or are rejected (unmappable / flipped / kickoff_mismatch /
  cancelled-postponed / duplicate-event-id).
- Competition isolation: events are fetched per competition-sport-key and
  mapped only against that competition's canonical fixtures, so a "Barcelona"
  event can never decorate another competition's fixtures.

Providers
---------
- ``TheOddsApiOddsProvider``: ``https://api.the-odds-api.com/v4/sports/{sport}/odds/``
  (h2h, decimal, EU books). Competition -> sport key comes from ``SPORT_KEYS``
  (config outside the class). Book selection is deterministic:
  ``primary_book`` (default ``pinnacle``) when it carries a complete h2h set,
  else the most recently updated book, ties broken lexically. Decimal prices
  are matched by folded team name (not by outcome ordering).
- ``BSDOddsProvider``: wraps the existing ``BSDDataProvider`` (league id from
  ``LEAGUE_IDS``) and re-shapes its flat events to the same normalized record.

Configuration (separate from ``DATA_PROVIDER`` which keeps meaning
"fixtures/results"):
- ``ODDS_PROVIDER=the-odds-api|bsd|auto|none`` (unset keeps legacy behavior:
  competitions use their pre-existing odds source, e.g. LaLiga uses BSD).
- ``auto`` priority (documented, deterministic): the-odds-api -> bsd -> none.
- The provider that actually supplied odds is reported in every summary/store.

Freshness
---------
- ``fetched_at`` (capture time) must be before ``event_kickoff`` and within
  ``ODDS_MAX_AGE_HOURS``.
- ``provider_last_update`` (the selected book's last_update; the provider's
  own market timestamp, kept separate from ``fetched_at``) must also be before
  kickoff; post-kickoff provider updates are rejected as STALE at acquisition.

Per-record statuses: AVAILABLE / STALE / MISSING / INVALID / UNAVAILABLE.
Aggregate states: NOT_CONFIGURED / CONNECTED / CONFIGURED_BUT_UNAVAILABLE /
ODDS_AVAILABLE / ODDS_PARTIAL / ODDS_MISSING / ODDS_STALE / PARSER_ERROR.

All acquisition is best-effort and never raises into the enclosing refresh.
"""

from __future__ import annotations

import json
import logging
import math
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from football_core.data_providers.bsd_provider import BSDDataProvider
from football_core.fetcher import fold_team_key
from football_core.predictors.odds import remove_vig

logger = logging.getLogger(__name__)

MARKET = "1X2"
THE_ODDS_API = "the-odds-api"
BSD = "bsd"
ODDS_API_BASE = "https://api.the-odds-api.com/v4/sports/{sport}/odds/"

SPORT_KEYS = {
    "laliga": "soccer_spain_la_liga",
    "ucl": "soccer_uefa_champs_league",
    "world_cup": "soccer_fifa_world_cup",
}
LEAGUE_IDS = {
    "laliga": 3,
    "ucl": 7,
    "world_cup": 27,
}

ODDS_MAX_AGE_HOURS = 24
MIN_DECIMAL_ODDS = 1.01
MAX_IMPLIED_SUM = 1.40

STATUS_AVAILABLE = "AVAILABLE"
STATUS_STALE = "STALE"
STATUS_MISSING = "MISSING"
STATUS_INVALID = "INVALID"
STATUS_UNAVAILABLE = "UNAVAILABLE"

STATE_NOT_CONFIGURED = "NOT_CONFIGURED"
STATE_CONNECTED = "CONNECTED"
STATE_CONFIGURED_BUT_UNAVAILABLE = "CONFIGURED_BUT_UNAVAILABLE"
STATE_ODDS_AVAILABLE = "ODDS_AVAILABLE"
STATE_ODDS_PARTIAL = "ODDS_PARTIAL"
STATE_ODDS_MISSING = "ODDS_MISSING"
STATE_ODDS_STALE = "ODDS_STALE"
STATE_PARSER_ERROR = "PARSER_ERROR"

_STATUS_SKIPPED = {"finished", "postponed", "cancelled", "abandoned"}


class OddsProviderError(Exception):
    """Base for odds-provider failures (never leaks into callers)."""


class ProviderNotConfiguredError(OddsProviderError):
    """No credential / no config for the requested competition."""


class ProviderUnavailableError(OddsProviderError):
    """Transport or upstream HTTP failure."""


class ProviderParseError(OddsProviderError):
    """Upstream returned something that is not the expected contract."""


def parse_utc(value) -> datetime | None:
    """Parse an ISO/UTC string (``...Z`` or naive) into tz-aware UTC."""
    if not value:
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _odds_key_usable(api_key: str | None) -> str | None:
    """A real credential returns the key; empty/placeholder returns None."""
    text = (api_key or "").strip()
    if not text or text.lower().startswith("your_"):
        return None
    return text


def _valid_decimal(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v >= MIN_DECIMAL_ODDS)


def validate_1x2(odds_home, odds_draw, odds_away) -> tuple[bool, str | None]:
    """Positivity/plausibility gate on raw 1X2 decimal odds."""
    for name, v in (("odds_home", odds_home), ("odds_draw", odds_draw),
                    ("odds_away", odds_away)):
        if not _valid_decimal(v):
            return False, f"invalid_{name}"
    implied = 1.0 / odds_home + 1.0 / odds_draw + 1.0 / odds_away
    if implied > MAX_IMPLIED_SUM:
        return False, "implausible_overround"
    return True, None


def _alias_lookup(data_dir=Path("data")) -> dict[str, str]:
    """Fold-key -> canonical team name from the shipped alias file."""
    path = Path(data_dir) / "team_aliases.json"
    if not path.exists():
        return {}
    try:
        aliases = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(aliases, dict):
        return {}
    lookup: dict[str, str] = {}
    for canonical, variants in aliases.items():
        lookup[fold_team_key(canonical)] = canonical
        for variant in variants or []:
            lookup[fold_team_key(str(variant))] = canonical
    return lookup


def canonicalize_names(home: str, away: str, alias_lookup: dict[str, str]) -> tuple[str, str]:
    return (
        alias_lookup.get(fold_team_key(str(home)), str(home)),
        alias_lookup.get(fold_team_key(str(away)), str(away)),
    )


def _fixture_lookup(fixtures: list[dict]) -> dict[tuple[str, str], dict]:
    """{(fold_home, fold_away): fixture} for the canonical season."""
    out: dict[tuple[str, str], dict] = {}
    for f in fixtures:
        home = fold_team_key(str(f.get("home_team", "")))
        away = fold_team_key(str(f.get("away_team", "")))
        if home and away:
            out[(home, away)] = f
    return out


# ── provider base ────────────────────────────────────────────────────────


class OddsProvider:
    """Competition-agnostic odds adapter (concrete subclasses bound below)."""

    name: str = "base"

    def fetch_events(self, competition: str) -> list[dict]:
        """Return normalized odds events for ``competition``.

        Each event: id, home_team, away_team, event_date, status,
        odds_home/odds_draw/odds_away (or None), bookmaker, bookmaker_key,
        provider_last_update, provider, provenance, n_books.
        """
        raise NotImplementedError

    def endpoint_for(self, competition: str) -> str:
        raise NotImplementedError


# ── The Odds API adapter ─────────────────────────────────────────────────


class TheOddsApiOddsProvider(OddsProvider):
    """Official v4 contract: /v4/sports/{sport}/odds/ (h2h, decimal, EU)."""

    name = THE_ODDS_API
    regions = "eu"
    markets = "h2h"
    odds_format = "decimal"

    def __init__(self, api_key: str, sport_keys: dict[str, str] | None = None,
                 primary_book: str = "pinnacle", timeout: int = 30):
        self.api_key = api_key
        self.sport_keys = dict(sport_keys or SPORT_KEYS)
        self.primary_book = primary_book
        self.timeout = timeout

    def endpoint_for(self, competition: str) -> str:
        return ODDS_API_BASE.format(sport=self.sport_keys.get(competition) or "?")

    def fetch_events(self, competition: str, *, http_fn=None) -> list[dict]:
        sport = self.sport_keys.get(competition)
        if not sport:
            raise ProviderNotConfiguredError(f"no the-odds-api sport key for {competition!r}")
        url = self.endpoint_for(competition)
        params = {"apiKey": self.api_key, "regions": self.regions,
                  "markets": self.markets, "oddsFormat": self.odds_format}
        resp = (http_fn(url, params) if http_fn is not None
                else requests.get(url, params=params, timeout=self.timeout))
        if getattr(resp, "status_code", None) != 200:
            raise ProviderUnavailableError(
                f"the-odds-api http {getattr(resp, 'status_code', 'unknown')} for {sport!r}")
        try:
            data = resp.json()
        except Exception as exc:
            raise ProviderParseError(f"the-odds-api non-JSON: {exc}") from exc
        if not isinstance(data, list):
            raise ProviderParseError("the-odds-api response is not a list of events")
        return [self._normalize_event(ev, url) for ev in data if isinstance(ev, dict)]

    def _normalize_event(self, ev: dict, url: str) -> dict:
        home, away = str(ev.get("home_team") or ""), str(ev.get("away_team") or "")
        book = self._select_book(ev.get("bookmakers") or [], home, away)
        prices = (None, None, None)
        bookmaker = bookmaker_key = provider_last_update = None
        if book is not None:
            bookmaker = str(book.get("title") or book.get("key") or "")
            bookmaker_key = book.get("key")
            provider_last_update = book.get("last_update")
            prices = self._h2h_prices(book, home, away)
        return {
            "id": ev.get("id"),
            "home_team": home,
            "away_team": away,
            "event_date": ev.get("commence_time"),
            "status": "scheduled",
            "odds_home": prices[0], "odds_draw": prices[1], "odds_away": prices[2],
            "bookmaker": bookmaker, "bookmaker_key": bookmaker_key,
            "provider_last_update": provider_last_update,
            "provider": self.name, "provenance": url,
            "n_books": len([b for b in (ev.get("bookmakers") or []) if isinstance(b, dict)]),
        }

    def _select_book(self, bookmakers: list[dict], home: str, away: str) -> dict | None:
        """Deterministic primary-book selection (never prediction-tuned).

        Primary book (``self.primary_book``) with a complete h2h price set,
        else most recently updated book (ties broken lexically by key).
        """
        epoch = datetime.min.replace(tzinfo=timezone.utc)
        def _ts(b: dict):
            return (parse_utc(b.get("last_update")) or epoch).timestamp()
        ordered = sorted((b for b in bookmakers if isinstance(b, dict)),
                         key=lambda b: (-_ts(b), str(b.get("key") or "")))
        for b in ordered:
            if (b.get("key") == self.primary_book and self._h2h_prices(b, home, away)[0] is not None):
                return b
        for b in ordered:
            if self._h2h_prices(b, home, away)[0] is not None:
                return b
        return None

    @staticmethod
    def _h2h_prices(book: dict, home: str, away: str) -> tuple | None:
        """(home, draw, away) decimal prices for the first complete h2h market."""
        for m in book.get("markets") or []:
            if not isinstance(m, dict) or m.get("key") != "h2h":
                continue
            by_name: dict[str, float] = {}
            for o in m.get("outcomes") or []:
                nm = str(o.get("name") or "")
                if nm:
                    by_name[fold_team_key(nm)] = o.get("price")
            h = by_name.get(fold_team_key(home))
            d = by_name.get("draw")
            a = by_name.get(fold_team_key(away))
            if h is not None and d is not None and a is not None:
                return (h, d, a)
        return (None, None, None)


# ── BSD adapter ──────────────────────────────────────────────────────────


class BSDOddsProvider(OddsProvider):
    """Re-shapes the existing BSDDataProvider feed into normalized events."""

    name = BSD

    def __init__(self, api_key: str, league_ids: dict[str, int] | None = None,
                 endpoint: str | None = None):
        self.api_key = api_key
        self.league_ids = dict(league_ids or LEAGUE_IDS)
        self._endpoint = endpoint

    def endpoint_for(self, competition: str) -> str:
        if self._endpoint:
            return self._endpoint
        lid = self.league_ids.get(competition, "")
        return f"https://sports.bzzoiro.com/api/events/?league_id={lid}"

    def fetch_events(self, competition: str, *, fetch_fn=None) -> list[dict]:
        lid = self.league_ids.get(competition)
        if not lid:
            raise ProviderNotConfiguredError(f"no bsd league id for {competition!r}")
        try:
            if fetch_fn is not None:
                raw = list(fetch_fn() or [])
            else:
                raw = list(BSDDataProvider(self.api_key, league_id=lid).fetch_matches() or [])
        except Exception as exc:
            raise ProviderUnavailableError(f"bsd fetch failed: {exc}") from exc
        return [self._normalize_event(e) for e in raw if isinstance(e, dict)]

    def _normalize_event(self, e: dict) -> dict:
        return {
            "id": e.get("id"),
            "home_team": e.get("home_team"),
            "away_team": e.get("away_team"),
            "event_date": e.get("event_date"),
            "status": e.get("status") or "scheduled",
            "odds_home": e.get("odds_home"), "odds_draw": e.get("odds_draw"),
            "odds_away": e.get("odds_away"),
            "bookmaker": "BSD", "bookmaker_key": "bsd",
            "provider_last_update": None,
            "provider": self.name, "provenance": self.endpoint_for("x"),
            "n_books": 1,
        }


# ── provider resolution ──────────────────────────────────────────────────


def resolve_odds_provider(mode: str | None = None, *, env: dict | None = None,
                          the_odds_api_key: str | None = None,
                          bsd_api_key: str | None = None
                          ) -> tuple[str | None, OddsProvider | None]:
    """Determine the active odds provider (deterministic).

    ``mode``: ODDS_PROVIDER value. ``auto`` priority: the-odds-api -> bsd.
    Returns (provider_name, provider); provider is None when the requested
    mode has no usable credential. Mode ``""``/``none`` resolve to (None, None)
    (``none`` is handled by callers as an explicit disable).
    """
    env = env if env is not None else os.environ
    mode = (mode if mode is not None else env.get("ODDS_PROVIDER") or "").strip().lower()
    toa = _odds_key_usable(the_odds_api_key if the_odds_api_key is not None
                           else env.get("THE_ODDS_API_KEY"))
    bsd = _odds_key_usable(bsd_api_key if bsd_api_key is not None else env.get("BSD_API_KEY"))
    if mode == THE_ODDS_API:
        return (THE_ODDS_API, TheOddsApiOddsProvider(toa)) if toa else (THE_ODDS_API, None)
    if mode == BSD:
        return (BSD, BSDOddsProvider(bsd)) if bsd else (BSD, None)
    if mode == "auto":
        if toa:
            return (THE_ODDS_API, TheOddsApiOddsProvider(toa))
        if bsd:
            return (BSD, BSDOddsProvider(bsd))
        return (None, None)
    return (None, None)


# ── acquisition core (competition-agnostic) ──────────────────────────────


def _missing_record(fixture: dict, now: datetime, *, provider: str, bookmaker: str,
                    market: str, endpoint: str) -> dict:
    return {
        "match_id": fixture.get("match_id"),
        "home_team": fixture.get("home_team"),
        "away_team": fixture.get("away_team"),
        "provider": provider,
        "bookmaker": bookmaker,
        "market": market,
        "odds_home": None, "odds_draw": None, "odds_away": None,
        "probability": None, "draw_probability": None, "away_probability": None,
        "fetched_at": now.isoformat(),
        "provider_last_update": None,
        "event_kickoff": fixture.get("event_date"),
        "status": STATUS_MISSING,
        "reason": "odds_not_available",
        "event_id": None,
        "provenance": endpoint,
        "normalized": False,
    }


def _available_record(fixture: dict, event: dict, odds_home, odds_draw, odds_away,
                      now: datetime, *, provider: str, market: str,
                      endpoint: str, status: str = STATUS_AVAILABLE,
                      reason: str | None = None) -> dict:
    probs = remove_vig(odds_home, odds_draw, odds_away)
    return {
        "match_id": fixture.get("match_id"),
        "home_team": fixture.get("home_team"),
        "away_team": fixture.get("away_team"),
        "provider": provider,
        "bookmaker": event.get("bookmaker") or provider,
        "market": market,
        "odds_home": odds_home, "odds_draw": odds_draw, "odds_away": odds_away,
        "probability": probs["home"], "draw_probability": probs["draw"],
        "away_probability": probs["away"],
        "fetched_at": now.isoformat(),
        "provider_last_update": event.get("provider_last_update"),
        "event_kickoff": event.get("event_date") or fixture.get("event_date"),
        "status": status,
        "reason": reason,
        "event_id": str(event.get("id")),
        "provenance": event.get("provenance") or endpoint,
        "normalized": True,
    }


def _atomic_write_odds(store: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.stem + ".tmp")
    tmp.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _aggregate_state(counts: dict, events_seen: bool) -> str:
    if counts["available"] > 0:
        if counts["invalid"] > 0 or counts["missing"] > 0:
            return STATE_ODDS_PARTIAL
        return STATE_ODDS_AVAILABLE
    if counts["invalid"] > 0:
        return STATE_PARSER_ERROR
    return STATE_CONNECTED if events_seen else STATE_ODDS_MISSING


def acquire_odds_store(
    events: list[dict],
    fixtures: list[dict],
    alias_lookup: dict[str, str],
    *,
    data_dir,
    season_token: str,
    now: datetime,
    provider: str,
    bookmaker: str,
    market: str = MARKET,
    competition: str = "laliga",
    store_path: Path,
    endpoint: str = "",
    iso_note: str,
    aggregation: str,
) -> dict:
    """Map normalized provider events onto canonical fixtures and persist.

    Returns the acquisition summary (state, reason, store_path,
    n_events, counts, matches). Never raises for bad data.
    """
    base = {"market": market, "provider": provider, "season": season_token,
            "competition": competition, "schema": 1, "_runtime": True}

    records: dict[str, dict] = {
        f["match_id"]: _missing_record(f, now, provider=provider, bookmaker=bookmaker,
                                       market=market, endpoint=endpoint)
        for f in fixtures if f.get("match_id")
    }
    counts = {"available": 0, "missing": 0, "invalid": 0, "stale": 0,
              "skipped_status": 0, "unmappable": 0, "kickoff_mismatch": 0}
    seen: set[str] = set()
    pair_by = _fixture_lookup(fixtures)

    for e in events:
        if not isinstance(e, dict):
            continue
        eid = str(e.get("id") or "")
        if not eid or eid in seen:
            continue
        seen.add(eid)

        home, away = canonicalize_names(e.get("home_team"), e.get("away_team"), alias_lookup)
        fixture = pair_by.get((fold_team_key(home), fold_team_key(away)))
        if fixture is None:
            counts["unmappable"] += 1
            continue

        mid = fixture.get("match_id")
        if mid is None or mid not in records:
            counts["unmappable"] += 1
            continue
        if str(fixture.get("status") or "").lower() in _STATUS_SKIPPED:
            counts["skipped_status"] += 1
            continue

        ev_ko = parse_utc(e.get("event_date"))
        fx_ko = parse_utc(fixture.get("event_date"))
        if ev_ko is not None and fx_ko is not None and ev_ko.date() != fx_ko.date():
            counts["kickoff_mismatch"] += 1
            continue

        record = records[mid]
        odds_home, odds_draw, odds_away = (e.get("odds_home"), e.get("odds_draw"),
                                           e.get("odds_away"))
        if odds_home is None and odds_draw is None and odds_away is None:
            continue
        plu = parse_utc(e.get("provider_last_update"))
        if plu is not None and ev_ko is not None and plu >= ev_ko:
            counts["stale"] += 1
            records[mid] = _available_record(
                fixture, e, odds_home, odds_draw, odds_away, now,
                provider=provider, market=market, endpoint=endpoint,
                status=STATUS_STALE, reason="post_kickoff_provider_update")
            continue
        ok, reason = validate_1x2(odds_home, odds_draw, odds_away)
        if not ok:
            counts["invalid"] += 1
            record.update({"status": STATUS_INVALID, "reason": reason,
                           "provider": provider, "event_id": eid})
            continue
        records[mid] = _available_record(fixture, e, odds_home, odds_draw, odds_away, now,
                                         provider=provider, market=market, endpoint=endpoint)
        counts["available"] += 1

    for r in records.values():
        if r.get("status") == STATUS_MISSING:
            counts["missing"] += 1

    store = {**base,
             "bookmaker": bookmaker,
             "normalization": "remove_vig (football_core.predictors.odds.remove_vig)",
             "aggregation": aggregation,
             "book_selection": _book_selection_note(events),
             "endpoint": _events_provenance(events) or endpoint,
             "fetched_at": now.isoformat(),
             "expires_at": (now + timedelta(hours=ODDS_MAX_AGE_HOURS)).isoformat(),
             "matches": records,
             "iso_note": iso_note}
    store_path = Path(store_path)
    try:
        _atomic_write_odds(store, store_path)
    except OSError as exc:
        logger.warning("odds store write failed: %s", exc)
        store_path = None

    state = _aggregate_state(counts, bool(seen))
    return {**base, "state": state, "reason": None,
            "fetched_at": now.isoformat(), "expires_at": store.get("expires_at"),
            "store_path": str(store_path) if store_path else None,
            "n_events": len(seen), "counts": counts, "matches": records}


def _book_selection_note(events: list[dict]) -> str:
    keys = sorted({str(e.get("bookmaker_key") or "") for e in events if isinstance(e, dict)
                   and e.get("bookmaker_key")})
    if not keys:
        return "none"
    if len(keys) == 1:
        return f"single_book:{keys[0]}"
    return "primary_book_deterministic(per-event):" + "+".join(keys)


def _events_provenance(events: list[dict]) -> str:
    seen_urls = sorted({str(e.get("provenance") or "") for e in events if isinstance(e, dict)
                        and e.get("provenance")})
    return seen_urls[0] if len(seen_urls) == 1 else ", ".join(seen_urls) or ""


def default_season_dir(data_dir, season_token: str) -> Path:
    """Shared competition-scoped season dir: <data_dir>/seasons/<season>."""
    return Path(data_dir) / "seasons" / str(season_token).replace("/", "_")


# ── load / freshness / enrichment ────────────────────────────────────────


def load_odds(data_dir, season_token: str, *, store_path: Path | None = None) -> dict:
    """Read a competition-scoped odds store (empty dict when absent/corrupt)."""
    path = store_path or default_season_dir(data_dir, season_token) / "odds.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def usable_odds(record: dict | None, now: datetime | None = None) -> tuple[float, float, float] | None:
    """(odds_home, odds_draw, odds_away) when the record is pre-kickoff & fresh."""
    now = now or datetime.now(timezone.utc)
    if not record or record.get("status") != STATUS_AVAILABLE:
        return None
    fetched = parse_utc(record.get("fetched_at"))
    kickoff = parse_utc(record.get("event_kickoff"))
    if fetched is None or kickoff is None:
        return None
    if fetched >= kickoff:
        return None
    plu = parse_utc(record.get("provider_last_update"))
    if plu is not None and plu >= kickoff:
        return None
    if (now - fetched).total_seconds() > ODDS_MAX_AGE_HOURS * 3600:
        return None
    h, d, a = record.get("odds_home"), record.get("odds_draw"), record.get("odds_away")
    if h is None or d is None or a is None:
        return None
    return (h, d, a)


def record_status(record: dict | None, now: datetime | None = None) -> str:
    """Prediction-time status for one record.

    Only records that actually carry odds (AVAILABLE) can age into STALE;
    a never-odds MISSING/INVALID/UNAVAILABLE record stays as-is regardless of
    kickoff, so finished matches without odds read MISSING, not STALE.
    """
    now = now or datetime.now(timezone.utc)
    if record is None:
        return STATUS_MISSING
    status = record.get("status")
    if status != STATUS_AVAILABLE:
        return status if status in (STATUS_MISSING, STATUS_INVALID, STATUS_UNAVAILABLE) else STATUS_MISSING
    fetched = parse_utc(record.get("fetched_at"))
    kickoff = parse_utc(record.get("event_kickoff"))
    if fetched is None:
        return STATUS_MISSING
    if kickoff is not None and fetched >= kickoff:
        return STATUS_STALE
    plu = parse_utc(record.get("provider_last_update"))
    if kickoff is not None and plu is not None and plu >= kickoff:
        return STATUS_STALE
    if (now - fetched).total_seconds() > ODDS_MAX_AGE_HOURS * 3600:
        return STATUS_STALE
    return STATUS_AVAILABLE


def decorate_matches(matches: list[dict], store: dict | None, now: datetime | None = None) -> list[dict]:
    """Merge usable ``odds_home/draw/away`` onto match dicts (no-op when none)."""
    records = (store or {}).get("matches") or {}
    for m in matches:
        mid = m.get("match_id")
        if not mid:
            continue
        odds = usable_odds(records.get(mid), now)
        if odds is not None:
            m["odds_home"], m["odds_draw"], m["odds_away"] = odds
    return matches


def odds_status_summary(store: dict | None, fixtures: list[dict] | None = None,
                        now: datetime | None = None, default_provider: str = "unknown") -> dict:
    """Aggregate observability snapshot with per-covered-fixture status counts."""
    now = now or datetime.now(timezone.utc)
    records = (store or {}).get("matches") or {}
    counts = {"available": 0, "stale": 0, "missing": 0, "invalid": 0,
              "unavailable": 0}
    for rec in records.values():
        counts[record_status(rec, now).lower()] += 1
    n_records = len(records)
    if not store or not n_records:
        state = store.get("state", STATE_ODDS_MISSING) if store else STATE_ODDS_MISSING
    elif counts["available"] > 0 and not (counts["stale"] or counts["invalid"]
                                          or counts["missing"] or counts["unavailable"]):
        state = STATE_ODDS_AVAILABLE
    elif counts["available"] > 0:
        state = STATE_ODDS_PARTIAL
    elif counts["stale"] > 0:
        state = STATE_ODDS_STALE
    elif counts["invalid"] > 0:
        state = STATE_PARSER_ERROR
    else:
        state = STATE_ODDS_MISSING
    return {
        "state": state,
        "provider": (store or {}).get("provider", default_provider),
        "market": (store or {}).get("market", MARKET),
        "fetched_at": (store or {}).get("fetched_at"),
        "expires_at": (store or {}).get("expires_at"),
        "counts": counts,
        "n_matches": n_records,
    }