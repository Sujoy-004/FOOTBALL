"""Tests for config.json loading and precedence logic."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from main import _resolve_league_id


class MockArgs:
    def __init__(self, league=None):
        self.league = league
        self.list_leagues = False


class TestResolveLeagueId:
    """Unit tests for _resolve_league_id()."""

    def test_default_when_no_config(self, monkeypatch, tmp_path):
        """No config.json -> returns DEFAULT_LEAGUE_ID (27)."""
        import src.constants as c
        monkeypatch.setattr(c, "DATA_DIR", tmp_path / "data")
        (tmp_path / "data").mkdir(exist_ok=True)

        args = MockArgs(league=None)
        league_id, data_dir = _resolve_league_id(args)
        assert league_id == 27
        assert str(league_id) in str(data_dir)

    def test_config_overrides_default(self, monkeypatch, tmp_path):
        """config.json with league_id=65 -> returns 65."""
        import src.constants as c
        monkeypatch.setattr(c, "DATA_DIR", tmp_path / "data")
        (tmp_path / "data").mkdir(exist_ok=True)
        # Create config.json at project root (DATA_DIR.parent)
        config_path = tmp_path / "config.json"
        with open(config_path, "w") as f:
            json.dump({"league_id": 65}, f)

        args = MockArgs(league=None)
        league_id, data_dir = _resolve_league_id(args)
        assert league_id == 65

    def test_cli_overrides_config(self, monkeypatch, tmp_path):
        """--league CLI flag overrides config.json."""
        import src.constants as c
        monkeypatch.setattr(c, "DATA_DIR", tmp_path / "data")
        (tmp_path / "data").mkdir(exist_ok=True)
        config_path = tmp_path / "config.json"
        with open(config_path, "w") as f:
            json.dump({"league_id": 65}, f)

        args = MockArgs(league=13)  # CLI says 13
        league_id, data_dir = _resolve_league_id(args)
        assert league_id == 13  # CLI wins

    def test_corrupt_config_falls_back(self, monkeypatch, tmp_path):
        """Corrupt config.json -> fallback to 27 + warning."""
        import src.constants as c
        monkeypatch.setattr(c, "DATA_DIR", tmp_path / "data")
        (tmp_path / "data").mkdir(exist_ok=True)
        config_path = tmp_path / "config.json"
        with open(config_path, "w") as f:
            f.write("not valid json")

        args = MockArgs(league=None)
        league_id, data_dir = _resolve_league_id(args)
        assert league_id == 27  # fallback

    def test_config_auto_created(self, monkeypatch, tmp_path):
        """Missing config.json -> auto-created with league_id=27."""
        import src.constants as c
        monkeypatch.setattr(c, "DATA_DIR", tmp_path / "data")
        (tmp_path / "data").mkdir(exist_ok=True)

        args = MockArgs(league=None)
        _resolve_league_id(args)
        config_path = tmp_path / "config.json"
        assert config_path.exists()
        with open(config_path) as f:
            config = json.load(f)
        assert config["league_id"] == 27
