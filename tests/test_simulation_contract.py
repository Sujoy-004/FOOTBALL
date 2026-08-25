"""Focused tests for the shared simulation contract (football_core.simulation).

Exchange 1 establishes the INTERFACE only: bounds, immutability, provenance
and protocol shapes. The Monte Carlo engine itself arrives in a later
exchange and must satisfy these contracts.
"""

import random

import pytest

from football_core.domain import ResultProvenance
from football_core.simulation import (
    MAX_SIMULATIONS,
    MIN_SIMULATIONS,
    Aggregation,
    SimulationContractError,
    SimulationRequest,
    SimulationResult,
    SimulationRunMetadata,
    ValueCounter,
    ensure_simulated,
    validate_n_simulations,
)


class TestSimulationBounds:
    def test_max_allowed_is_one_million(self):
        assert MAX_SIMULATIONS == 1_000_000

    def test_min_boundary_accepted(self):
        assert validate_n_simulations(MIN_SIMULATIONS) == MIN_SIMULATIONS

    def test_max_boundary_accepted(self):
        assert validate_n_simulations(MAX_SIMULATIONS) == MAX_SIMULATIONS

    def test_below_minimum_rejected(self):
        with pytest.raises(SimulationContractError):
            validate_n_simulations(MIN_SIMULATIONS - 1)

    def test_above_maximum_rejected(self):
        with pytest.raises(SimulationContractError):
            validate_n_simulations(MAX_SIMULATIONS + 1)

    def test_non_integer_rejected(self):
        with pytest.raises(SimulationContractError):
            validate_n_simulations("many")

    def test_numeric_string_coerced(self):
        assert validate_n_simulations("5000") == 5000


class TestSimulationRequest:
    def test_valid_request_construction(self):
        req = SimulationRequest(
            competition_id="UCL", season="2025/26",
            n_simulations=10_000, seed=42,
        )
        assert req.n_simulations == 10_000
        assert req.seed == 42

    def test_request_is_frozen(self):
        req = SimulationRequest(competition_id="WC", season="2026", n_simulations=1000)
        with pytest.raises(Exception):
            req.n_simulations = 2000  # type: ignore[misc]

    def test_request_enforces_bounds_at_construction(self):
        # Exchange 3 lowered MIN_SIMULATIONS from 100 to 1; counts below 1
        # and above the hard maximum remain invalid at construction time.
        with pytest.raises(SimulationContractError):
            SimulationRequest(competition_id="WC", season="2026", n_simulations=0)
        with pytest.raises(SimulationContractError):
            SimulationRequest(
                competition_id="WC", season="2026", n_simulations=2_000_000
            )
        assert SimulationRequest(
            competition_id="WC", season="2026", n_simulations=1
        ).n_simulations == 1

    def test_empty_competition_or_season_rejected(self):
        with pytest.raises(SimulationContractError):
            SimulationRequest(competition_id="  ", season="2026", n_simulations=1000)
        with pytest.raises(SimulationContractError):
            SimulationRequest(competition_id="UCL", season="", n_simulations=1000)


class TestAggregationProtocol:
    def _dummy_rules(self):
        class Rules:
            def declare_aggregations(self):
                return {"champion": lambda: ValueCounter("champion")}

            def simulate_one(self, ctx):
                return {"champion": "A"}

            def provenance_attestation(self):
                return {}

        return Rules()

    def test_aggregation_runtime_checkable(self):
        from football_core.simulation import MonteCarloEngine
        assert isinstance(ValueCounter("x"), Aggregation)

    def test_minimal_rules_object_drives_the_real_engine(self):
        """The only contract a competition must satisfy."""
        import random as _random
        from football_core.simulation import MonteCarloEngine, RunContext

        rules = self._dummy_rules()

        def simulate_one(ctx: RunContext):
            return {"champion": "A" if ctx.rng.random() < 0.6 else "B"}
        rules.simulate_one = simulate_one
        result = MonteCarloEngine().run(
            SimulationRequest(competition_id="X", season="s",
                              n_simulations=50, seed=1),
            rules,
        )
        counts = result.aggregates["champion"]["counts"]
        assert sum(counts.values()) == 50

class TestProvenanceGuards:
    def _result_with(self, provenance: str) -> SimulationResult:
        meta = SimulationRunMetadata(
            competition_id="X", season="s", n_simulations=100,
            seed=None, engine_version="t", provenance=provenance,
        )
        return SimulationResult(metadata=meta)

    def test_default_metadata_is_simulated(self):
        result = self._result_with(ResultProvenance.SIMULATED.value)
        assert result.is_simulated
        ensure_simulated(result)

    def test_non_simulated_output_refused(self):
        result = self._result_with("official")
        assert not result.is_simulated
        with pytest.raises(SimulationContractError):
            ensure_simulated(result)
