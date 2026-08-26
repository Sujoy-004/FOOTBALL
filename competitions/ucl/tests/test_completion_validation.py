"""Target Failure 5 regression tests — completion-validation hardening.

A champion alone must NEVER imply a completed season. Every scenario here
constructs an impossible-by-construction combination in temporary data dirs
(built from the real repo stores) and asserts the brain refuses to classify
it as completed: weak evidence yields active, self-contradicting evidence
yields inconsistent with machine-readable ``ucl.*`` / ``wc.*`` diagnostics.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
REAL_UCL_DATA = REPO_ROOT / "competitions" / "ucl" / "data"
REAL_WC_DATA = REPO_ROOT / "competitions" / "worldcup" / "data"

SEASON = "2025/26"
TOTAL_LEAGUE = 144

# World Cup package bootstrap (mirrors test_lifecycle_wc.py): worldcup must
# precede ucl so the bare ``src`` name resolves to the World Cup package.
_UCL = str(REPO_ROOT / "competitions" / "ucl")
_WC = str(REPO_ROOT / "competitions" / "worldcup")
for _entry in (_UCL, _WC, str(REPO_ROOT)):
    while _entry in sys.path:
        sys.path.remove(_entry)
sys.path.insert(0, _UCL)
sys.path.insert(0, _WC)
sys.path.insert(0, str(REPO_ROOT))

from competitions.ucl.src.lifecycle import discover  # noqa: E402
from competitions.ucl.src.orchestrator import (  # noqa: E402
    compute_competition_phase as ucl_compute_phase,
)
from src.pipeline import (  # noqa: E402
    compute_competition_phase as wc_compute_phase,
    season_lifecycle,
)


def _real_rows() -> list:
    payload = json.loads((REAL_UCL_DATA / "results.json").read_text(encoding="utf-8"))
    rows = payload.get("matches", payload) if isinstance(payload, dict) else payload
    assert isinstance(rows, list) and len(rows) == TOTAL_LEAGUE
    return rows


def _real_knockout() -> dict:
    return json.loads(
        (REAL_UCL_DATA / "knockout_results.json").read_text(encoding="utf-8"))


def _champion_only_knockout(champion: str = "PSG") -> dict:
    return {
        "schema": 2,
        "matches": {
            "playoff": [],
            "rounds": {"R16": [], "QF": [], "SF": []},
            "final": [],
            "champion": champion,
        },
        "meta": {"provider": None, "backfilled_from": None, "updated_at": None},
    }


def _ucl_dir(
    tmp_path: Path,
    *,
    results_rows: list | None,
    knockout: dict | None,
) -> Path:
    dst = tmp_path / "ucldata"
    dst.mkdir(exist_ok=True)
    (dst / "fixtures.json").write_text(
        (REAL_UCL_DATA / "fixtures.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    if results_rows is not None:
        (dst / "results.json").write_text(
            json.dumps({"matches": results_rows}), encoding="utf-8")
    if knockout is not None:
        (dst / "knockout_results.json").write_text(
            json.dumps(knockout), encoding="utf-8")
    return dst


def _full_ucl_dir(tmp_path: Path, *, knockout: dict | None) -> Path:
    return _ucl_dir(tmp_path, results_rows=_real_rows(), knockout=knockout)


def _wc_payload(name: str):
    return json.loads((REAL_WC_DATA / name).read_text(encoding="utf-8"))


def _wc_dir(tmp_path: Path, *, n_groups: int = 72, ko_mutate=None) -> Path:
    dst = tmp_path / "wcdata"
    dst.mkdir(exist_ok=True)
    (dst / "bracket.json").write_text(
        (REAL_WC_DATA / "bracket.json").read_text(encoding="utf-8"),
        encoding="utf-8")
    played_groups = _wc_payload("played_groups.json")
    kept = dict(list(played_groups.items())[:n_groups])
    (dst / "played_groups.json").write_text(
        json.dumps(kept), encoding="utf-8")
    played = _wc_payload("played.json")
    if ko_mutate is not None:
        ko_mutate(played)
    (dst / "played.json").write_text(json.dumps(played), encoding="utf-8")
    return dst


class TestUCLChampionAloneNeverCompletes:
    def test_champion_with_empty_league_and_empty_ko_store(self, tmp_path):
        """Scenario 1: champion field + zero league rows + empty KO store."""
        dst = _ucl_dir(
            tmp_path, results_rows=[], knockout=_champion_only_knockout())
        phase = ucl_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is True
        assert "ucl.league_incomplete" in phase["diagnostics"]
        assert any("champion" in d or "league" in d
                   for d in phase["diagnostics"])
        view = discover(dst)
        assert view["stage"] == "inconsistent"

    def test_full_league_with_ko_store_missing_entirely(self, tmp_path):
        """Scenario 2: 144/144 league but no knockout file => NOT completed."""
        dst = _ucl_dir(tmp_path, results_rows=_real_rows(), knockout=None)
        phase = ucl_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is False
        assert "ucl.knockout_store_unavailable" in phase["diagnostics"]
        view = discover(dst)
        assert view["stage"] == "active"
        assert "ucl.knockout_store_unavailable" in view["diagnostics"]

    def test_full_league_with_champion_only_ko_store(self, tmp_path):
        """Scenario 2b: champion recorded but the whole progression missing."""
        dst = _full_ucl_dir(
            tmp_path, knockout=_champion_only_knockout())
        phase = ucl_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is True
        assert "ucl.final_undecided" in phase["diagnostics"]
        assert discover(dst)["stage"] == "inconsistent"

    def test_final_undecided_but_champion_present(self, tmp_path):
        """Scenario 3: KO decided through SF, FINAL undecided, champion set."""
        knockout = _real_knockout()
        final_entry = knockout["matches"]["final"][0]
        final_entry["winner"] = None
        final_entry["status"] = "scheduled"
        dst = _full_ucl_dir(tmp_path, knockout=knockout)
        phase = ucl_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is True
        assert phase["diagnostics"] == ["ucl.final_undecided"]
        view = discover(dst)
        assert view["stage"] == "inconsistent"

    def test_champion_differs_from_final_winner(self, tmp_path):
        """Scenario 4: fully played season whose champion contradicts FINAL."""
        knockout = _real_knockout()
        knockout["matches"]["champion"] = "Bayern"
        dst = _full_ucl_dir(tmp_path, knockout=knockout)
        phase = ucl_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is True
        assert phase["diagnostics"] == ["ucl.champion_final_mismatch"]
        assert discover(dst)["stage"] == "inconsistent"

    def test_full_valid_evidence_is_completed_clean(self, tmp_path):
        """Scenario 5: the complete valid set classifies completed, [] diags."""
        dst = _full_ucl_dir(tmp_path, knockout=_real_knockout())
        phase = ucl_compute_phase(dst)
        assert phase["phase"] == "completed"
        assert phase["diagnostics"] == []
        assert phase["inconsistent"] is False
        assert discover(dst) == {
            "season": SEASON,
            "stage": "completed",
            "progress": {"played": TOTAL_LEAGUE, "total": TOTAL_LEAGUE},
            "historical": [SEASON],
            "basis": "derived",
            "provider_current_season": None,
            "season_mismatch": False,
            "label": f"{SEASON} - completed",
            "diagnostics": [],
        }

    @pytest.mark.parametrize("with_fixtures", [True, False])
    def test_fresh_checkout_without_runtime_files_never_completes(
            self, tmp_path, with_fixtures):
        """Empty-store scenarios classify future/unknown, never completed."""
        dst = tmp_path / ("fresh" if with_fixtures else "bare")
        dst.mkdir()
        if with_fixtures:
            (dst / "fixtures.json").write_text(
                (REAL_UCL_DATA / "fixtures.json").read_text(encoding="utf-8"),
                encoding="utf-8")
        assert ucl_compute_phase(dst)["phase"] == "not_started"
        view = discover(dst)
        assert view["stage"] == ("future" if with_fixtures else "unknown")
        assert view["stage"] != "completed"
        assert view["diagnostics"] == []


class TestWCChampionAloneNeverCompletes:
    def test_tpp_undecided_but_champion_present(self, tmp_path):
        """Champion (FINAL winner) on file while TPP has no winner."""
        def mutate(played: dict) -> None:
            played["TPP"]["winner"] = None

        dst = _wc_dir(tmp_path, ko_mutate=mutate)
        phase = wc_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is True
        assert phase["diagnostics"] == ["wc.tpp_undecided"]
        view = season_lifecycle(dst)
        assert view["stage"] == "inconsistent"

    def test_champion_with_incomplete_groups(self, tmp_path):
        """Champion on file while group matches are missing."""
        dst = _wc_dir(tmp_path, n_groups=60)
        phase = wc_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is True
        assert "wc.groups_incomplete" in phase["diagnostics"]
        assert season_lifecycle(dst)["stage"] == "inconsistent"

    def test_full_valid_wc_is_completed_clean(self, tmp_path):
        dst = _wc_dir(tmp_path)
        phase = wc_compute_phase(dst)
        assert phase["phase"] == "completed"
        assert phase["diagnostics"] == []
        assert phase["inconsistent"] is False
        view = season_lifecycle(dst)
        assert view["stage"] == "completed"
        assert view["diagnostics"] == []

    def test_final_undecided_is_active_never_completed(self, tmp_path):
        """FINAL winner null: champion unreachable, stage stays active.

        The WC champion IS the FINAL winner (single derivation source), so
        the champion-vs-FINAL mismatch class is structurally unreachable;
        the undecided FINAL simply blocks completion.
        """
        def mutate(played: dict) -> None:
            played["FINAL"]["winner"] = None

        dst = _wc_dir(tmp_path, ko_mutate=mutate)
        phase = wc_compute_phase(dst)
        assert phase["phase"] != "completed"
        assert phase["inconsistent"] is False
        assert "wc.final_undecided" in phase["diagnostics"]
        view = season_lifecycle(dst)
        assert view["stage"] == "active"
        assert "wc.final_undecided" in view["diagnostics"]

    def test_empty_wc_stores_never_complete(self, tmp_path):
        dst = tmp_path / "wcempty"
        dst.mkdir()
        (dst / "bracket.json").write_text(
            (REAL_WC_DATA / "bracket.json").read_text(encoding="utf-8"),
            encoding="utf-8")
        phase = wc_compute_phase(dst)
        assert phase["phase"] == "not_started"
        assert season_lifecycle(dst)["stage"] == "future"
        assert phase["phase"] != "completed"
