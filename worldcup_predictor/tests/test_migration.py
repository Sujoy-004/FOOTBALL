"""Tests for legacy data migration (data/ -> data/27/)."""

import json
from pathlib import Path

import pytest

from main import _migrate_legacy_data


class TestMigrateLegacyData:
    """Unit tests for _migrate_legacy_data()."""

    def test_skips_non_27_league(self, tmp_path):
        """league_id != 27 -> no migration."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "played.json").write_text("{}")

        _migrate_legacy_data(data_dir, league_id=65)
        assert not (data_dir / "65" / "played.json").exists()

    def test_idempotent_skips_if_already_migrated(self, tmp_path):
        """data/27/played.json exists -> skip migration."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "played.json").write_text(json.dumps({"m1": {}}))
        target = data_dir / "27"
        target.mkdir(parents=True)
        (target / "played.json").write_text(json.dumps({"existing": {}}))

        _migrate_legacy_data(data_dir, league_id=27)
        # Should NOT overwrite existing
        with open(target / "played.json") as f:
            data = json.load(f)
        assert data == {"existing": {}}  # untouched

    def test_migrates_league_scoped_files(self, tmp_path):
        """League-scoped files are copied from data/ to data/27/."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()

        # Create source files
        files = {
            "played.json": {"m1": {}},
            "teams.json": {"TeamA": {"elo": 2000}},
            "elo_applied.json": ["m1"],
            "versions.json": {"data_version": "D5"},
        }
        for name, content in files.items():
            (data_dir / name).write_text(json.dumps(content))

        _migrate_legacy_data(data_dir, league_id=27)

        target = data_dir / "27"
        assert target.exists()
        for name in files:
            assert (target / name).exists(), f"{name} not migrated"

    def test_non_destructive_keeps_originals(self, tmp_path):
        """Original data/*.json files are NOT deleted after migration."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "played.json").write_text("{}")
        (data_dir / "teams.json").write_text("{}")

        _migrate_legacy_data(data_dir, league_id=27)

        # Originals still exist
        assert (data_dir / "played.json").exists()
        assert (data_dir / "teams.json").exists()

    def test_shared_data_not_migrated(self, tmp_path):
        """Shared files (bracket.json, groups.json) are NOT copied."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "played.json").write_text("{}")
        (data_dir / "bracket.json").write_text("[]")
        (data_dir / "groups.json").write_text("{}")

        _migrate_legacy_data(data_dir, league_id=27)

        target = data_dir / "27"
        # played.json IS per-league -> migrated
        assert (target / "played.json").exists()
        # bracket.json is shared -> NOT migrated
        assert not (target / "bracket.json").exists()
        # groups.json is shared -> NOT migrated
        assert not (target / "groups.json").exists()
