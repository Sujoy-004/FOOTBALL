"""ClubElo rating fetcher — competition-agnostic.

Provides cached fetching of Elo ratings from ClubElo for any list of team
names.  Team name to ClubElo name resolution uses a team_aliases.json file
supplied by the caller.

Fetch strategy
--------------
A *single* request to the ClubElo ranking page (see ``football_core.clubelo``)
returns the whole world ranking as ``{normalized slug: Elo}``. The Elo for each
team is extracted by looking up its alias (from the alias file) as a slug in
that dict. Slugs, not display names, because two clubs can share a name —
``Liverpool`` and ``LiverpoolUY`` both print as "Liverpool".

The result is cached per snapshot date, so repeated lookups on the same day
cost one request and the next day picks up a fresh ranking.

An earlier version used api.clubelo.com's dated CSV endpoint and fell back to
its per-team history endpoint. Both are dead (HTTP 502), and the per-team
fallback could only ever have masked a wrong alias anyway: with the full
ranking in hand, a miss means "no club by that name", so the caller is told
directly and falls through to its own labelled fallback.

Persistence
-----------
:func:`refresh_elos_if_stale` is the entry point for anything that wants
ratings over time rather than once: it reuses the stored snapshot while it is
recent and complete, and logs the ratings that actually moved.

Refresh happens where a rating is actually needed — boot and recompute, both
off the request path. There is no background timer: a server that stays up
across a day boundary keeps serving yesterday's ratings until the next boot
or recompute. Add a scheduled task if a long-lived process needs to track the
daily ranking without being restarted.
"""

from __future__ import annotations

import functools
import json
import logging
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from football_core.clubelo import fetch_ranking, slug_key
from football_core.constants import DEFAULT_ELO
from football_core.state import (
    load_elo_cache,
    load_elo_update_log,
    save_elo_cache,
    save_elo_update_log,
)

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def _load_aliases(alias_path: str) -> dict[str, list[str]]:
    with open(alias_path, encoding="utf-8") as f:
        return json.load(f)


def _normalized_key(name: str) -> str:
    """Accent-insensitive, lowercased key for fuzzy alias matching.

    NFKD-decomposes and strips combining diacritic marks (NFKD keeps encoded
    accented forms such as ``ø`` U+00F8 undecoded, since they have no
    decomposition — that is an honest, bounded limit of the fallback).
    """
    decomposed = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return stripped.lower()


def resolve_clubelo_name(team_name: str, alias_path: str) -> str:
    aliases = _load_aliases(alias_path)
    team_aliases = aliases.get(team_name)
    if team_aliases and len(team_aliases) > 0:
        return team_aliases[0]
    # Fallback-only, resolution-side accent-insensitive lookup. Reuses the
    # existing alias keys verbatim (no invented aliases, no data edits). Pure
    # ASCII inputs take the exact path above and are therefore byte-identical.
    normalized = _normalized_key(team_name)
    for key, values in aliases.items():
        if _normalized_key(key) == normalized and values:
            return values[0]
    return team_name


@functools.lru_cache(maxsize=1)
def _fetch_ranking(snapshot_date: str) -> dict[str, float]:
    """The whole ClubElo ranking as {normalized slug: Elo}.

    *snapshot_date* is the cache key, not a request parameter: the ranking
    page serves today's ranking regardless. Keying on the date is what
    makes this a daily refresh — a new day is a new key, so the next call
    re-fetches, while same-day callers share one request.
    """
    del snapshot_date
    return fetch_ranking()


def fetch_team_elos(
    team_names: list[str],
    alias_path: str,
    delay: float = 0.0,
) -> dict[str, float]:
    snapshot_date = get_clubelo_snapshot_date()
    ranking = _fetch_ranking(snapshot_date)

    elos: dict[str, float] = {}
    for team_name in team_names:
        clubelo_name = resolve_clubelo_name(team_name, alias_path)
        elo = ranking.get(slug_key(clubelo_name))
        if elo is not None:
            elos[team_name] = elo
        else:
            # The ranking page already holds every rated club, so a miss means
            # the alias does not name a real ClubElo entry — a data bug, not a
            # coverage gap. Say so and hand the caller an explicit placeholder
            # it can label, rather than inventing a plausible number.
            logger.warning(
                "ClubElo has no entry named '%s' (alias for team '%s') — "
                "falling back to DEFAULT_ELO=%d",
                clubelo_name, team_name, DEFAULT_ELO,
            )
            elos[team_name] = float(DEFAULT_ELO)

    return elos


def get_clubelo_snapshot_date() -> str:
    return date.today().isoformat()


# ─── Stored ratings: fetch once, reuse until something changes ──────────────

