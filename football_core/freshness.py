"""Sole owner of the shared freshness ledger (``web/last_refresh.json``).

D-18 / OQ5: the ledger used to be written by three modules through four
lock-less read-modify-write sites and read by four more that swallowed every
exception into ``{}``. This module is now the only writer and the canonical
reader:

* :func:`update_ledger` — one ``threading.Lock`` guards the whole
  read-modify-write, the write goes through :func:`football_core.state.
  atomic_write_text`, and any failure is logged with ``logger.exception``
  **and re-raised** so no caller can mistake a lost write for a fresh one;
* :func:`read_ledger` — corruption is reported as the explicit
  ``{"ledger": "unreadable", "detail": "<exception class>"}`` marker, never as
  ``{}`` (which is indistinguishable from "no refresh has ever run"). ``detail``
  carries the exception *class* only, never the message, so a path or token
  inside an OSError string cannot leak into an API payload;
* :func:`is_stale` — the D-12 staleness rule as a tested predicate;
* :func:`served_stale` — the same rule applied to a report that is about to
  be served, so a "fresh" claim a store has outgrown is never rendered;
* :func:`store_mtime` — the mtime probe apps feed into :func:`served_stale`.

Ground rules: stdlib + ``football_core.state`` only — no ``web`` imports and no
repo-path knowledge. Callers pass the ledger path (each keeps its own derivation
seam: ``pipeline._last_refresh_report_path``, ``ucl_app._refresh_report_path`` …),
which keeps the kernel competition-agnostic.

Schema is unchanged: one shared file with per-competition top-level keys
(``worldcup``, ``ucl``, ``ucl_seasons``, ``laliga``, ``laliga_seasons``) and the
inner fields each writer already produced — no migration.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from football_core.state import atomic_write_text

logger = logging.getLogger(__name__)

#: One lock for every read-modify-write of the shared ledger (D-18).
_LOCK = threading.Lock()

#: Value of the ``ledger`` key when the file cannot be parsed.
UNREADABLE = "unreadable"

#: Mtime comparison tolerance in seconds — FAT/exFAT timestamps are 2s
#: granular and Windows rounds, so a "just written" store can appear a moment
#: older than the ledger entry that wrote it.
MTIME_TOLERANCE_SECONDS = 1.0

PathLike = Path | str
#: A top-level key, or a key path for nested entries (``("ucl_seasons",
#: "2026/27")``) so a writer can update two ledger slots without a second,
#: unlocked read of the file.
LedgerKey = str | Sequence[str]

__all__ = [
    "MTIME_TOLERANCE_SECONDS",
    "UNREADABLE",
    "is_stale",
    "read_ledger",
    "served_stale",
    "store_mtime",
    "update_ledger",
]


def _as_path(path: PathLike) -> Path:
    return path if isinstance(path, Path) else Path(path)


def _parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp tz-aware (UTC when the offset is absent).

    The codebase emits both ``datetime.now(timezone.utc).isoformat()``
    (``+00:00``) and ``Z``-suffixed strings; every comparison in D-12 is
    tz-aware so a naive timestamp can never silently compare against an aware
    one.
    """
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _unreadable(exc: BaseException) -> dict:
    """The loud failure marker: class name only, never the message."""
    return {"ledger": UNREADABLE, "detail": exc.__class__.__name__}


