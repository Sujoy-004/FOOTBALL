"""Fixture providers for UCL — BSD API primary and repo JSON fallback.

Both providers implement the FixtureProvider Protocol from football_core.
BSDFixtureProvider fetches from the BSD API with TTL caching.
RepoFixtureProvider loads from the repo fixtures.json file.
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from football_core.fetcher import fetch_raw_matches, _build_alias_lookup, normalize_team
from football_core.provider import (
    FixtureProvider,
    FixtureSchedule,
    Team,
    Match,
    FixtureProviderError,
)
from football_core.state import is_cache_valid, _atomic_write_json
from competitions.ucl.src.constants import (
    UCL_LEAGUE_ID,
    BSD_API_URL,
    CACHE_TTL_HOURS,
    CACHE_FILENAME,
)

logger = logging.getLogger(__name__)


class RepoFixtureProvider:
    """Load fixture schedule from a repo JSON file (e.g. fixtures.json)."""

    def __init__(self, fixtures_path: str) -> None:
        self._path = fixtures_path

    def load(self) -> FixtureSchedule:
        """Load, convert, validate and return a FixtureSchedule from the JSON file.

        Raises
        ------
        FileNotFoundError
            If the fixtures file does not exist.
        ValueError
            If the schedule fails validation.
        """
        with open(self._path) as f:
            data = json.load(f)
        schedule = self._dict_to_schedule(data["schedule"])
        schedule.validate()
        return schedule

    @staticmethod
    def _dict_to_schedule(schedule_dict: dict) -> FixtureSchedule:
        return FixtureSchedule.from_dict(schedule_dict)


class BSDFixtureProvider:
    """Fetch UCL fixture schedule from BSD API with TTL caching.

    Load flow:
        1. Check local TTL cache — return cached FixtureSchedule if valid
        2. Fetch raw events from BSD API via ``fetch_raw_matches()``
        3. Filter to future-dated / upcoming events only
        4. Resolve team names via alias lookup
        5. Group events by round_number into matchdays
        6. Build and validate FixtureSchedule
        7. Write cache atomically
        8. Return schedule
    """

    def __init__(
        self,
        api_key: str,
        aliases: dict[str, list[str]],
        cache_dir: str,
        teams_data: list[dict],
    ) -> None:
        self._api_key = api_key
        self._aliases = aliases
        self._cache_path = os.path.join(cache_dir, CACHE_FILENAME)
        self._teams_data = teams_data

    # ── Public API ────────────────────────────────────────────────────────

    def load(self) -> FixtureSchedule:
        """Load and return a validated FixtureSchedule.

        Uses cache-first strategy. Falls back to BSD API fetch on cache miss.
        Validates the schedule before returning.

        Raises
        ------
        FixtureProviderError
            If BSD returns no events or no events with future dates.
        """
        # 1. Check cache
        cached = self._load_cache()
        if cached is not None:
            logger.debug("Cache HIT — returning cached fixture schedule")
            return cached

        # 2. Fetch from BSD API
        logger.debug("Cache MISS — fetching from BSD API")
        raw_events = fetch_raw_matches(
            self._api_key, BSD_API_URL, UCL_LEAGUE_ID,
        )

        if not raw_events:
            raise FixtureProviderError(
                "BSD returned 0 events for UCL (league_id=7)"
            )

        # 3. Filter to future-dated / upcoming events
        future_events = self._filter_future_events(raw_events)

        if not future_events:
            raise FixtureProviderError(
                f"BSD returned {len(raw_events)} events, "
                f"0 with future dates"
            )

        # 4. Build schedule from BSD events
        schedule = self._build_schedule(future_events)

        # 5. Validate
        schedule.validate()

        # 6. Cache and return
        self._save_cache(schedule)
        return schedule

    # ── Future-date filtering ─────────────────────────────────────────────

    def _filter_future_events(self, events: list[dict]) -> list[dict]:
        """Return only events with status 'upcoming' or a future event_date."""
        return [
            e
            for e in events
            if e.get("status") == "upcoming"
            or self._is_future_date(e.get("event_date", ""))
        ]

    @staticmethod
    def _is_future_date(date_str: str) -> bool:
        """Check if an ISO 8601 date string is in the future.

        Uses ``datetime.now(timezone.utc)`` for timezone-aware comparison.
        Returns False on any parse error.
        """
        if not date_str:
            return False
        try:
            dt = datetime.fromisoformat(date_str)
            return dt > datetime.now(timezone.utc)
        except (ValueError, TypeError):
            return False

    # ── Schedule building ─────────────────────────────────────────────────

    def _build_schedule(self, bsd_events: list[dict]) -> FixtureSchedule:
        """Map BSD API events to a FixtureSchedule dataclass.

        1. Builds alias lookup from self._aliases
        2. Registers all team names from self._teams_data into the lookup
        3. Normalises each event's home/away team names
        4. Groups events by ``round_number`` into matchdays
        5. Builds Team and Match objects
        """
        # Build team name lookup from aliases + teams_data
        alias_lookup = _build_alias_lookup(self._aliases, bracket=[])
        for td in self._teams_data:
            alias_lookup[td["name"].strip().lower()] = td["name"]

        # Build pot lookup
        pot_lookup: dict[str, int] = {
            td["name"]: td["pot"] for td in self._teams_data
        }

        # Normalise and group events by round_number
        matchdays: dict[int, list[Match]] = {}
        for event in bsd_events:
            home_raw = event.get("home_team", "")
            away_raw = event.get("away_team", "")
            home_norm = normalize_team(home_raw, alias_lookup)
            away_norm = normalize_team(away_raw, alias_lookup)

            if home_norm is None or away_norm is None:
                logger.warning(
                    "Skipping unmatchable teams: home=%r, away=%r",
                    home_raw, away_raw,
                )
                continue

            round_num = event.get("round_number", 1)
            match = Match(
                match_id=str(event.get("id", "")),
                team_a=home_norm,
                team_b=away_norm,
                home_pot=pot_lookup.get(home_norm, 0),
                away_pot=pot_lookup.get(away_norm, 0),
                event_date=event.get("event_date"),
            )
            if round_num not in matchdays:
                matchdays[round_num] = []
            matchdays[round_num].append(match)

        # Build teams list
        teams = [Team(**td) for td in self._teams_data]

        # Convert to ordered list of matchdays
        ordered_matchdays: list[list[Match]] = [
            matchdays[k] for k in sorted(matchdays)
        ]

        if not ordered_matchdays:
            raise FixtureProviderError(
                "No matchdays could be built from BSD events"
            )

        return FixtureSchedule(teams=teams, matchdays=ordered_matchdays)

    # ── Cache layer ───────────────────────────────────────────────────────

    def _load_cache(self) -> FixtureSchedule | None:
        """Load cached fixture schedule if the cache file exists and is valid.

        Returns
        -------
        FixtureSchedule or None
            The cached schedule if valid, None if absent or expired.
        """
        if not os.path.exists(self._cache_path):
            return None

        try:
            with open(self._cache_path) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            logger.warning("Cache file corrupt, ignoring")
            return None

        if not is_cache_valid(data, ttl_hours=CACHE_TTL_HOURS):
            logger.debug("Cache expired")
            return None

        schedule_dict = data.get("schedule")
        if schedule_dict is None:
            return None

        return self._dict_to_schedule(schedule_dict)

    def _save_cache(self, schedule: FixtureSchedule) -> None:
        """Write the fixture schedule to cache atomically.

        Cache data includes ``expires_at``, ``cached_at``, and the
        serialised ``schedule`` dict.
        """
        from dataclasses import asdict

        cache_data: dict = {
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(hours=CACHE_TTL_HOURS)
            ).isoformat(),
            "cached_at": datetime.now(timezone.utc).isoformat(),
            "schedule": asdict(schedule),
        }
        _atomic_write_json(cache_data, Path(self._cache_path))
        logger.debug("Cache written to %s", self._cache_path)

    @staticmethod
    def _dict_to_schedule(schedule_dict: dict) -> FixtureSchedule:
        return FixtureSchedule.from_dict(schedule_dict)
