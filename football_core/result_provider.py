"""MatchResultProvider protocol — data source abstraction for RollingFormSignal (D-09)."""

import logging
from typing import List, Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class MatchResultProviderError(Exception):
    """Raised when a result provider cannot produce results."""


@runtime_checkable
class MatchResultProvider(Protocol):
    """Provide completed match results for a team before a given date.
    Used by RollingFormSignal (D-09) for form computation.
    Implementations: BSDMatchResultProvider (BSD API) and
    ReplayMatchResultProvider (replay JSON files)."""

    def get_team_results(
        self, team: str, before_date: str, limit: int = 10
    ) -> list[dict]: ...
