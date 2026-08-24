"""Simulation contracts shared by all competitions — INTERFACE ONLY.

This module defines the boundary between:

- ``football_core.simulation`` (this layer, competition-agnostic):
  request validation, sampling, running N simulations, aggregating
  probabilities, and marking every output as SIMULATED.
- each competition brain (competitions/<id>/): deciding which matches
  remain, holding real results as immutable facts, advancing the format,
  and determining champion / qualification / final standings.

The Monte Carlo engine itself is deliberately NOT implemented here yet
(Exchange 1 establishes the contract; later exchanges implement it).

Hard product rules encoded here:

- maximum allowed simulation count is 1,000,000
- played matches are immutable facts and can never be sampled or altered
- every produced result carries SIMULATED provenance
- no simulation run means no simulated probabilities anywhere downstream

Stdlib only.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable

from football_core.domain import ResultProvenance

MAX_SIMULATIONS = 1_000_000
MIN_SIMULATIONS = 100

PROGRESS_CB = Callable[[int, int], None]
"""progress_cb(done_iterations, total_iterations) — may be called from a worker thread."""


class SimulationContractError(ValueError):
    """Raised when a simulation request violates the shared contract."""


def validate_n_simulations(n_simulations: int) -> int:
    """Validate a user-selected simulation count.

    Returns the coerced ``int``; raises :class:`SimulationContractError`
    when the value is not a positive integer within
    ``[MIN_SIMULATIONS, MAX_SIMULATIONS]``.
    """
    if isinstance(n_simulations, bool) or not isinstance(n_simulations, int):
        try:
            n_simulations = int(n_simulations)
        except (TypeError, ValueError):
            raise SimulationContractError(
                f"n_simulations must be an integer, got {n_simulations!r}"
            ) from None
    if n_simulations < MIN_SIMULATIONS:
        raise SimulationContractError(
            f"n_simulations must be >= {MIN_SIMULATIONS}, got {n_simulations}"
        )
    if n_simulations > MAX_SIMULATIONS:
        raise SimulationContractError(
            f"n_simulations must be <= {MAX_SIMULATIONS}, got {n_simulations}"
        )
    return n_simulations


@dataclass(frozen=True)
class SampledOutcome:
    """One sampled match outcome. Regulation + extra time goals; pens optional."""

    home_goals: int
    away_goals: int
    pens_home: Optional[int] = None
    pens_away: Optional[int] = None


@dataclass(frozen=True)
class SimulationRequest:
    """A validated, immutable simulation request.

    Constraints enforced at construction time:

    - ``competition_id`` / ``season`` identify the target non-empty
    - ``n_simulations`` within ``[MIN_SIMULATIONS, MAX_SIMULATIONS]``
    - ``seed`` enables reproducible runs; ``None`` means caller-chosen entropy
    - ``scenario`` carries optional user-selected counterfactual options;
      it must never reference already-played matches (enforced by engines)
    """

    competition_id: str
    season: str
    n_simulations: int
    seed: Optional[int] = None
    scenario: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not str(self.competition_id).strip():
            raise SimulationContractError("competition_id must be non-empty")
        if not str(self.season).strip():
            raise SimulationContractError("season must be non-empty")
        object.__setattr__(
            self, "n_simulations", validate_n_simulations(self.n_simulations)
        )
        if self.seed is not None:
            object.__setattr__(self, "seed", int(self.seed))


@dataclass(frozen=True)
class SimulationRunMetadata:
    """Provenance block attached to every simulation output."""

    competition_id: str
    season: str
    n_simulations: int
    seed: Optional[int]
    engine_version: str
    generated_at_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    provenance: str = ResultProvenance.SIMULATED.value


@dataclass
class SimulationResult:
    """Aggregated output of one simulation run.

    Everything inside *aggregates* is simulated: champion odds, standings
    distributions, stage-reach probabilities. Consumers must surface this
    as projection data, never as results.
    """

    metadata: SimulationRunMetadata
    aggregates: dict[str, Any] = field(default_factory=dict)

    @property
    def is_simulated(self) -> bool:
        return self.metadata.provenance == ResultProvenance.SIMULATED.value

    def to_payload(self) -> dict:
        """JSON-safe payload that always identifies itself as simulated."""
        return {
            "provenance": self.metadata.provenance,
            "is_simulated": self.is_simulated,
            "meta": {
                "competition_id": self.metadata.competition_id,
                "season": self.metadata.season,
                "n_simulations": self.metadata.n_simulations,
                "seed": self.metadata.seed,
                "engine_version": self.metadata.engine_version,
                "generated_at_utc": self.metadata.generated_at_utc,
            },
            "aggregates": self.aggregates,
        }


def ensure_simulated(result: SimulationResult) -> SimulationResult:
    """Guard: refuse outputs that do not declare themselves simulated."""
    if not result.is_simulated:
        raise SimulationContractError(
            "simulation output must carry SIMULATED provenance"
        )
    return result


# ── protocols (the seams competitions implement) ────────────────────────────


@runtime_checkable
class ProbabilitySource(Protocol):
    """Per-match outcome probabilities feeding the sampler.

    Returns ``(home, draw, away)`` summing to ~1.0, or ``None`` when no
    signal-based estimate is available for the match (callers then fall
    back to their declared default policy — probabilities are never
    fabricated silently).
    """

    def match_probabilities(
        self, match_id: str, team_a: str, team_b: str
    ) -> Optional[tuple[float, float, float]]: ...


@runtime_checkable
class TournamentRules(Protocol):
    """The competition brain's side of the contract.

    Implemented per competition: knows the format, which matches remain,
    and how to advance rounds. The generic engine calls these hooks; it
    never encodes tournament structure itself.
    """

    def eligible_matches(self) -> Sequence[Mapping[str, Any]]:
        """Unplayed fixtures eligible for sampling (played ones excluded)."""
        ...

    def immutable_results(self) -> Mapping[str, Mapping[str, Any]]:
        """Real played results by match_id. Engines must never alter these."""
        ...

    def apply_result(self, match_id: str, outcome: SampledOutcome) -> None:
        """Apply one sampled outcome to the competition state."""
        ...

    def advance(self) -> None:
        """Advance the tournament one round/stage using current state."""
        ...

    def champion(self) -> Optional[str]:
        """Champion once the format completes; ``None`` before that."""
        ...

    def final_standings(self) -> Sequence[Mapping[str, Any]]:
        """Final table/qualifiers once the format completes."""
        ...


@runtime_checkable
class MatchSampler(Protocol):
    """Samples one match outcome.

    Implementations own the scoreline model (e.g. Poisson from expected
    goals). When *probabilities* is ``None`` the sampler applies its own
    documented fallback; it must not invent availability metadata.
    """

    def sample(
        self,
        match: Mapping[str, Any],
        probabilities: Optional[tuple[float, float, float]],
        rng: random.Random,
    ) -> SampledOutcome: ...


@runtime_checkable
class SimulationEngine(Protocol):
    """Generic N-iteration Monte Carlo driver (implemented in a later exchange)."""

    def run(
        self,
        request: SimulationRequest,
        rules: TournamentRules,
        sampler: MatchSampler,
        probabilities: Optional[ProbabilitySource],
        progress_cb: Optional[PROGRESS_CB] = None,
    ) -> SimulationResult: ...
