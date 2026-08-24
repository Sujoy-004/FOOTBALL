"""Fixture provider interface, DataProvider protocol, and shared types — competition-agnostic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Team:
    """A team participating in a fixture schedule."""

    name: str
    pot: int
    clubelo_name: str
    coefficient: float


@dataclass
class Match:
    """A single match within a fixture schedule."""

    match_id: str
    team_a: str
    team_b: str
    home_pot: int
    away_pot: int
    event_date: str | None = None


@dataclass
class FixtureSchedule:
    """A validated fixture schedule with teams and matchdays."""

    teams: list[Team]
    matchdays: list[list[Match]]

    @staticmethod
    def from_dict(schedule_dict: dict) -> FixtureSchedule:
        """Convert a schedule dict to a FixtureSchedule dataclass.

        Expected dict structure: ``{teams: [...], matchdays: [...]}``
        where each team dict is unpacked as ``Team(**t)`` and each
        matchday is a list of match dicts unpacked as ``Match(**m)``.
        """
        teams = [Team(**t) for t in schedule_dict["teams"]]
        matchdays = []
        for md in schedule_dict["matchdays"]:
            matches = [Match(**m) for m in md]
            matchdays.append(matches)
        return FixtureSchedule(teams=teams, matchdays=matchdays)

    def validate(self) -> None:
        """Validate the schedule structurally.

        Competition-specific validation (e.g. UCL league-phase constraints)
        is the caller's responsibility — this core method must stay
        competition-agnostic.
        """
        if not self.teams:
            raise ValueError("Schedule has no teams")
        if not self.matchdays:
            raise ValueError("Schedule has no matchdays")


@runtime_checkable
class MatchResultProvider(Protocol):
    """Protocol that all match result providers implement.

    Follows the same pattern as FixtureProvider.
    Implementations load match results from their source (JSON, BSD API, etc.)
    and return a played_matches dict for injection into the simulation engine.
    """

    def load(
        self,
    ) -> dict[tuple[str, str], tuple[int, int]]:
        """Load and return played match results.

        Returns a dict keyed by (team_a, team_b) tuple with
        (home_score, away_score) values. Both orientations are stored
        for bidirectional lookup.

        Raises FileNotFoundError, json.JSONDecodeError, or custom errors
        specific to the provider implementation.
        """
        ...


@runtime_checkable
class ResultHistoryProvider(Protocol):
    """Provide completed match results for a team before a given date.

    Used by RollingFormSignal for form computation (D-09).
    Implementations: BSDMatchResultProvider (BSD API) and
    ReplayMatchResultProvider (replay JSON files).
    """

    def get_team_results(
        self, team: str, before_date: str, limit: int = 10
    ) -> list[dict]: ...


class FixtureProviderError(Exception):
    """Raised when a provider cannot produce a valid fixture schedule."""


@runtime_checkable
class FixtureProvider(Protocol):
    """Protocol that all fixture providers implement."""

    def load(self) -> FixtureSchedule:
        """Load and return a validated FixtureSchedule.

        Raises FixtureProviderError if no valid schedule can be produced.
        """
        ...


@runtime_checkable
class DataProvider(Protocol):
    """Protocol for external data sources (match results / events).

    Returns raw list-of-dict data from the provider. Processing, caching,
    and persistence are handled by the caller. Competition identifiers are
    provider-specific (e.g. ``"WC"``, ``"CL"`` for football-data.org;
    ``"27"``, ``"7"`` for BSD league IDs).
    """

    def fetch_matches(self, competition_id: str, **kwargs) -> list[dict]:
        """Fetch match results / events for *competition_id*."""
        ...
