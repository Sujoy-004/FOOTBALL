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
    MatchSampler,
    ProbabilitySource,
    SampledOutcome,
    SimulationContractError,
    SimulationEngine,
    SimulationRequest,
    SimulationResult,
    SimulationRunMetadata,
    TournamentRules,
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
        with pytest.raises(SimulationContractError):
            SimulationRequest(competition_id="WC", season="2026", n_simulations=10)
        with pytest.raises(SimulationContractError):
            SimulationRequest(
                competition_id="WC", season="2026", n_simulations=2_000_000
            )

    def test_empty_competition_or_season_rejected(self):
        with pytest.raises(SimulationContractError):
            SimulationRequest(competition_id="  ", season="2026", n_simulations=1000)
        with pytest.raises(SimulationContractError):
            SimulationRequest(competition_id="UCL", season="", n_simulations=1000)


class TestProtocols:
    def _dummy_probability_source(self):
        class Src:
            def match_probabilities(self, match_id, team_a, team_b):
                return None

        return Src()

    def _dummy_rules(self):
        class Rules:
            def eligible_matches(self):
                return []

            def immutable_results(self):
                return {}

            def apply_result(self, match_id, outcome):
                pass

            def advance(self):
                pass

            def champion(self):
                return None

            def final_standings(self):
                return []

        return Rules()

    def _dummy_sampler(self):
        class Sampler:
            def sample(self, match, probabilities, rng):
                return SampledOutcome(home_goals=1, away_goals=0)

        return Sampler()

    def test_probability_source_satisfies_protocol(self):
        assert isinstance(self._dummy_probability_source(), ProbabilitySource)

    def test_tournament_rules_satisfies_protocol(self):
        assert isinstance(self._dummy_rules(), TournamentRules)

    def test_match_sampler_satisfies_protocol(self):
        assert isinstance(self._dummy_sampler(), MatchSampler)

    def test_engine_protocol_is_definable(self):
        class Engine:
            def run(self, request, rules, sampler, probabilities, progress_cb=None):
                rng = random.Random(request.seed)
                rules.apply_result(
                    "m1", sampler.sample({}, (0.4, 0.3, 0.3), rng)
                )
                rules.advance()
                return SimulationResult(
                    metadata=SimulationRunMetadata(
                        competition_id=request.competition_id,
                        season=request.season,
                        n_simulations=request.n_simulations,
                        seed=request.seed,
                        engine_version="test",
                    ),
                    aggregates={"champion_odds": {"A": 1.0}},
                )

        engine = Engine()
        assert isinstance(engine, SimulationEngine)
        result = engine.run(
            SimulationRequest(competition_id="X", season="s", n_simulations=100),
            self._dummy_rules(),
            self._dummy_sampler(),
            self._dummy_probability_source(),
        )
        assert result.is_simulated is True
        payload = result.to_payload()
        assert payload["provenance"] == "simulated"
        assert payload["meta"]["n_simulations"] == 100
        ensure_simulated(result)


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
