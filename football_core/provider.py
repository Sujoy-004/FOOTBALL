"""Fixture provider interface and shared types — competition-agnostic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
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
        """Validate schedule against UCL league phase constraints.

        Raises ValueError on violation. Delegates to the existing
        validate_ucl_fixtures() from competitions/ucl/src/validation.py.
        """
        from competitions.ucl.src.validation import validate_ucl_fixtures

        fixture_dict = {"schedule": asdict(self)}
        validate_ucl_fixtures(fixture_dict)


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
