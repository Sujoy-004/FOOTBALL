"""Simulation contracts and the generic Monte Carlo engine.

This module defines the boundary between:

- ``football_core.simulation`` (this layer, competition-agnostic):
  request validation, run-count limits (max 1,000,000), isolated seeded
  RNG ownership, repeated simulation execution, aggregation of small
  per-run outcome summaries, provenance metadata, and fail-fast errors.
- each competition brain (competitions/<id>/): deciding which matches
  exist and remain, holding real results as immutable facts, advancing
  the format, and determining champion / qualification / standings.
  The engine never knows what a group, a Swiss league phase, a playoff,
  or a FIFA bracket is.

Hard product rules encoded here:

- maximum allowed simulation count is 1,000,000; counts are validated,
  never silently clamped
- played matches are immutable facts and can never be sampled or altered
- every produced result carries SIMULATED provenance
- no simulation run means no simulated probabilities anywhere downstream
- one invalid competition state fails the whole run with a clear error;
  partial results are never emitted

Stdlib only.
"""

from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence, runtime_checkable

from football_core.domain import ResultProvenance

MAX_SIMULATIONS = 1_000_000
MIN_SIMULATIONS = 1

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
    """Generic N-iteration Monte Carlo driver."""

    def run(
        self,
        request: SimulationRequest,
        rules: Any,
        sampler: Optional[MatchSampler] = None,
        probabilities: Optional[ProbabilitySource] = None,
        progress_cb: Optional[PROGRESS_CB] = None,
    ) -> SimulationResult: ...


# ═══════════════════════════════════════════════════════════════════════════
# Generic engine machinery (Exchange 3)
#
# Division of labor:
#   MonteCarloEngine (this module): validates the request, resolves and owns
#   an isolated seeded RNG, executes N repetitions, aggregates the small
#   outcome summaries produced by the rules, attaches provenance metadata,
#   and fails fast on any rules error (never partial results).
#   SimulationRules (competition adapters): realize ONE complete tournament
#   per call using the context RNG, condition on immutable real results,
#   and return a small JSON-safe summary dict per run.
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RunContext:
    """Everything one tournament realization may consume.

    ``rng`` is owned by the engine for this request. ``sampler`` and
    ``probabilities`` are optional injections; rules fall back to their own
    documented mechanics when absent. Rules must treat every member as
    read-only except consuming randomness.
    """

    rng: random.Random
    request: SimulationRequest
    sampler: Optional[MatchSampler] = None
    probabilities: Optional[ProbabilitySource] = None


@runtime_checkable
class Aggregation(Protocol):
    """Generic aggregation seam: count what the competition returns.

    The engine never interprets summary structure — it only feeds each
    completed run's summary to every declared aggregation and collects
    their :meth:`result` payloads at the end.
    """

    def add(self, summary: Mapping[str, Any]) -> None: ...

    def result(self) -> Any: ...


def _summary_team_list(summary: Mapping[str, Any], field_name: str) -> list[str]:
    value = summary.get(field_name) or []
    if isinstance(value, str):
        return [value]
    return [str(t) for t in value]


class ValueCounter:
    """Counts occurrences of a scalar summary field (e.g. champion team)."""

    def __init__(self, field_name: str) -> None:
        self._field = field_name
        self._counts: dict[str, int] = {}
        self._n = 0

    def add(self, summary: Mapping[str, Any]) -> None:
        self._n += 1
        value = summary.get(self._field)
        if value is None:
            return
        key = str(value)
        self._counts[key] = self._counts.get(key, 0) + 1

    def result(self) -> dict:
        return {"counts": dict(self._counts), "n": self._n}

    @property
    def counts(self) -> dict[str, int]:
        return self._counts

    @property
    def n(self) -> int:
        return self._n


