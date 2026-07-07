"""Tests for live_state.py persistence — round-trip, missing files, corruption, atomic writes."""

import json
import os
import tempfile

import pytest

from competitions.ucl.src.live_state import (
    append_ucl_prediction_history,
    load_ucl_elo_applied,
    load_ucl_played,
    load_ucl_prediction_history,
    save_ucl_elo_applied,
    save_ucl_played,
    save_ucl_prediction_history,
)


class TestLiveStatePersistence:

    def test_save_load_played_roundtrip(self, tmp_path):
        played = {"M1": {"home": "A", "away": "B", "winner": "A"}}
        save_ucl_played(played, str(tmp_path))
        loaded = load_ucl_played(str(tmp_path))
        assert loaded == played

    def test_save_load_elo_applied_roundtrip(self, tmp_path):
        elo_applied = ["M1", "M2", "M3"]
        save_ucl_elo_applied(elo_applied, str(tmp_path))
        loaded = load_ucl_elo_applied(str(tmp_path))
        assert loaded == elo_applied

    def test_save_load_prediction_history_roundtrip(self, tmp_path):
        history = [{"date": "2026-07-01", "iterations": 1000}]
        save_ucl_prediction_history(history, str(tmp_path))
        loaded = load_ucl_prediction_history(str(tmp_path))
        assert loaded == history

    def test_append_prediction_history(self, tmp_path):
        entry1 = {"date": "2026-07-01", "iterations": 1000}
        entry2 = {"date": "2026-07-02", "iterations": 2000}
        append_ucl_prediction_history(entry1, str(tmp_path))
        assert load_ucl_prediction_history(str(tmp_path)) == [entry1]
        append_ucl_prediction_history(entry2, str(tmp_path))
        assert load_ucl_prediction_history(str(tmp_path)) == [entry1, entry2]

    def test_missing_file_returns_empty_dict(self, tmp_path):
        result = load_ucl_played(str(tmp_path))
        assert result == {}

    def test_missing_file_returns_empty_list(self, tmp_path):
        result = load_ucl_elo_applied(str(tmp_path))
        assert result == []

    def test_missing_history_returns_empty_list(self, tmp_path):
        result = load_ucl_prediction_history(str(tmp_path))
        assert result == []

    def test_corrupted_json_returns_empty(self, tmp_path):
        bad_path = tmp_path / "ucl_played.json"
        bad_path.write_text("invalid json", encoding="utf-8")
        result = load_ucl_played(str(tmp_path))
        assert result == {}

    def test_atomic_write_integrity(self, tmp_path):
        played = {"M1": {"home": "A", "winner": "A"}}
        save_ucl_played(played, str(tmp_path))
        target = tmp_path / "ucl_played.json"
        assert target.exists()
        with open(target) as f:
            assert json.load(f) == played

    def test_ucl_prefix_on_all_files(self, tmp_path):
        save_ucl_played({"M1": {}}, str(tmp_path))
        save_ucl_elo_applied(["M1"], str(tmp_path))
        save_ucl_prediction_history([], str(tmp_path))
        files = {f.name for f in tmp_path.iterdir() if f.is_file() and not f.name.startswith(".")}
        assert files == {"ucl_played.json", "ucl_elo_applied.json", "ucl_prediction_history.json"}
