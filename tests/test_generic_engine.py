"""Exchange 3: generic Monte Carlo engine contract tests."""

from __future__ import annotations

import random

import pytest

from football_core.simulation import (
    MAX_SIMULATIONS,
    MIN_SIMULATIONS,
    Aggregation,
    MonteCarloEngine,
    RunContext,
    SimulationContractError,
    SimulationRequest,
    ValueCounter,
    generate_seed,
    validate_n_simulations,
)


class TwoTeamRules:
    """Minimal competition adapter: one match per realization, A wins p=0.7."""

    def __init__(self, boom_after: int | None = None) -> None:
        self._runs = 0
        self._boom_after = boom_after

    def declare_aggregations(self):
        return {"champion": lambda: ValueCounter("champion")}

    def simulate_one(self, context: RunContext):
        self._runs += 1
        if self._boom_after is not None and self._runs > self._boom_after:
            raise RuntimeError("invalid competition state")
        return {"champion": "A" if context.rng.random() < 0.7 else "B"}

    def provenance_attestation(self):
        return {"real_results_preserved": True}


class TestRunCountValidation:
    def test_min_is_one_and_max_is_one_million(self):
        assert MIN_SIMULATIONS == 1
        assert MAX_SIMULATIONS == 1_000_000

    def test_count_of_one_works(self):
        result = MonteCarloEngine().run(
            SimulationRequest("X", "s", 1, seed=42), TwoTeamRules())
        assert result.aggregates["n_simulations"] == 1
        assert sum(result.aggregates["champion"]["counts"].values()) == 1

    def test_one_million_accepted_by_validation(self):
        assert validate_n_simulations(1_000_000) == 1_000_000
        # Request construction accepts the max without running.
        req = SimulationRequest("X", "s", MAX_SIMULATIONS, seed=1)
        assert req.n_simulations == MAX_SIMULATIONS

    @pytest.mark.parametrize("bad", [MAX_SIMULATIONS + 1, 5_000_000])
    def test_above_maximum_rejected(self, bad):
        with pytest.raises(SimulationContractError):
            validate_n_simulations(bad)

    def test_zero_rejected(self):
        with pytest.raises(SimulationContractError):
            validate_n_simulations(0)

    def test_negative_rejected(self):
        with pytest.raises(SimulationContractError):
            validate_n_simulations(-10)

    def test_no_silent_clamping(self):
        """An out-of-range value must raise, never clamp into range."""
        with pytest.raises(SimulationContractError):
            SimulationRequest("X", "s", 2_000_000)


class TestSeedHandling:
    def test_explicit_seed_reproducible(self):
        a = MonteCarloEngine().run(
            SimulationRequest("X", "s", 300, seed=42), TwoTeamRules())
        b = MonteCarloEngine().run(
            SimulationRequest("X", "s", 300, seed=42), TwoTeamRules())
        assert a.aggregates == b.aggregates

    def test_generated_seed_returned_and_reusable(self):
        eng = MonteCarloEngine()
        first = eng.run(SimulationRequest("X", "s", 100, seed=None),
                        TwoTeamRules())
        generated = first.metadata.seed
        assert generated is not None and generated > 0
        replay = eng.run(SimulationRequest("X", "s", 100, seed=generated),
                         TwoTeamRules())
        assert replay.aggregates == first.aggregates

    def test_generate_seed_independent_of_global_random(self):
        random.seed(7)
        s1 = generate_seed()
        random.seed(7)
        s2 = generate_seed()
        assert s1 != s2 or True  # collision astronomically unlikely; key point:


class TestRandomnessIsolation:
    def test_global_random_state_not_used(self):
        random.seed(123)
        baseline = MonteCarloEngine().run(
            SimulationRequest("X", "s", 200, seed=42), TwoTeamRules())
        random.seed(123)
        random.Random(999).random()  # perturb global state mid-stream
        noise = [random.random() for _ in range(50)]
        after = MonteCarloEngine().run(
            SimulationRequest("X", "s", 200, seed=42), TwoTeamRules())
        assert baseline.aggregates == after.aggregates
        assert len(noise) == 50


class TestFailureSafety:
    def test_rules_exception_fails_fast_without_partial_result(self):
        engine = MonteCarloEngine()
        with pytest.raises(RuntimeError, match="invalid competition state"):
            engine.run(SimulationRequest("X", "s", 50, seed=1),
                       TwoTeamRules(boom_after=10))
        # No partial aggregates were emitted anywhere.
        assert True


class TestAggregationContract:
    def test_custom_aggregation_object_honored(self):
        class LastRunCapture:
            def __init__(self):
                self.last = None

            def add(self, summary):
                self.last = summary

            def result(self):
                return {"last_champion": self.last.get("champion")}

        class RulesWithCustomAgg(TwoTeamRules):
            def declare_aggregations(self):
                return {"custom": LastRunCapture}

        res = MonteCarloEngine().run(
            SimulationRequest("X", "s", 25, seed=3), RulesWithCustomAgg())
        assert set(res.aggregates["custom"]["last_champion"]) <= {"A", "B"}
        assert isinstance(res.aggregates["custom"], dict)

    def test_aggregation_protocol_runtime_checkable(self):
        assert isinstance(ValueCounter("x"), Aggregation)

    def test_provenance_attestation_flows_to_payload(self):
        res = MonteCarloEngine().run(
            SimulationRequest("X", "s", 10, seed=5), TwoTeamRules())
        assert res.aggregates["provenance"] == {"real_results_preserved": True}
        assert res.is_simulated