class TeamListCounter:
    """Counts, per team, appearances in a list-valued summary field
    (e.g. teams that reached a given stage)."""

    def __init__(self, field_name: str) -> None:
        self._field = field_name
        self._counts: dict[str, int] = {}
        self._n = 0

    def add(self, summary: Mapping[str, Any]) -> None:
        self._n += 1
        for team in _summary_team_list(summary, self._field):
            self._counts[team] = self._counts.get(team, 0) + 1

    def result(self) -> dict:
        return {"counts": dict(self._counts), "n": self._n}


class PositionHistogram:
    """Histogram of finishing positions from ``{team: position}`` fields."""

    def __init__(self, field_name: str) -> None:
        self._field = field_name
        self._hist: dict[str, dict[int, int]] = {}

    def add(self, summary: Mapping[str, Any]) -> None:
        positions = summary.get(self._field) or {}
        if not isinstance(positions, Mapping):
            return
        for team, pos in positions.items():
            try:
                p = int(pos)
            except (TypeError, ValueError):
                continue
            bucket = self._hist.setdefault(str(team), {})
            bucket[p] = bucket.get(p, 0) + 1

    def result(self) -> dict:
        # Positions kept as native ints; json.dumps stringifies keys only at
        # serialization time, while Python consumers compute arithmetically.
        return {team: dict(buckets) for team, buckets in self._hist.items()}

    def average_and_zone_probs(self, n: int, top_cut: int, mid_cut: int) -> dict:
        """Convenience: {team: {avg_position, top_prob, middle_prob,
        bottom_prob}} computed from tallies without storing sequences."""
        out: dict[str, dict] = {}
        for team, buckets in self._hist.items():
            total = sum(buckets.values())
            if not total:
                continue
            avg = sum(p * c for p, c in buckets.items()) / total
            top = sum(c for p, c in buckets.items() if p <= top_cut) / n
            middle = sum(c for p, c in buckets.items() if top_cut < p <= mid_cut) / n
            bottom = sum(c for p, c in buckets.items() if p > mid_cut) / n
            out[team] = {
                "avg_position": avg,
                "top_prob": top,
                "middle_prob": middle,
                "bottom_prob": bottom,
            }
        return out


class TeamStatsAverages:
    """Running means of numeric per-team stat dicts
    (``{team: {stat: number}}``) without storing per-iteration values."""

    def __init__(self, field_name: str) -> None:
        self._field = field_name
        self._sums: dict[str, dict[str, float]] = {}
        self._n = 0

    def add(self, summary: Mapping[str, Any]) -> None:
        stats = summary.get(self._field) or {}
        if not isinstance(stats, Mapping):
            return
        self._n += 1
        for team, values in stats.items():
            if not isinstance(values, Mapping):
                continue
            bucket = self._sums.setdefault(str(team), {})
            for stat, value in values.items():
                try:
                    bucket[stat] = bucket.get(stat, 0.0) + float(value)
                except (TypeError, ValueError):
                    continue

    def result(self) -> dict:
        if not self._n:
            return {}
        return {
            team: {stat: round(total / self._n, 6) for stat, total in values.items()}
            for team, values in self._sums.items()
        }


class LadderCounter:
    """Counts the best stage attained per team against a declared ladder
    order (e.g. eliminated < playoff < r16 < qf < sf < final < champion)."""

    def __init__(self, field_name: str, order: Sequence[str]) -> None:
        self._field = field_name
        self._index = {name: i for i, name in enumerate(order)}
        self._counts: dict[str, dict[int, int]] = {}
        self._order = tuple(order)

    def add(self, summary: Mapping[str, Any]) -> None:
        ladder = summary.get(self._field) or {}
        if not isinstance(ladder, Mapping):
            return
        for team, stage in ladder.items():
            idx = self._index.get(str(stage))
            if idx is None:
                continue
            bucket = self._counts.setdefault(str(team), {})
            bucket[idx] = bucket.get(idx, 0) + 1

    def result(self) -> dict:
        """``{team: {stage_name: exact_best_stage_count}}``."""
        out: dict[str, dict] = {}
        for team, buckets in self._counts.items():
            out[team] = {
                name: buckets.get(idx, 0)
                for name, idx in self._index.items()
            }
        return out

    def reached_probabilities(self, n: int) -> dict[str, dict[str, float]]:
        """Cumulative variant: P(best-attained stage >= name) per team."""
        out: dict[str, dict[str, float]] = {}
        for team, buckets in self._counts.items():
            entry = {}
            for name, idx in self._index.items():
                reached = sum(c for i, c in buckets.items() if i >= idx)
                entry[f"reached_{name}"] = reached / n if n else 0.0
            out[team] = entry
        return out


