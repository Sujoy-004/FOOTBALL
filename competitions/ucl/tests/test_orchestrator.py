"""Tests for simulation mode orchestrator."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


class TestResolvePlayedMatches:
    """Tests for orchestrator.resolve_played_matches()."""

    def test_simulate_mode_returns_none(self):
        """Default simulate mode returns None played_matches."""
        from competitions.ucl.src.orchestrator import resolve_played_matches

        class FakeArgs:
            mode = "simulate"
            replay_data = None
            api_key = None

        result = resolve_played_matches(FakeArgs(), "/data", None)
        assert result is None

    def test_replay_mode_without_data_exits(self):
        """Replay mode without --replay-data exits with error."""
        from competitions.ucl.src.orchestrator import resolve_played_matches

        class FakeArgs:
            mode = "replay"
            replay_data = None
            api_key = None

        with pytest.raises(SystemExit):
            resolve_played_matches(FakeArgs(), "/data", None)

    def test_live_mode_without_key_exits(self):
        """Live mode without API key exits with error."""
        from competitions.ucl.src.orchestrator import resolve_played_matches

        class FakeArgs:
            mode = "live"
            replay_data = None
            api_key = None

        with pytest.raises(SystemExit) as exc:
            resolve_played_matches(FakeArgs(), "/data", None)
        assert exc.value.code == 1
