# -*- coding: utf-8 -*-
"""Tests for the network-free eloratings TSV snapshot loader.

The live ClubElo fetch 502s at runtime, so the Elo view needs a real, offline
ratings source.  These tests lock in the loader contract: it reads only the
newest dated snapshot, matches canonical team names through the alias file,
and degrades to ``{}`` — never an exception — when the directory, the file, or
the data is missing or malformed.  Hermetic: everything is written to
``tmp_path``, no network.
"""

from __future__ import annotations

import json

import pytest

from football_core.elo_fetcher import (
    ELO_SNAPSHOT_DIR,
    load_snapshot_elos,
    load_snapshot_ratings,
)

_ALIASES = {"Real Madrid": ["Real Madrid", "Real Madrid CF"],
            "Bodo/Glimt": ["Bodoe Glimt", "FK Bodo/Glimt"]}


def _write_aliases(tmp_path) -> str:
    path = tmp_path / "team_aliases.json"
    path.write_text(json.dumps(_ALIASES), encoding="utf-8")
    return str(path)


def _row(name: str, rating: object) -> str:
    """A snapshot row in the layout ``parse_eloratings_tsv`` reads (id@2, rating@3)."""
    return "\t".join(["1", "EU", name, str(rating), "1", "2281", "1946"])


class TestLoadSnapshotRatings:
    def test_missing_dir_returns_empty(self, tmp_path):
        assert load_snapshot_ratings(tmp_path / "nope") == {}

    def test_empty_dir_returns_empty(self, tmp_path):
        assert load_snapshot_ratings(tmp_path) == {}

    def test_parses_temp_tsv_fixture(self, tmp_path):
        (tmp_path / "eloratings_2026-09-01.tsv").write_text(
            _row("Real Madrid", 1943) + "\n" + _row("Barcelona", 1890) + "\n",
            encoding="utf-8",
        )
        table = load_snapshot_ratings(tmp_path)
        assert table["real madrid"] == 1943.0
        assert table["barcelona"] == 1890.0

    def test_reads_only_the_newest_snapshot(self, tmp_path):
        (tmp_path / "eloratings_2026-09-01.tsv").write_text(
            _row("Real Madrid", 1943) + "\n", encoding="utf-8")
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(
            _row("Real Madrid", 1971) + "\n", encoding="utf-8")
        assert load_snapshot_ratings(tmp_path)["real madrid"] == 1971.0

    def test_bad_rows_are_skipped_not_fatal(self, tmp_path):
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(
            "\n".join([
                "1\t2\t3",                      # too short
                _row("Real Madrid", "n/a"),     # unparseable rating
                _row("Nowhere", 99),            # implausible Elo
                _row("Real Madrid", 1943),      # the one good row
            ]) + "\n",
            encoding="utf-8",
        )
        assert load_snapshot_ratings(tmp_path) == {"real madrid": 1943.0}

    def test_shifted_layout_is_never_misattributed_to_a_team(self, tmp_path):
        # A shifted row is read by its own column contract, so it lands on a
        # name no team aliases to. What must not happen is Real Madrid
        # inheriting a rating parsed out of a column it does not own.
        row = "\t".join(["1", "Real Madrid", "ES", "1943", "x", "y"])
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(row + "\n", encoding="utf-8")
        assert load_snapshot_elos(["Real Madrid"], _write_aliases(tmp_path), tmp_path) == {}

    def test_garbage_file_returns_empty(self, tmp_path):
        (tmp_path / "eloratings_2026-09-30.tsv").write_bytes(b"\x00\xff\xfe not a tsv")
        assert load_snapshot_ratings(tmp_path) == {}


class TestLoadSnapshotElo:
    def test_missing_dir_returns_empty(self, tmp_path):
        alias_path = _write_aliases(tmp_path)
        assert load_snapshot_elos(["Real Madrid"], alias_path, tmp_path / "nope") == {}

    def test_no_team_matches_returns_empty(self, tmp_path):
        alias_path = _write_aliases(tmp_path)
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(
            _row("Some Other Club", 1700) + "\n", encoding="utf-8")
        assert load_snapshot_elos(["Real Madrid"], alias_path, tmp_path) == {}

    def test_matches_canonical_name(self, tmp_path):
        alias_path = _write_aliases(tmp_path)
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(
            _row("Real Madrid", 1943) + "\n", encoding="utf-8")
        assert load_snapshot_elos(["Real Madrid"], alias_path, tmp_path) == {
            "Real Madrid": 1943.0,
        }

    def test_matches_alias_variant_accent_insensitively(self, tmp_path):
        alias_path = _write_aliases(tmp_path)
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(
            _row("Bodoe Glimt", 1812) + "\n", encoding="utf-8")
        assert load_snapshot_elos(["Bodo/Glimt"], alias_path, tmp_path) == {
            "Bodo/Glimt": 1812.0,
        }

    def test_uncovered_team_is_absent_not_defaulted(self, tmp_path):
        alias_path = _write_aliases(tmp_path)
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(
            _row("Real Madrid", 1943) + "\n", encoding="utf-8")
        matched = load_snapshot_elos(["Real Madrid", "Barcelona"], alias_path, tmp_path)
        assert matched == {"Real Madrid": 1943.0}

    def test_unreadable_alias_file_returns_empty(self, tmp_path):
        (tmp_path / "eloratings_2026-09-30.tsv").write_text(
            _row("Real Madrid", 1943) + "\n", encoding="utf-8")
        assert load_snapshot_elos(["Real Madrid"], str(tmp_path / "gone.json"), tmp_path) == {}


def test_default_snapshot_dir_is_football_core_elo_ratings():
    """The default points at football_core/elo_ratings, next to this module."""
    assert ELO_SNAPSHOT_DIR.name == "elo_ratings"
    assert ELO_SNAPSHOT_DIR.parent.name == "football_core"
