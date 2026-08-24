"""Exchange 1 regression tests: UCL compute-mode resolution truth rules.

Locks down the fix for the fabrication incident: a missing or empty
knockout_results.json must NEVER flip the app from real results into a
simulated season over unconditioned real league results.
"""

from __future__ import annotations

import json

import pytest

from competitions.ucl.src.orchestrator import (
    _load_league_played_pairs,
    resolve_compute_mode,
)


def _write_results(tmp_path, matches):
    (tmp_path / "results.json").write_text(
        json.dumps({"matches": matches}), encoding="utf-8"
    )


class TestResolveComputeMode:
    def test_both_files_present_is_results(self, tmp_path):
        _write_results(tmp_path, [{"match_id": "MD01_01"}])
        (tmp_path / "knockout_results.json").write_text("{}", encoding="utf-8")
        mode, reason = resolve_compute_mode(str(tmp_path))
        assert mode == "results"

    def test_results_without_knockout_file_stays_results(self, tmp_path):
        """THE incident: missing KO file must not flip to simulation mode."""
        _write_results(
            tmp_path,
            [{"match_id": "MD01_01", "team_a": "A", "team_b": "B",
              "home_score": 1, "away_score": 0}],
        )
        mode, reason = resolve_compute_mode(str(tmp_path))
        assert mode == "results"
        assert "results" in reason.lower()

    def test_empty_ko_stub_with_real_results_stays_results(self, tmp_path):
        """The actual snapshot state on disk: {"matches": {}} KO stub."""
        _write_results(
            tmp_path,
            [{"match_id": "MD01_01", "team_a": "A", "team_b": "B",
              "home_score": 0, "away_score": 2}],
        )
        (tmp_path / "knockout_results.json").write_text(
            '{\n  "matches": {}\n}\n', encoding="utf-8"
        )
        mode, _ = resolve_compute_mode(str(tmp_path))
        assert mode == "results"

    def test_empty_results_flips_to_simulation(self, tmp_path):
        _write_results(tmp_path, [])
        mode, reason = resolve_compute_mode(str(tmp_path))
        assert mode == "simulation"
        assert "no matches" in reason.lower()

    def test_missing_results_flips_to_simulation(self, tmp_path):
        mode, reason = resolve_compute_mode(str(tmp_path))
        assert mode == "simulation"
        assert "absent" in reason.lower()

    def test_unreadable_results_is_error_not_fabrication(self, tmp_path):
        (tmp_path / "results.json").write_text("{broken", encoding="utf-8")
        mode, detail = resolve_compute_mode(str(tmp_path))
        assert mode == "error"
        assert detail


class TestLeaguePlayedPairs:
    def test_pair_keying_bidirectional(self, tmp_path):
        _write_results(
            tmp_path,
            [{"match_id": "MD01_01", "team_a": "Athletic Bilbao",
              "team_b": "Arsenal", "home_score": 0, "away_score": 2}],
        )
        pairs = _load_league_played_pairs(str(tmp_path))
        assert pairs[("Athletic Bilbao", "Arsenal")] == (0, 2)
        assert pairs[("Arsenal", "Athletic Bilbao")] == (2, 0)

    def test_malformed_entries_skipped(self, tmp_path):
        _write_results(
            tmp_path,
            [
                {"match_id": "bad", "team_a": "A", "team_b": "B"},  # no scores
                {"match_id": "ok", "team_a": "C", "team_b": "D",
                 "home_score": 1, "away_score": 1},
            ],
        )
        pairs = _load_league_played_pairs(str(tmp_path))
        assert ("C", "D") in pairs
        assert ("A", "B") not in pairs

    def test_missing_file_returns_none(self, tmp_path):
        assert _load_league_played_pairs(str(tmp_path)) is None


class TestComputeAllConsistency:
    def test_ucl_app_compute_all_matches_resolver(self, monkeypatch, tmp_path):
        """web.ucl_app.compute_all must follow resolve_compute_mode."""
        import web.ucl_app as ucl_app

        calls = {}

        def fake_deterministic():
            calls["deterministic"] = True
            return {"mode": "results"}

        monkeypatch.setattr(ucl_app, "deterministic_compute", fake_deterministic)
        # Real repo data dir has results.json -> must take results branch
        result = ucl_app.compute_all()
        assert calls.get("deterministic") is True
        assert result["mode"] == "results"
