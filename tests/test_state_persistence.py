# -*- coding: utf-8 -*-
"""football_core.state persistence primitives — the adapters' on-disk truth.

The seed+replay Elo adapters (ucl/elo_fetcher, laliga pipeline, worldcup
elo_runtime) persist every moved rating through these helpers, so the
atomic-write barrier and the Elo cache/log round-trips are part of the
kernel's provenance story (T-quick-03 audit trail). This file pins the
branches that no other module exercises: the cwd resolution, the
failure path that cleans the temp file, the missing-file emptiness
contract, and save/load round-trips through the single atomic primitive.
"""

from __future__ import annotations

import os

import pytest

from football_core import state


class TestResolveDataDir:
    def test_none_resolves_to_cwd(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        assert state._resolve_data_dir(None) == tmp_path

    def test_str_resolves_to_path(self, tmp_path):
        dp = state._resolve_data_dir(str(tmp_path))
        assert dp == tmp_path


class TestAtomicWriteBarrier:
    def test_failure_unlinks_temp_file_and_reraises(self, tmp_path, monkeypatch):
        """A crash mid-write leaves the previous file intact and NO temp. """
        target = tmp_path / "x.json"
        target.write_text("previous", encoding="utf-8")

        def _boom(fd, *args, **kwargs):
            try:
                os.close(fd)
            except OSError:
                pass
            raise OSError("simulated write failure")

        monkeypatch.setattr(state.os, "fdopen", _boom)
        with pytest.raises(OSError):
            state.atomic_write_text(target, "new-text")
        # Temp cleaned up; the previous content survives the failed write.
        assert [p for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []
        assert target.read_text(encoding="utf-8") == "previous"

    def test_success_creates_nested_dirs_and_writes(self, tmp_path):
        target = tmp_path / "nested" / "dir" / "x.json"
        state.atomic_write_text(target, "payload", encoding="utf-8")
        assert target.read_text(encoding="utf-8") == "payload"

    def test_unlink_failure_swallowed_and_reraises(self, tmp_path, monkeypatch):
        """Best-effort cleanup: an unlink failure inside the barrier is
        swallowed and the ORIGINAL exception still propagates — the temp
        file leaks, which is the documented best-effort behaviour."""
        target = tmp_path / "x.json"
        target.write_text("previous", encoding="utf-8")

        def _boom_fdopen(fd, *args, **kwargs):
            try:
                os.close(fd)
            except OSError:
                pass
            raise OSError("simulated write failure")

        def _boom_unlink(path, *args, **kwargs):
            raise OSError("simulated unlink failure")

        real_unlink = os.unlink  # captured before patching; used for cleanup
        monkeypatch.setattr(state.os, "fdopen", _boom_fdopen)
        monkeypatch.setattr(state.os, "unlink", _boom_unlink)
        with pytest.raises(OSError):
            state.atomic_write_text(target, "new-text")
        # Temp leaked because unlink was broken; clean it up here.
        leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
        assert leftovers, "the temp file must leak when unlink is broken"
        for p in leftovers:
            real_unlink(str(p))
        assert target.read_text(encoding="utf-8") == "previous"


class TestMissingStoreEmptiness:
    """Missing file is an honest empty — never an error, never a fill."""

    def test_load_played_missing_is_empty(self, tmp_path):
        assert state.load_played(str(tmp_path)) == {}

    def test_load_prediction_history_missing_is_empty(self, tmp_path):
        assert state.load_prediction_history(str(tmp_path)) == []


class TestStoreRoundTrips:
    """save_* helpers write atomically; load reads the same bytes back."""

    def test_prediction_history_roundtrip(self, tmp_path):
        history = [{"match_id": "1", "actual": 1.0}]
        state.save_prediction_history(history, str(tmp_path))
        assert state.load_prediction_history(str(tmp_path)) == history

    def test_eloratings_cache_roundtrip(self, tmp_path):
        cache = {"Arg": {"elo": 2100.0}}
        state.save_eloratings_cache(cache, str(tmp_path))
        assert state.load_eloratings_cache(str(tmp_path)) == cache

    def test_elo_cache_roundtrip(self, tmp_path):
        doc = {"fetched_at": "2026-10-30T00:00:00Z", "source": "seeded",
               "values": {"A": 1500.0}}
        state.save_elo_cache(doc, str(tmp_path))
        assert state.load_elo_cache(str(tmp_path)) == doc
