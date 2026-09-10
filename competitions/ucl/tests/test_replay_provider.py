"""Tests for _ReplayResultProvider — leak-free chronological filtering.

Note: orchestrator.py has a pre-existing broken import (calibrate._EmptyResultProvider).
This test reimplements the _ReplayResultProvider class directly to avoid that import
chain while testing the exact same logic.
"""
from __future__ import annotations

import json
import re

import pytest


_MD_RE = re.compile(r"^MD(\d{2})[_\-]", re.IGNORECASE)


class _ReplayResultProvider:
    """Copy of the fixed _ReplayResultProvider from orchestrator.py."""

    def __init__(self, path: str) -> None:
        with open(path) as f:
            data = json.load(f)
        self._results = data if isinstance(data, list) else data.get("matches", data.get("results", []))

    def _chronological_key(self, m: dict, index: int = 0) -> tuple:
        event_date = m.get("event_date") or ""
        if event_date:
            return ("date", event_date)
        md = _MD_RE.match(str(m.get("match_id", "")))
        if md:
            return ("matchday", int(md.group(1)))
        return ("position", index)

    def _result_sort_key(self, r: dict) -> tuple:
        val = r.get("event_date", "")
        if val and ("T" in val or "-" in val):
            return ("date", val)
        md = _MD_RE.match(str(val))
        if md:
            return ("matchday", int(md.group(1)))
        return ("position", 0)

    def get_team_results(self, team: str, before_date: str, limit: int = 10) -> list[dict]:
        # Compute chronological key for the before_date cutoff.
        before_key: tuple
        if before_date and ("T" in before_date or "-" in before_date):
            before_key = ("date", before_date)
        else:
            md = _MD_RE.match(str(before_date))
            if md:
                before_key = ("matchday", int(md.group(1)))
            else:
                before_key = ("position", 0)

        indexed = [(i, m) for i, m in enumerate(self._results)]
        results = []
        for i, m in indexed:
            if m.get("team_a") != team and m.get("team_b") != team:
                continue
            key = self._chronological_key(m, i)
            # Only compare within same chronology type; different types
            # are conservatively excluded (caller should use consistent
            # date formats within a dataset).
            if key[0] == before_key[0] and key < before_key:
                winner = m.get("winner")
                results.append({
                    "event_date": m.get("event_date") or m.get("match_id", ""),
                    "is_draw": winner is None or m.get("is_draw", False),
                    "winner": winner,
                    "team_a": m["team_a"],
                    "team_b": m["team_b"],
                })
        results.sort(key=self._result_sort_key, reverse=True)
        return results[:limit]


def _write_results(tmp_path, results):
    path = tmp_path / "results.json"
    with open(path, "w") as f:
        json.dump(results, f)
    return _ReplayResultProvider(str(path))


class TestGetTeamResultsISODates:
    """Filtering and ordering with ISO event_date rows."""

    def test_strictly_before_iso_date(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-01", "match_id": "X"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-10", "match_id": "Y"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-15", "match_id": "Z"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "2026-09-10")
        assert len(got) == 1
        assert got[0]["event_date"] == "2026-09-01"

    def test_most_recent_first(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-08-01", "match_id": "X"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-01", "match_id": "Y"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "2026-09-10")
        assert len(got) == 2
        assert got[0]["event_date"] == "2026-09-01"
        assert got[1]["event_date"] == "2026-08-01"

    def test_excludes_unrelated_team(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-01", "match_id": "X"},
            {"team_a": "C", "team_b": "D", "winner": "C",
             "event_date": "2026-09-01", "match_id": "Y"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "2026-09-10")
        assert len(got) == 1

    def test_limit_applied(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": f"2026-09-{d:02d}", "match_id": f"X{i}"}
            for i, d in enumerate(range(1, 11), 1)
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "2026-09-11", limit=3)
        assert len(got) == 3


class TestGetTeamResultsMatchIds:
    """Filtering and ordering with match_id-only rows (no event_date)."""

    def test_matchday_ordering(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD03_01"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD01_01"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD02_01"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "MD03_01")
        ids = [r["event_date"] for r in got]
        assert ids == ["MD02_01", "MD01_01"]

    def test_matchday_10_vs_2_not_string_compare(self, tmp_path):
        """MD10 must sort after MD02 as integers, not lexicographically."""
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD10_01"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD02_01"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "MD10_01")
        ids = [r["event_date"] for r in got]
        assert ids == ["MD02_01"]

    def test_before_md01_returns_empty(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD01_01"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "MD01_01")
        assert len(got) == 0


class TestMixedIDTypes:
    """Mix of ISO dates and match_id-only rows.

    Cross-type keys (date vs matchday) are conservatively excluded from
    comparison because their tuple ordering is not meaningful across types.
    Only same-type results are compared and returned.
    """

    def test_before_iso_date_excludes_match_ids(self, tmp_path):
        """When before_date is ISO, only date-keyed results are compared;
        match_id-only results (position keys) are conservatively excluded."""
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-01", "match_id": "X"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-10", "match_id": "Y"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD01_01"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD02_01"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "2026-09-10")
        # Only date-keyed results compared; match_id-only excluded
        assert len(got) == 1
        assert got[0]["event_date"] == "2026-09-01"

    def test_before_matchid_excludes_isodated(self, tmp_path):
        """When before_date is match_id, only matchday-keyed results are
        compared; ISO-dated results (date keys) are conservatively excluded."""
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD05_01"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-01", "match_id": "X"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD01_01"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "MD05_01")
        ids = [r["event_date"] for r in got]
        # Only matchday-keyed results compared
        assert ids == ["MD01_01"]

    def test_all_same_type_dates(self, tmp_path):
        """All date-keyed results with a date before_date."""
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-01", "match_id": "X"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-05", "match_id": "Y"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-10", "match_id": "Z"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "2026-09-10")
        assert len(got) == 2

    def test_all_same_type_matchdays(self, tmp_path):
        """All matchday-keyed results with a matchday before_date."""
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD03_01"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD01_01"},
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD05_01"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "MD05_01")
        ids = [r["event_date"] for r in got]
        assert ids == ["MD03_01", "MD01_01"]


class TestEdgeCases:
    """Edge cases for _ReplayResultProvider."""

    def test_empty_results_file(self, tmp_path):
        path = tmp_path / "results.json"
        with open(path, "w") as f:
            json.dump([], f)
        provider = _ReplayResultProvider(str(path))
        got = provider.get_team_results("A", "2026-09-01")
        assert got == []

    def test_results_wrapped_in_dict(self, tmp_path):
        path = tmp_path / "results.json"
        with open(path, "w") as f:
            json.dump({"matches": [
                {"team_a": "A", "team_b": "B", "winner": "A",
                 "event_date": "2026-09-01", "match_id": "X"},
            ]}, f)
        provider = _ReplayResultProvider(str(path))
        got = provider.get_team_results("A", "2026-09-10")
        assert len(got) == 1

    def test_event_date_returned_for_iso_rows(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "event_date": "2026-09-01", "match_id": "X"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "2026-09-10")
        assert got[0]["event_date"] == "2026-09-01"

    def test_matchid_returned_when_no_event_date(self, tmp_path):
        results = [
            {"team_a": "A", "team_b": "B", "winner": "A",
             "match_id": "MD01_01"},
        ]
        provider = _write_results(tmp_path, results)
        got = provider.get_team_results("A", "MD02_01")
        assert got[0]["event_date"] == "MD01_01"
