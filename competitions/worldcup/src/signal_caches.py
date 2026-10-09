"""World Cup signal-cache producers (plan 02-09, D-08/D-20).

Single acquisition pass: once a World Cup refresh has ingested verified
results, it runs these producers so the refresh leaves the four engine caches
(``odds``, ``rolling_form``, ``squad_value``, ``rest_days``) in the exact shape
``build_engine_from_caches`` consumes (D-02). Nothing else in the refresh path
touches signal caches.

The producers are pure and offline-testable: providers are injected via
``fetch_fn``, timestamps come from the caller's ``now``, and credentials are
read only inside the odds producer's call-time branch (never at import).

Failure is always folded into the returned row -- a producer never raises, so a
missing provider or a parser error can never abort results ingestion.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from football_core.predictors.odds import fetch_and_cache_odds
from football_core.signal import PredictionContext
from football_core.signals.rest_days import RestDaysSignal
from football_core.signals.rolling_form import RollingFormSignal
from football_core.signals.squad_value import SquadValueSignal

from competitions.worldcup.src import constants
from competitions.worldcup.src.state import (
    is_cache_valid,
    load_signal_cache,
    load_team_values,
    save_signal_cache,
)

logger = logging.getLogger(__name__)

ROW_KEY_ODDS = "signals.odds"
ROW_KEY_ROLLING_FORM = "signals.rolling_form"
ROW_KEY_SQUAD_VALUE = "signals.squad_value"
ROW_KEY_REST_DAYS = "signals.rest_days"

LABEL_ODDS = "Market odds cache"
LABEL_ROLLING_FORM = "Rolling form cache"
LABEL_SQUAD_VALUE = "Squad value cache"
LABEL_REST_DAYS = "Rest days cache"

STATE_SNAPSHOT_DETAIL = "snapshot mode selected at startup; not attempted"
STATE_NO_PROVIDER_DETAIL = "no odds provider configured"


# ── small shared helpers ─────────────────────────────────────────────────


def _load(data_dir: Path, name: str):
    """Read one JSON file; missing/corrupt returns ``{}`` (never raises)."""
    path = Path(data_dir) / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _clamp(value: float) -> float:
    return max(1e-15, min(1 - 1e-15, value))


def _match_date(match: dict) -> str | None:
    return match.get("event_date") or match.get("date") or match.get("completed_at")


def _wrap(matches: dict, now: datetime, ttl_hours: int) -> dict:
    return {
        "fetched_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=ttl_hours)).isoformat(),
        "matches": matches,
    }


def _available(probability: float, draw: float, timestamp: str) -> dict:
    return {
        "probability": _clamp(probability),
        "draw_probability": draw,
        "timestamp": timestamp,
        "available": True,
    }


def _unavailable(reason: str, timestamp: str) -> dict:
    return {
        "probability": None,
        "timestamp": timestamp,
        "available": False,
        "reason": reason,
    }


def _signal_matches(data_dir: Path) -> list[dict]:
    """Group fixtures + *resolved* bracket entries (the deleted adapters' set)."""
    groups = _load(data_dir, "groups.json")
    groups_data = groups.get("groups", groups) if isinstance(groups, dict) else {}
    matches: list[dict] = []
    for group in groups_data.values():
        if isinstance(group, dict):
            matches.extend(group.get("matches", []))
    bracket = _load(data_dir, "bracket.json")
    if isinstance(bracket, list):
        matches.extend(
            m
            for m in bracket
            if isinstance(m, dict)
            and m.get("team_a") is not None
            and m.get("team_b") is not None
        )
    return matches


class _FixtureResultsProvider:
    """``ResultHistoryProvider`` over the committed played fixtures.

    ``RollingFormSignal`` takes historical results through this protocol
    (``football_core/provider.py``); rows are indexed by team and ordered
    most-recent-first, the order the signal's stable sort relies on when a
    match carries no ``event_date``.
    """

    def __init__(self, played: dict, played_groups: dict) -> None:
        self._by_team: dict[str, list[dict]] = {}
        for match in list(played.values()) + list(played_groups.values()):
            if not isinstance(match, dict):
                continue
            for team in (match.get("team_a"), match.get("team_b")):
                if team:
                    self._by_team.setdefault(team, []).append(
                        {
                            "winner": match.get("winner"),
                            "is_draw": match.get("is_draw", False),
                            "completed_at": match.get("completed_at", ""),
                        }
                    )
        for rows in self._by_team.values():
            rows.sort(key=lambda r: r.get("completed_at", ""), reverse=True)

    def get_team_results(
        self, team: str, before_date: str, limit: int = 10
    ) -> list[dict]:
        rows = [
            r
            for r in self._by_team.get(team, [])
            if r.get("completed_at", "") < before_date
        ]
        return rows[:limit]


def _row(key: str, label: str, state: str, count: int | None, detail: str) -> dict:
    return {"key": key, "label": label, "state": state, "count": count, "detail": detail}


# ── odds producer ────────────────────────────────────────────────────────


def _store_odds(events: list[dict], data_dir: Path, now: datetime):
    from football_core.fetcher import _build_alias_lookup

    groups_raw = _load(data_dir, "groups.json")
    bracket = _load(data_dir, "bracket.json")
    bracket = bracket if isinstance(bracket, list) else []
    aliases = _load(data_dir, "team_aliases.json")
    aliases = aliases if isinstance(aliases, dict) else {}
    alias_lookup = _build_alias_lookup(aliases, bracket)

    cache = fetch_and_cache_odds(
        "",
        events,
        alias_lookup,
        groups_raw,
        cache_ttl_hours=constants.ODDS_CACHE_TTL_HOURS,
        bracket=bracket,
    )
    matches = cache.get("matches", {})
    if not matches:
        return (
            _row(
                ROW_KEY_ODDS,
                LABEL_ODDS,
                "unavailable",
                None,
                "no odds events mapped to a fixture",
            ),
            None,
        )
    save_signal_cache(cache, constants.ODDS_CACHE_FILE, data_dir)
    available = sum(1 for entry in matches.values() if entry.get("available"))
    return (
        _row(
            ROW_KEY_ODDS,
            LABEL_ODDS,
            "ok",
            available,
            f"{available} fixtures with market odds cached",
        ),
        data_dir / constants.ODDS_CACHE_FILE,
    )


def _produce_odds_cache(data_dir: Path, *, now: datetime, fetch_fn=None):
    filename = constants.ODDS_CACHE_FILE
    existing = load_signal_cache(filename, data_dir)
    if is_cache_valid(existing, constants.ODDS_CACHE_TTL_HOURS):
        return (
            _row(
                ROW_KEY_ODDS,
                LABEL_ODDS,
                "ok",
                None,
                f"odds cache fresh; within {constants.ODDS_CACHE_TTL_HOURS}h TTL",
            ),
            None,
        )

    if fetch_fn is not None:
        try:
            events = list(fetch_fn() or [])
        except Exception as exc:  # noqa: BLE001 - folded into the row, never raised
            logger.warning("odds producer fetch_fn failed: %r", exc)
            return _row(
                ROW_KEY_ODDS, LABEL_ODDS, "error", None, type(exc).__name__
            ), None
        return _store_odds(events, data_dir, now)

    import os

    from football_core.odds import resolve_odds_provider

    mode = (os.environ.get("ODDS_PROVIDER") or "").strip().lower()
    name, provider = resolve_odds_provider(mode=mode)
    if provider is None:
        return (
            _row(
                ROW_KEY_ODDS,
                LABEL_ODDS,
                "unavailable",
                None,
                STATE_NO_PROVIDER_DETAIL,
            ),
            None,
        )
    try:
        events = list(provider.fetch_events("world_cup") or [])
    except Exception as exc:  # noqa: BLE001 - folded into the row, never raised
        logger.warning("odds provider %r raised: %r", name, exc)
        return _row(ROW_KEY_ODDS, LABEL_ODDS, "error", None, type(exc).__name__), None
    return _store_odds(events, data_dir, now)


def produce_odds_cache(data_dir, *, now: datetime, fetch_fn=None) -> dict:
    """Produce the odds cache; returns the truthful stage row."""
    row, _ = _produce_odds_cache(Path(data_dir), now=now, fetch_fn=fetch_fn)
    return row


# ── local producers (kernel signals over committed fixtures) ─────────────


def _produce_rolling_form_cache(data_dir: Path, *, now: datetime):
    filename = constants.ROLLING_FORM_CACHE_FILE
    existing = load_signal_cache(filename, data_dir)
    if is_cache_valid(existing, constants.LOCAL_SIGNAL_CACHE_TTL_HOURS):
        return (
            _row(
                ROW_KEY_ROLLING_FORM,
                LABEL_ROLLING_FORM,
                "ok",
                None,
                f"cache fresh; within {constants.LOCAL_SIGNAL_CACHE_TTL_HOURS}h TTL",
            ),
            None,
        )

    matches = _signal_matches(data_dir)
    provider = _FixtureResultsProvider(
        _load(data_dir, "played.json"), _load(data_dir, "played_groups.json")
    )
    signal = RollingFormSignal(result_provider=provider, windows=[5], decay_factor=0.9)
    context = PredictionContext(fixtures=list(matches), elo_ratings={})
    timestamp = now.isoformat()
    entries: dict[str, dict] = {}
    for match in matches:
        mid = match.get("match_id")
        if not mid:
            continue
        try:
            out = signal.predict(match, context)
            entries[mid] = _available(out.home_prob, out.draw_prob, timestamp)
        except Exception:  # noqa: BLE001 - per-entry fallback, never raised
            entries[mid] = _unavailable("error", timestamp)

    save_signal_cache(
        _wrap(entries, now, constants.LOCAL_SIGNAL_CACHE_TTL_HOURS), filename, data_dir
    )
    return (
        _row(
            ROW_KEY_ROLLING_FORM,
            LABEL_ROLLING_FORM,
            "ok",
            len(entries),
            f"{len(entries)} fixtures cached",
        ),
        data_dir / filename,
    )


def produce_rolling_form_cache(data_dir, *, now: datetime) -> dict:
    """Produce the rolling-form cache; returns the truthful stage row."""
    row, _ = _produce_rolling_form_cache(Path(data_dir), now=now)
    return row


def _produce_squad_value_cache(data_dir: Path, *, now: datetime):
    filename = constants.SQUAD_VALUE_CACHE_FILE
    existing = load_signal_cache(filename, data_dir)
    if is_cache_valid(existing, constants.SQUAD_VALUE_CACHE_TTL_HOURS):
        return (
            _row(
                ROW_KEY_SQUAD_VALUE,
                LABEL_SQUAD_VALUE,
                "ok",
                None,
                f"cache fresh; within {constants.SQUAD_VALUE_CACHE_TTL_HOURS}h TTL",
            ),
            None,
        )

    matches = _signal_matches(data_dir)
    team_values = load_team_values(data_dir)
    signal = SquadValueSignal()
    context = PredictionContext(
        fixtures=list(matches), elo_ratings={}, squad_values=team_values
    )
    timestamp = now.isoformat()
    entries: dict[str, dict] = {}
    for match in matches:
        mid = match.get("match_id")
        if not mid:
            continue
        team_a = match.get("team_a", "")
        team_b = match.get("team_b", "")
        if team_a not in team_values:
            entries[mid] = _unavailable(f"team_value_not_found: {team_a}", timestamp)
            continue
        if team_b not in team_values:
            entries[mid] = _unavailable(f"team_value_not_found: {team_b}", timestamp)
            continue
        try:
            out = signal.predict(match, context)
            entries[mid] = _available(out.home_prob, out.draw_prob, timestamp)
        except Exception:  # noqa: BLE001 - per-entry fallback, never raised
            entries[mid] = _unavailable("error", timestamp)

    save_signal_cache(
        _wrap(entries, now, constants.SQUAD_VALUE_CACHE_TTL_HOURS), filename, data_dir
    )
    return (
        _row(
            ROW_KEY_SQUAD_VALUE,
            LABEL_SQUAD_VALUE,
            "ok",
            len(entries),
            f"{len(entries)} fixtures cached",
        ),
        data_dir / filename,
    )


def produce_squad_value_cache(data_dir, *, now: datetime) -> dict:
    """Produce the squad-value cache; returns the truthful stage row."""
    row, _ = _produce_squad_value_cache(Path(data_dir), now=now)
    return row


def _produce_rest_days_cache(data_dir: Path, *, now: datetime):
    filename = constants.REST_DAYS_CACHE_FILE
    existing = load_signal_cache(filename, data_dir)
    if is_cache_valid(existing, constants.LOCAL_SIGNAL_CACHE_TTL_HOURS):
        return (
            _row(
                ROW_KEY_REST_DAYS,
                LABEL_REST_DAYS,
                "ok",
                None,
                f"cache fresh; within {constants.LOCAL_SIGNAL_CACHE_TTL_HOURS}h TTL",
            ),
            None,
        )

    matches = _signal_matches(data_dir)
    signal = RestDaysSignal()
    context = PredictionContext(fixtures=list(matches), elo_ratings={})
    timestamp = now.isoformat()
    entries: dict[str, dict] = {}
    for match in matches:
        mid = match.get("match_id")
        if not mid:
            continue
        if not _match_date(match):
            entries[mid] = _unavailable("no_date_info", timestamp)
            continue
        try:
            out = signal.predict(match, context)
            entries[mid] = _available(out.home_prob, out.draw_prob, timestamp)
        except Exception:  # noqa: BLE001 - per-entry fallback, never raised
            entries[mid] = _unavailable("error", timestamp)

    save_signal_cache(
        _wrap(entries, now, constants.LOCAL_SIGNAL_CACHE_TTL_HOURS), filename, data_dir
    )
    return (
        _row(
            ROW_KEY_REST_DAYS,
            LABEL_REST_DAYS,
            "ok",
            len(entries),
            f"{len(entries)} fixtures cached",
        ),
        data_dir / filename,
    )


def produce_rest_days_cache(data_dir, *, now: datetime) -> dict:
    """Produce the rest-days cache; returns the truthful stage row."""
    row, _ = _produce_rest_days_cache(Path(data_dir), now=now)
    return row


# ── the four-row orchestrator ────────────────────────────────────────────


def _snapshot_rows() -> list[dict]:
    return [
        _row(ROW_KEY_ODDS, LABEL_ODDS, "unavailable", None, STATE_SNAPSHOT_DETAIL),
        _row(
            ROW_KEY_ROLLING_FORM,
            LABEL_ROLLING_FORM,
            "unavailable",
            None,
            STATE_SNAPSHOT_DETAIL,
        ),
        _row(
            ROW_KEY_SQUAD_VALUE,
            LABEL_SQUAD_VALUE,
            "unavailable",
            None,
            STATE_SNAPSHOT_DETAIL,
        ),
        _row(
            ROW_KEY_REST_DAYS,
            LABEL_REST_DAYS,
            "unavailable",
            None,
            STATE_SNAPSHOT_DETAIL,
        ),
    ]


def produce_signal_caches(
    data_dir,
    *,
    now: datetime,
    mode: str,
    fetch_fn=None,
    written_files: list | None = None,
) -> list[dict]:
    """Run all four producers once, in fixed order, returning their stage rows.

    ``mode == "snapshot"`` returns four truthful not-attempted rows and writes
    nothing (zero network). Otherwise each producer runs with its own failure
    folded into its row; ``written_files`` (when given) collects the paths that
    were actually written this pass, so the refresh ledger stays truthful.
    """
    data_dir = Path(data_dir)

    if mode == "snapshot":
        return _snapshot_rows()

    plan = (
        (ROW_KEY_ODDS, LABEL_ODDS, _produce_odds_cache, {"fetch_fn": fetch_fn}),
        (ROW_KEY_ROLLING_FORM, LABEL_ROLLING_FORM, _produce_rolling_form_cache, {}),
        (ROW_KEY_SQUAD_VALUE, LABEL_SQUAD_VALUE, _produce_squad_value_cache, {}),
        (ROW_KEY_REST_DAYS, LABEL_REST_DAYS, _produce_rest_days_cache, {}),
    )

    rows: list[dict] = []
    for key, label, producer, kwargs in plan:
        try:
            row, written = producer(data_dir, now=now, **kwargs)
        except Exception as exc:  # noqa: BLE001 - never abort the refresh
            logger.warning("signal cache producer %r failed: %r", key, exc)
            row, written = _row(key, label, "error", None, type(exc).__name__), None
        rows.append(row)
        if written is not None and written_files is not None:
            written_files.append(str(written))
    return rows
