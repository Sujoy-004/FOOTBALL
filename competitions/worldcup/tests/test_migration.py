"""Tests for legacy data migration (data/ -> data/27/)."""

import json
from pathlib import Path

import pytest

from main import _migrate_legacy_data, _merge_probability_log


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

    def test_migrates_probability_log(self, tmp_path):
        """probability_log.json is included in migration."""
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "played.json").write_text("{}")
        (data_dir / "probability_log.json").write_text(json.dumps([
            {"timestamp": "2026-06-21T10:00:00", "probabilities": {}},
        ]))

        _migrate_legacy_data(data_dir, league_id=27)

        target = data_dir / "27"
        assert (target / "probability_log.json").exists()
        assert json.loads((target / "probability_log.json").read_text()) == [
            {"timestamp": "2026-06-21T10:00:00", "probabilities": {}},
        ]


class TestMergeProbabilityLog:
    """Tests for _merge_probability_log()."""

    def test_no_root_file_does_nothing(self, tmp_path):
        """No root data/probability_log.json -> no-op."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        league_dir.mkdir(parents=True)
        league_log = [{"timestamp": "2026-06-22T10:00:00", "probabilities": {}}]
        (league_dir / "probability_log.json").write_text(json.dumps(league_log))

        _merge_probability_log(data_dir, league_dir)

        assert json.loads((league_dir / "probability_log.json").read_text()) == league_log

    def test_merges_new_entries_from_root(self, tmp_path):
        """Root entries not in league dir are appended."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        data_dir.mkdir(parents=True)
        league_dir.mkdir(parents=True)

        root_log = [
            {"timestamp": "2026-06-21T10:00:00", "probabilities": {"a": 0.5}},
            {"timestamp": "2026-06-21T11:00:00", "probabilities": {"a": 0.6}},
        ]
        (data_dir / "probability_log.json").write_text(json.dumps(root_log))

        league_log = [
            {"timestamp": "2026-06-22T10:00:00", "probabilities": {"a": 0.7}},
        ]
        (league_dir / "probability_log.json").write_text(json.dumps(league_log))

        _merge_probability_log(data_dir, league_dir)

        result = json.loads((league_dir / "probability_log.json").read_text())
        assert len(result) == 3
        assert result[0]["timestamp"] == "2026-06-22T10:00:00"  # existing first
        assert result[1]["timestamp"] == "2026-06-21T10:00:00"  # merged
        assert result[2]["timestamp"] == "2026-06-21T11:00:00"  # merged

    def test_dedup_by_timestamp(self, tmp_path):
        """Entries already in league dir (same timestamp) are NOT duplicated."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        data_dir.mkdir(parents=True)
        league_dir.mkdir(parents=True)

        root_log = [
            {"timestamp": "2026-06-21T10:00:00", "probabilities": {"a": 0.5}},
            {"timestamp": "2026-06-22T10:00:00", "probabilities": {"a": 0.7}},
        ]
        (data_dir / "probability_log.json").write_text(json.dumps(root_log))

        league_log = [
            {"timestamp": "2026-06-22T10:00:00", "probabilities": {"a": 0.7}},
        ]
        (league_dir / "probability_log.json").write_text(json.dumps(league_log))

        _merge_probability_log(data_dir, league_dir)

        result = json.loads((league_dir / "probability_log.json").read_text())
        assert len(result) == 2  # only one new entry added
        assert result[0]["timestamp"] == "2026-06-22T10:00:00"
        assert result[1]["timestamp"] == "2026-06-21T10:00:00"

    def test_idempotent_second_call_no_change(self, tmp_path):
        """Second call does nothing — already merged."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        data_dir.mkdir(parents=True)
        league_dir.mkdir(parents=True)

        root_log = [{"timestamp": "2026-06-21T10:00:00", "probabilities": {}}]
        (data_dir / "probability_log.json").write_text(json.dumps(root_log))
        (league_dir / "probability_log.json").write_text(json.dumps([]))

        _merge_probability_log(data_dir, league_dir)
        first_result = json.loads((league_dir / "probability_log.json").read_text())
        assert len(first_result) == 1

        _merge_probability_log(data_dir, league_dir)
        second_result = json.loads((league_dir / "probability_log.json").read_text())
        assert len(second_result) == 1  # no duplicate

    def test_empty_root_log_does_nothing(self, tmp_path):
        """Empty root list -> no-op."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        data_dir.mkdir(parents=True)
        league_dir.mkdir(parents=True)
        (data_dir / "probability_log.json").write_text("[]")

        league_log = [{"timestamp": "2026-06-22T10:00:00", "probabilities": {}}]
        (league_dir / "probability_log.json").write_text(json.dumps(league_log))

        _merge_probability_log(data_dir, league_dir)

        assert json.loads((league_dir / "probability_log.json").read_text()) == league_log

    def test_corrupt_root_log_does_nothing(self, tmp_path):
        """Corrupt JSON in root -> no-op (graceful skip)."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        data_dir.mkdir(parents=True)
        league_dir.mkdir(parents=True)
        (data_dir / "probability_log.json").write_text("not valid json")

        league_log = [{"timestamp": "2026-06-22T10:00:00", "probabilities": {}}]
        (league_dir / "probability_log.json").write_text(json.dumps(league_log))

        _merge_probability_log(data_dir, league_dir)

        assert json.loads((league_dir / "probability_log.json").read_text()) == league_log

    def test_creates_league_dir_if_missing(self, tmp_path):
        """League probability_log.json is created if it doesn't exist."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        data_dir.mkdir(parents=True)

        root_log = [{"timestamp": "2026-06-21T10:00:00", "probabilities": {}}]
        (data_dir / "probability_log.json").write_text(json.dumps(root_log))

        _merge_probability_log(data_dir, league_dir)

        assert (league_dir / "probability_log.json").exists()
        result = json.loads((league_dir / "probability_log.json").read_text())
        assert len(result) == 1
        assert result[0]["timestamp"] == "2026-06-21T10:00:00"

    def test_root_not_deleted(self, tmp_path):
        """Root data/probability_log.json is NEVER deleted."""
        data_dir = tmp_path / "data"
        league_dir = tmp_path / "data" / "27"
        data_dir.mkdir(parents=True)
        league_dir.mkdir(parents=True)

        root_log = [{"timestamp": "2026-06-21T10:00:00", "probabilities": {}}]
        (data_dir / "probability_log.json").write_text(json.dumps(root_log))
        (league_dir / "probability_log.json").write_text(json.dumps([]))

        _merge_probability_log(data_dir, league_dir)

        assert (data_dir / "probability_log.json").exists()
