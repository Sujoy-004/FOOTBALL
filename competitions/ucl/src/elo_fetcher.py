"""UCL self-calculated Elo resolver — seed + locally replayed results.

Every UCL runtime Elo rating is computed at runtime by
``football_core.elo_replay.replay_elo`` from the stored seed snapshot
(``elo_cache.json``) plus a chronologically replayed ledger of played
results dated strictly after the seed's as-of stamp. Zero network
requests in every mode (including FOOTBALL_SNAPSHOT=1); the only writes
are the sanctioned gitignored UCL Elo stores via ``football_core.state``
helpers.

The retired ClubElo fetch path does NOT survive here. Provenance is
derived from the ReplayOutcome itself (``replayed`` count), never from
any file-declared source field:

- ``self_calculated`` — the kernel replayed at least one result row;
- ``seeded`` — no row qualified for replay, so the ratings are exactly
  the stored seed values.

Seed keys may be stored under their ClubElo display identities (the
committed snapshot predates this kernel); they are translated to the
canonical competition team names via ``team_aliases.json`` (committed
DATA identity — decision 5) before replay, so kernel rows — which use
canonical names — stay eligible. Full coverage is REQUIRED of the
output: when any requested team cannot be resolved the resolver returns
``({}, None)`` (its callers degrade to their own coefficient-derived
fallback) — partial coverage would KeyError the strict-indexing Monte
Carlo engine. Never filled with a placeholder: a missing seed value is
"unavailable", not 1500.

The coefficient-derived fallback for sessions with no usable seed lives
with the callers (orchestrator/pipeline), not here.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from football_core.elo_replay import ReplayOutcome
from football_core.state import (
    load_elo_cache,
    load_elo_update_log,
    save_elo_cache,
    save_elo_update_log,
)

logger = logging.getLogger(__name__)

_UCL_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
)

_UPDATE_LOG_LIMIT = 500
"""Most recent ``elo_update_log.json`` entries to keep."""

SOURCE_SEEDED = "seeded"
SOURCE_SELF_CALCULATED = "self_calculated"


def _resolve_active_store_dir(data_dir: str | Path | None) -> str:
    """The store directory the seed lives in for this session.

    Mirrors ``orchestrator.resolve_active_data_dir``'s rule without
    importing the orchestrator (the orchestrator imports this module):
    the active season dir when a non-historical season is pointed at,
    else the passed ``data_dir`` (default ``_UCL_DATA_DIR``).
    """
    dp = Path(data_dir if data_dir is not None else _UCL_DATA_DIR)
    try:
        from competitions.ucl.src.seasons import (
            LOCAL_HISTORICAL_SEASON,
            get_current_season,
            season_dir,
        )

        current = get_current_season(dp)
        if current and isinstance(current, dict):
            active_season = current.get("season")
            if active_season and active_season != LOCAL_HISTORICAL_SEASON:
                sd = season_dir(dp, active_season)
                if sd.is_dir():
                    return str(sd)
    except Exception:  # pragma: no cover - season pointer corruption only
        logger.warning("UCL Elo store dir fell back to %s (season resolution failed)", dp)
    return str(dp)


def _canonical_seed_rankings(
    seed_values: dict, data_dir: str | Path,
) -> dict[str, float]:
    """Stored seed doc values re-keyed to canonical competition names.

    The committed snapshot may key its values by display identities of the
    era it was fetched in (ClubElo ranking names). team_aliases.json maps
    canonical team names to those alias tokens; a stored key therefore
    resolves to a canonical name when it appears in some canonical's alias
    list, and each canonical also falls back to an identity hit. Unclaimed
    stored keys stay verbatim (harmless extras the selection filter drops).
    First-wins in alias-file order — deterministic. Non-numeric values are
    dropped honestly.
    """
    import json

    own_dir = str(data_dir) if data_dir is not None else _UCL_DATA_DIR
    path = Path(own_dir) / "team_aliases.json"
    mapping: dict[str, list[str]] = {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            mapping = {k: [a for a in (v or []) if isinstance(a, str)]
                       for k, v in raw.items() if isinstance(k, str)}
    except (OSError, ValueError) as exc:
        logger.warning(
            "team_aliases.json unreadable at %s (%s) — seed translation "
            "degrades to identity", path, exc)

    seed_of: dict[str, float] = {}
    for token, value in seed_values.items():
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            seed_of.setdefault(str(token), float(value))

    rekeyed: dict[str, float] = {}
    claimed: set[str] = set()
    for canonical, tokens in mapping.items():
        if canonical in rekeyed:
            continue
        for token in tuple(tokens) + (canonical,):
            if token in rekeyed or token in claimed:
                continue
            value = seed_of.get(token)
            if value is not None:
                rekeyed[canonical] = value
                claimed.add(token)
                break
    for token, value in seed_of.items():
        if token not in claimed and token not in rekeyed:
            rekeyed[token] = value
    return rekeyed


def _read_seed(data_dir: str | Path) -> dict:
    """Stored seed cache, or ``{}`` when missing/corrupt (graceful)."""
    try:
        cache = load_elo_cache(data_dir)
    except Exception:
        logger.warning("UCL elo_cache.json unreadable — treating as absent")
        return {}
    return cache if isinstance(cache, dict) else {}


def _candidate_rows(active_dir: str, root_dir: str) -> list[dict]:
    """Normalize result rows from BOTH stores into the kernel row contract.

    Season-routed ``results.json`` first, then the root store: each row
    becomes ``{team_a, team_b, home_score, away_score, date}`` where
    ``date`` is the row's ``event_date``/``completed_at`` or ``""``. The
    ``winner`` key is deliberately omitted — the kernel derives it from
    the scores.
    """
    import json

    rows: list[dict] = []
    seen: set[str] = set()
    for base in (active_dir, root_dir):
        path = Path(base) / "results.json"
        if not path.exists():
            continue
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
            matches = payload.get("matches", []) if isinstance(payload, dict) else payload
            if not isinstance(matches, list):
                continue
        except (OSError, ValueError):
            logger.warning("UCL results.json unreadable at %s — skipped for replay", path)
            continue
        for row in matches:
            if not isinstance(row, dict):
                continue
            match_id = row.get("match_id")
            if isinstance(match_id, str) and match_id:
                if match_id in seen:
                    continue
                seen.add(match_id)
            rows.append({
                "team_a": row.get("team_a"),
                "team_b": row.get("team_b"),
                "home_score": row.get("home_score"),
                "away_score": row.get("away_score"),
                "date": row.get("event_date") or row.get("completed_at") or "",
            })
    return rows


def compute_elo_outcome(
    team_names: list[str],
    data_dir: str | Path | None = None,
) -> tuple[dict[str, float], ReplayOutcome | None]:
    """Kernel outcome for *team_names*: seed + locally replayed results.

    Loads the seed snapshot from ``elo_cache.json`` (in the resolved
    active store dir), re-keys the stored values to canonical team names
    (see :func:`_canonical_seed_rankings`), replays every date-carrying
    played result dated strictly after the seed's ``fetched_at`` through
    ``football_core.elo_replay`` (base K 30), and returns the requested
    teams' values TOGETHER with the raw ReplayOutcome so callers can
    derive provenance from the actual ``replayed`` count (T-quick-02:
    never from a file-declared source field).

    Coverage is all-or-nothing: when any requested team has no resolved
    value, the return is ``({}, None)``. The kernel simulation consumers
    index ratings for every fixture team strictly, and a fabricated
    1500.0 fill is not honest data — so an incomplete seed degrades to
    the caller's coefficient fallback instead of leaking a partial dict.

    Returns ``({}, None)`` when no seed exists — the caller degrades to
    its own coefficient-derived fallback for that session.
    """
    from football_core.elo_replay import replay_elo

    root_dir = str(data_dir if data_dir is not None else _UCL_DATA_DIR)
    active_dir = _resolve_active_store_dir(data_dir)
    seed_doc = _read_seed(active_dir) or _read_seed(root_dir)
    seed_values = seed_doc.get("values") if isinstance(seed_doc, dict) else None
    if not isinstance(seed_values, dict) or not seed_values:
        return {}, None
    # The seed lives in exactly one store; persist back to the SAME
    # document we read (competitions/ucl/data/elo_cache.json at HEAD),
    # never a second per-season copy. Same for the alias file: committed
    # DATA lives in the root club dir.
    seed_dir = active_dir if _read_seed(active_dir) else root_dir

    seed = _canonical_seed_rankings(seed_values, root_dir)
    if not seed:
        return {}, None

    seed_fetched_at = seed_doc.get("fetched_at")
    outcome = replay_elo(
        seed,
        seed_fetched_at if isinstance(seed_fetched_at, str) else "",
        _candidate_rows(active_dir, root_dir),
        base_k=30,
    )

    selected = {team: outcome.ratings[team] for team in team_names if team in outcome.ratings}
    if team_names and len(selected) != len(set(team_names)):
        # Full-or-nothing (module docstring): the strict-indexing runtime
        # can never receive a partial dict.
        return {}, None

    stored = dict(seed)
    if outcome.replayed > 0 or outcome.ratings != stored:
        stamp = outcome.as_of or datetime.now(timezone.utc).isoformat()
        _persist(
            seed_dir,
            {
                "fetched_at": stamp,
                "source": SOURCE_SELF_CALCULATED if outcome.replayed else SOURCE_SEEDED,
                "values": outcome.ratings,
            },
            outcome.ratings,
            stored,
            stamp,
        )
    return selected, outcome


def compute_self_calculated_elos(
    team_names: list[str],
    data_dir: str | Path | None = None,
) -> dict[str, float]:
    """Runtime Elo ratings for *team_names*: seed + locally replayed results.

    Thin view over :func:`compute_elo_outcome` for callers that only
    need the values (pipeline, simulation, web apps).
    """
    ratings, _outcome = compute_elo_outcome(team_names, data_dir)
    return ratings


def _persist(active_dir: str, cache_doc: dict, values: dict, stored: dict, stamp: str) -> None:
    """Persist the computed cache + per-team drift entries to the update log."""
    save_elo_cache(cache_doc, active_dir)
    log = load_elo_update_log(active_dir)
    source = cache_doc["source"]
    for team, value in values.items():
        previous = stored.get(team)
        if previous is not None and float(previous) != float(value):
            log.append({
                "timestamp": stamp,
                "team": team,
                "old_value": float(previous),
                "new_value": float(value),
                "source": source,
                "reason": "scheduled_refresh",
                "drift_magnitude": round(float(value) - float(previous), 4),
            })
    if len(log) > _UPDATE_LOG_LIMIT:
        log = log[-_UPDATE_LOG_LIMIT:]
    if log:
        # Only touch the log file when there is something in it: a cold
        # cache or an unchanged replay should not leave an empty "log".
        save_elo_update_log(log, active_dir)


def elo_computed_at(data_dir: str | Path | None = None) -> str:
    """When the stored UCL ratings were computed, or ``""`` if there are none."""
    doc = _read_seed(_resolve_active_store_dir(data_dir))
    fetched_at = doc.get("fetched_at") if isinstance(doc, dict) else None
    return fetched_at if isinstance(fetched_at, str) else ""
