"""Tests for src.pipeline.season_lifecycle (Exchange 3).

Covers: completed stage on the real World Cup stores, key-contract parity
with the UCL lifecycle contract, sane progress counters (72 group matches),
and phase reuse without recomputation.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Import bootstrap (mirrors tests/test_stage_order.py): worldcup must precede
# ucl on sys.path so the bare ``src`` name resolves to the World Cup package.
_UCL = str(ROOT / "competitions" / "ucl")
_WC = str(ROOT / "competitions" / "worldcup")
for _entry in (_UCL, _WC, str(ROOT)):
    while _entry in sys.path:
        sys.path.remove(_entry)
sys.path.insert(0, _UCL)
sys.path.insert(0, _WC)
sys.path.insert(0, str(ROOT))

from src.pipeline import compute_competition_phase, season_lifecycle  # noqa: E402


LIFECYCLE_CONTRACT = {
    "season", "stage", "progress", "historical", "basis",
    "provider_current_season", "season_mismatch", "label",
    "diagnostics",
}


class TestRealDataCompleted:
    def test_stage_completed_on_real_wc_data(self):
        """Real stores carry 72 group + 32 KO results incl. FINAL winner."""
        result = season_lifecycle()
        assert result == {
            "season": "2026",
            "stage": "completed",
            "progress": {"played": 104, "total": 104},
            "historical": ["2026"],
            "basis": "derived",
            "provider_current_season": None,
            "season_mismatch": False,
            "label": "2026 - completed",
            "diagnostics": [],
        }

    def test_phase_report_agrees_on_completed(self):
        phase = compute_competition_phase()
        assert phase["phase"] == "completed"
        assert season_lifecycle()["stage"] == "completed"


class TestContractParity:
    def test_same_keys_as_ucl_contract(self):
        assert set(season_lifecycle().keys()) == LIFECYCLE_CONTRACT

    def test_same_keys_as_ucl_discover_output(self):
        """Live parity check against a real UCL discover() call."""
        from competitions.ucl.src.lifecycle import discover

        ucl_dir = ROOT / "competitions" / "ucl" / "data"
        assert set(discover(ucl_dir).keys()) == set(season_lifecycle().keys())

    def test_progress_shape_is_played_total_ints(self):
        progress = season_lifecycle()["progress"]
        assert set(progress.keys()) == {"played", "total"}
        assert isinstance(progress["played"], int)
        assert isinstance(progress["total"], int)


class TestProgressCounts:
    def test_seventy_two_group_matches_played(self):
        phase = compute_competition_phase()
        assert phase["progress"]["played"] >= 72

    def test_lifecycle_progress_matches_phase_counters(self):
        """Progress reuses the exact compute_competition_phase counters."""
        phase = compute_competition_phase()
        result = season_lifecycle(phase=phase)
        assert result["progress"] == {
            "played": phase["progress"]["played"],
            "total": phase["progress"]["total"],
        }

    def test_progress_totals_are_the_full_tournament(self):
        assert season_lifecycle()["progress"]["total"] == 72 + 32


class TestPhaseReuse:
    def test_supplied_phase_is_not_recomputed(self, monkeypatch):
        def _boom(_data_dir=None):
            raise AssertionError("phase was supplied; must not recompute")

        monkeypatch.setattr(
            sys.modules["src.pipeline"], "compute_competition_phase", _boom)
        precomputed = {
            "phase": "group_stage",
            "label": "Group Stage",
            "champion": None,
            "progress": {"played": 30, "total": 104},
            "stores": {"group_results": "available",
                       "knockout_results": "missing"},
        }
        result = season_lifecycle(phase=precomputed)
        assert result["stage"] == "active"
        assert result["progress"] == {"played": 30, "total": 104}
        assert result["label"] == "2026 - active"

    def test_deterministic_across_calls(self):
        first = season_lifecycle()
        second = season_lifecycle()
        assert first == second
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