def _read_unlocked(path: Path) -> dict:
    """Read and parse the ledger. Caller may or may not hold the lock.

    Never raises: a file that has never been written is legitimately ``{}``
    (nothing recorded), while anything unreadable is logged with
    ``logger.exception`` and returned as the explicit marker.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001 - the marker IS the contract
        logger.exception("freshness ledger unreadable at %s", path)
        return _unreadable(exc)
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("ledger root must be a JSON object")
    except Exception as exc:  # noqa: BLE001 - corrupt content
        logger.exception("freshness ledger unreadable at %s", path)
        return _unreadable(exc)
    return data


def read_ledger(path: PathLike) -> dict:
    """Read the shared freshness ledger under the lock.

    Args:
        path: Ledger file path, supplied by the caller (each module keeps its
            own path-derivation seam).

    Returns:
        The parsed ledger (``{}`` when the file does not exist), or
        ``{"ledger": "unreadable", "detail": "<exception class>"}`` when it
        cannot be read or parsed.
    """
    with _LOCK:
        return _read_unlocked(_as_path(path))


def _assign(payload: dict, key: LedgerKey, value: Any) -> None:
    """Set ``payload[key] = value``, descending into nested key paths."""
    if isinstance(key, str):
        payload[key] = value
        return
    parts = list(key)
    if not parts:
        raise ValueError("ledger key path must not be empty")
    node = payload
    for part in parts[:-1]:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[parts[-1]] = value


def update_ledger(path: PathLike, competition: str | Sequence[str],
                  report: dict) -> None:
    """Merge one entry into the shared ledger atomically (the only writer).

    The whole read-modify-write happens under :data:`_LOCK` and lands through
    :func:`football_core.state.atomic_write_text`, so a concurrent writer can
    never observe — or clobber — a half-updated payload.

    Args:
        path: Ledger file path, supplied by the caller.
        competition: Top-level key (``"worldcup"``, ``"ucl"``, ``"laliga"``)
            or a key path for nested entries (``("ucl_seasons", "2026/27")``).
        report: The entry to store, JSON-serialisable.

    Raises:
        Exception: Re-raised after ``logger.exception`` — a ledger write that
            did not land must never look like one that did. Callers on
            report-building paths catch this themselves (they already guard
            failures) but the log is non-negotiable.
    """
    ledger = _as_path(path)
    with _LOCK:
        try:
            payload = _read_unlocked(ledger)
            if payload.get("ledger") == UNREADABLE:
                # The read already logged; a fresh document is preferable to
                # persisting the marker as if it were ledger content.
                logger.warning(
                    "freshness ledger was unreadable; rewriting from scratch: %s",
                    ledger,
                )
                payload = {}
            _assign(payload, competition, report)
            atomic_write_text(ledger, json.dumps(payload, indent=2))
        except Exception:
            logger.exception(
                "freshness ledger update FAILED (%s[%s])", ledger, competition
            )
            raise


def is_stale(ledger_entry: dict, *, previous_last_success_at: str | None,
             store_mtime: float | None) -> bool:
    """D-12: does this ledger entry describe a STALE store?

    A store reads stale iff **any** of:

    1. ``last_success_at`` is missing or unparseable — a missing timestamp can
       never render as fresh;
    2. ``last_success_at`` did not advance past ``previous_last_success_at``
       (unchanged or moved backwards — clock skew, restored backup);
    3. the store file's mtime is more than :data:`MTIME_TOLERANCE_SECONDS`
       newer than ``last_success_at`` — an out-of-band write the ledger never
       saw (CLI backfill, ``git checkout`` of the partly-gitignored data dir).

    Args:
        ledger_entry: The per-competition ledger entry (or the unreadable
            marker, which carries no timestamp and so reads stale).
        previous_last_success_at: The value observed on the previous read;
            ``None`` on a first observation, which skips clause 2.
        store_mtime: Store file mtime (``Path.stat().st_mtime``); ``None``
            skips clause 3.

    Returns:
        ``True`` when the entry must be presented as stale.
    """
    entry = ledger_entry if isinstance(ledger_entry, dict) else {}
    raw = entry.get("last_success_at")
    if not isinstance(raw, str) or not raw.strip():
        return True  # clause 1: missing
    try:
        current = _parse_timestamp(raw)
    except ValueError:
        return True  # clause 1: unparseable is not fresh either
    if isinstance(previous_last_success_at, str) and previous_last_success_at.strip():
        try:
            previous = _parse_timestamp(previous_last_success_at)
        except ValueError:
            previous = None
        if previous is not None and current <= previous:
            return True  # clause 2: non-advancing
    if store_mtime is not None and store_mtime - current.timestamp() > MTIME_TOLERANCE_SECONDS:
        return True  # clause 3: store moved on without the ledger
    return False


def store_mtime(path: PathLike) -> float | None:
    """mtime of one factual store, or ``None`` when it cannot be stat'ed.

    ``None`` is an explicit "nothing to compare against" that the caller folds
    into :func:`served_stale` (clause 3 is skipped, the timestamp clauses still
    decide) — the freshness decision is never silently assumed either way.

    Args:
        path: Store file path, supplied by the caller (path knowledge about a
            competition's own stores stays in its app / brain).

    Returns:
        The file's mtime as an epoch float, or ``None`` when absent or
        unreadable.
    """
    try:
        return _as_path(path).stat().st_mtime
    except OSError:
        return None


def served_stale(ledger_entry: dict, store_mtimes: Sequence[float | None]) -> bool:
    """D-12 gate for a refresh report that is about to be served.

    The recorded instant is ``last_success_at`` (World Cup schema) or, when a
    schema only records the refresh instant (UCL / LaLiga), ``last_refresh`` —
    both mean "the moment the ledger last vouched for this store". An entry
    carrying neither, or an unparseable one, is stale (clause 1): it can never
    render as fresh.

    Args:
        ledger_entry: The refresh report / ledger entry being served.
        store_mtimes: mtimes of the factual stores the refresh writes, as
            :func:`store_mtime` produced them. ``None`` entries (store absent)
            and an empty sequence skip clause 3; which files to pass is the
            calling app's knowledge, not this kernel's.

    Returns:
        ``True`` when the entry must be served as stale.
    """
    entry = ledger_entry if isinstance(ledger_entry, dict) else {}
    recorded = entry.get("last_success_at") or entry.get("last_refresh")
    probe = {"last_success_at": recorded}
    newest = max((m for m in store_mtimes if isinstance(m, (int, float))), default=None)
    return is_stale(probe, previous_last_success_at=None, store_mtime=newest)