@runtime_checkable
class SimulationRules(Protocol):
    """The engine-facing contract for a competition brain.

    ``declare_aggregations`` returns ``{name: Aggregation factory}``; the
    engine instantiates them once per request and feeds every run summary.

    ``simulate_one`` must realize exactly one complete, independent
    tournament using ``context.rng``, honoring real played results as
    immutable facts, and return a small JSON-safe summary (champion,
    reached-stage team lists, position map, stat averages, ...).
    """

    def declare_aggregations(self) -> Mapping[str, Callable[[], Aggregation]]: ...

    def simulate_one(self, context: RunContext) -> Mapping[str, Any]: ...

    def provenance_attestation(self) -> Mapping[str, Any]: ...


def generate_seed() -> int:
    """Generate a reproducible-recordable seed independent of global state."""
    return int.from_bytes(os.urandom(8), "big") & ((1 << 63) - 1)


class MonteCarloEngine:
    """Competition-agnostic repeated-run driver.

    Owns: validation (no clamping; max 1,000,000), seed resolution
    (explicit or generated-and-returned), an isolated ``random.Random``
    instance per request, N-repetition execution, generic aggregation via
    declared :class:`Aggregation` objects, provenance metadata, and
    fail-fast error semantics (any rules exception aborts the whole run;
    partial results are never emitted).
    """

    ENGINE_VERSION = "monte-carlo-v1"

    def __init__(self, sampler: Optional[MatchSampler] = None) -> None:
        self._sampler = sampler

    def run(
        self,
        request: SimulationRequest,
        rules: Any,
        probabilities: Optional[ProbabilitySource] = None,
        progress_cb: Optional[PROGRESS_CB] = None,
    ) -> SimulationResult:
        n = validate_n_simulations(request.n_simulations)

        seed = request.seed if request.seed is not None else generate_seed()
        rng = random.Random(seed)  # isolated; global random state untouched

        factories = dict(rules.declare_aggregations())
        aggregations: dict[str, Aggregation] = {
            name: make() for name, make in factories.items()
        }

        attestation: Mapping[str, Any] = {}
        attest_fn = getattr(rules, "provenance_attestation", None)
        if callable(attest_fn):
            attestation = attest_fn() or {}

        context = RunContext(
            rng=rng, request=request,
            sampler=self._sampler, probabilities=probabilities,
        )

        report_every = max(1, n // 200)
        for done in range(1, n + 1):
            # Fail fast: any invalid competition state aborts the entire run.
            summary = rules.simulate_one(context)
            for agg in aggregations.values():
                agg.add(summary)
            if progress_cb is not None and (
                done % report_every == 0 or done == 1 or done == n
            ):
                progress_cb(done, n)

        aggregates: dict[str, Any] = {
            name: agg.result() for name, agg in aggregations.items()
        }
        aggregates["n_simulations"] = n
        aggregates["seed"] = seed
        if attestation:
            aggregates["provenance"] = dict(attestation)

        metadata = SimulationRunMetadata(
            competition_id=request.competition_id,
            season=request.season,
            n_simulations=n,
            seed=seed,
            engine_version=self.ENGINE_VERSION,
            provenance=ResultProvenance.SIMULATED.value,
        )
        result = SimulationResult(metadata=metadata, aggregates=aggregates)
        ensure_simulated(result)
        return result