SOURCE_CLUBELO = "clubelo"

_UPDATE_LOG_LIMIT = 500
"""Most recent ``elo_update_log.json`` entries to keep."""


def _is_fresh(cache: dict, team_names: list[str], max_age_hours: float) -> bool:
    """True when *cache* is recent enough and covers every requested team.

    Coverage matters as much as age. ClubElo rates a club from its first
    top-flight appearance, so a team new to the competition has no entry
    and would sit at ``DEFAULT_ELO`` forever inside a store that is still
    "fresh". Requiring full coverage means a newly drawn team forces one
    fetch instead of being served a placeholder.

    A stored placeholder does not count as coverage either. ``fetch_team_elos``
    returns ``DEFAULT_ELO`` for a name ClubElo does not have, and writing that
    into the store would make the next call see the team present and stop
    trying — turning a missing rating into a confident-looking 1500 for the
    whole freshness window. Counting it as uncovered costs one fetch a day for
    a genuinely unrated club, and recovers automatically once it is rated.
    """
    values = cache.get("values") or {}
    if not team_names:
        return False
    for team in team_names:
        value = values.get(team)
        if value is None or float(value) == float(DEFAULT_ELO):
            return False
    fetched_at = cache.get("fetched_at")
    if not isinstance(fetched_at, str):
        return False
    try:
        stamp = datetime.fromisoformat(fetched_at)
    except ValueError:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() < max_age_hours * 3600


def elo_store_fetched_at(data_dir: Path | str | None = None) -> str:
    """ISO stamp of the stored ratings, or ``""`` when nothing is stored.

    Lets a caller label the numbers with when they were actually read, instead
    of guessing a date from the season or leaving the field blank.
    """
    fetched_at = (load_elo_cache(data_dir) or {}).get("fetched_at")
    return fetched_at if isinstance(fetched_at, str) else ""


def refresh_elos_if_stale(
    team_names: list[str],
    alias_path: str,
    data_dir: Path | str | None = None,
    max_age_hours: float = 24.0,
) -> dict[str, float]:
    """Ratings for *team_names*, re-fetched only when the store goes stale.

    This is the entry point for anything that wants ClubElo numbers over
    time rather than once. It reuses :func:`fetch_team_elos` for the actual
    fetch and then:

    * serves the stored snapshot while it is recent and complete;
    * writes the new ratings to ``elo_cache.json`` (atomic);
    * appends one ``elo_update_log.json`` entry per team whose rating
      actually moved, which is the "new Elo is stored when it changes" part.

    A failed fetch returns the stored ratings when there are any and raises
    nothing, so a ClubElo outage degrades to slightly stale numbers instead
    of to no numbers. With no stored ratings the error propagates and the
    caller's own labelled fallback takes over.

    The log is trimmed to :data:`_UPDATE_LOG_LIMIT` most recent entries.
    It is otherwise append-only, which would grow by up to one entry per
    team per day forever.
    """
    cache = load_elo_cache(data_dir)
    if _is_fresh(cache, team_names, max_age_hours):
        values = cache["values"]
        return {team: float(values[team]) for team in team_names}

    stored = cache.get("values") or {}
    try:
        ratings = fetch_team_elos(team_names, alias_path)
    except Exception:
        # Stale numbers beat no numbers, but only if they are numbers for the
        # teams being asked about. Serving a partial set here would look like
        # success to the caller (it labels anything non-empty as ClubElo) while
        # quietly dropping a team, so re-raise and let the caller's own
        # labelled fallback cover the whole set instead.
        if all(team in stored for team in team_names):
            logger.warning(
                "ClubElo refresh failed; serving the %d stored ratings",
                len(stored),
            )
            return {team: float(stored[team]) for team in team_names}
        raise

    stamp = datetime.now(timezone.utc).isoformat()
    save_elo_cache(
        {"fetched_at": stamp, "source": SOURCE_CLUBELO, "values": ratings},
        data_dir,
    )

    log = load_elo_update_log(data_dir)
    for team, value in ratings.items():
        previous = stored.get(team)
        if previous is not None and float(previous) != float(value):
            log.append({
                "timestamp": stamp,
                "team": team,
                "old_value": float(previous),
                "new_value": float(value),
                "source": SOURCE_CLUBELO,
                "reason": "scheduled_refresh",
                "drift_magnitude": round(float(value) - float(previous), 4),
            })
    if len(log) > _UPDATE_LOG_LIMIT:
        log = log[-_UPDATE_LOG_LIMIT:]
    if log:
        # Only touch the file when there is something in it: a cold cache or an
        # unchanged ranking should not leave behind an empty "log".
        save_elo_update_log(log, data_dir)
    return ratings
