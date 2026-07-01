"""Tests for Signal Protocol, SignalOutput, and SignalRegistry."""

import dataclasses
from football_core.signal import (
    Signal,
    SignalOutput,
    PredictionContext,
    SignalRegistry,
    SignalRegistryError,
)


class TestSignalProtocol:
    """Verify the Signal Protocol contract."""

    def test_signal_is_protocol(self):
        assert hasattr(Signal, "_is_protocol")

    def test_protocol_has_name_and_predict(self):
        assert "name" in Signal.__annotations__
        assert hasattr(Signal, "predict")

    def test_concrete_signal_conforms(self):
        class StubSignal:
            name: str = "stub"

            def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
                return SignalOutput(0.4, 0.3, 0.3)

        stub = StubSignal()
        assert isinstance(stub, Signal)


class TestSignalOutput:
    """Verify SignalOutput dataclass."""

    def test_fields_exist(self):
        fields = dataclasses.fields(SignalOutput)
        assert len(fields) == 3

    def test_field_names(self):
        names = [f.name for f in dataclasses.fields(SignalOutput)]
        assert names == ["home_prob", "draw_prob", "away_prob"]

    def test_construction_and_values(self):
        output = SignalOutput(0.5, 0.3, 0.2)
        assert output.home_prob == 0.5
        assert output.draw_prob == 0.3
        assert output.away_prob == 0.2

    def test_sum_near_one(self):
        output = SignalOutput(0.5, 0.3, 0.2)
        assert abs(output.home_prob + output.draw_prob + output.away_prob - 1.0) < 1e-10


class TestSignalRegistry:
    """Verify SignalRegistry operations."""

    def _make_stub(self, signal_name: str = "test") -> Signal:
        _name = signal_name

        class StubSignal:
            n = _name

            @property
            def name(self):
                return self.n

            def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
                return SignalOutput(0.4, 0.3, 0.3)

        return StubSignal()

    def test_empty_registry(self):
        reg = SignalRegistry()
        assert reg.list() == []

    def test_register_and_get(self):
        reg = SignalRegistry()
        sig = self._make_stub("test")
        reg.register(sig)
        assert reg.get("test") is sig

    def test_register_duplicate_raises(self):
        reg = SignalRegistry()
        sig = self._make_stub("dup")
        reg.register(sig)
        import pytest
        with pytest.raises(SignalRegistryError):
            reg.register(self._make_stub("dup"))

    def test_get_unknown_raises(self):
        reg = SignalRegistry()
        import pytest
        with pytest.raises(SignalRegistryError):
            reg.get("nonexistent")

    def test_list_returns_sorted(self):
        reg = SignalRegistry()
        for name in ["z", "a", "m"]:
            reg.register(self._make_stub(name))
        assert reg.list() == ["a", "m", "z"]

    def test_all_returns_all_instances(self):
        reg = SignalRegistry()
        sig_a = self._make_stub("a")
        sig_b = self._make_stub("b")
        reg.register(sig_a)
        reg.register(sig_b)
        instances = reg.all()
        assert sig_a in instances
        assert sig_b in instances

    def test_clear_empties_registry(self):
        reg = SignalRegistry()
        reg.register(self._make_stub("x"))
        reg.clear()
        assert reg.list() == []

    def test_empty_clear_does_not_raise(self):
        reg = SignalRegistry()
        reg.clear()
        assert True

    def test_evaluate_returns_dict(self):
        reg = SignalRegistry()
        reg.register(self._make_stub("sig_a"))
        reg.register(self._make_stub("sig_b"))
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        results = reg.evaluate({"match_id": "M1"}, ctx)
        assert isinstance(results, dict)
        assert len(results) == 2

    def test_evaluate_values_are_signal_output(self):
        reg = SignalRegistry()
        reg.register(self._make_stub("sig"))
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        results = reg.evaluate({"match_id": "M1"}, ctx)
        assert isinstance(results["sig"], SignalOutput)

    def test_evaluate_failing_signal_returns_uniform(self):
        class FailingSignal:
            name: str = "failing"

            def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
                msg = "intentional failure"
                raise ValueError(msg)

        reg = SignalRegistry()
        reg.register(FailingSignal())
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        results = reg.evaluate({"match_id": "M1"}, ctx)
        out = results["failing"]
        assert abs(out.home_prob - 1 / 3) < 1e-10
        assert abs(out.draw_prob - 1 / 3) < 1e-10
        assert abs(out.away_prob - 1 / 3) < 1e-10

    def test_evaluate_failing_signal_does_not_affect_others(self):
        class PassingSignal:
            name: str = "passing"

            def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
                return SignalOutput(0.6, 0.25, 0.15)

        class FailingSignal:
            name: str = "failing"

            def predict(self, match: dict, context: PredictionContext) -> SignalOutput:
                msg = "boom"
                raise RuntimeError(msg)

        reg = SignalRegistry()
        reg.register(PassingSignal())
        reg.register(FailingSignal())
        ctx = PredictionContext(fixtures=[], elo_ratings={})
        results = reg.evaluate({"match_id": "M1"}, ctx)
        passing = results["passing"]
        assert abs(passing.home_prob - 0.6) < 1e-10
        assert abs(passing.draw_prob - 0.25) < 1e-10
        assert abs(passing.away_prob - 0.15) < 1e-10
        failing = results["failing"]
        assert abs(failing.home_prob - 1 / 3) < 1e-10
