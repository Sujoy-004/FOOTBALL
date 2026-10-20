"""SIM-03: a simulation run never touches a canonical factual store.

The rule this file pins: **after a simulation run, no canonical factual store
file under ``competitions/*/data/`` has changed.** The ONE sanctioned
exception is ``snapshot.json`` — the simulated artifact (Assumption A1). That
carve-out is EXPLICIT and it is load-bearing: the test below proves that

1. the hash map really does cover every canonical file (so the gate is real,
   not a test that silently excluded everything), and
2. the sanctioned artifact really is produced by a run (so excluding it is a
   deliberate carve-out, not a no-op that would let any file slip through).

Two levels are covered:

* the **pipeline** level (``run_mc_simulation``) — the computation itself
  must not write a store, and
* the **app** level (a real ``POST /api/simulate``) — the only file the
  served path may create is the sanctioned ``snapshot.json``.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Iterable, Optional

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
UCL_DATA = ROOT / "competitions" / "ucl" / "data"

#: The ONE file a simulation run is allowed to write (Assumption A1).
SANCTIONED_SIMULATED_ARTIFACT = "snapshot.json"


def _hash_tree(root: Path, exclude: Optional[Iterable[str]] = None) -> dict[str, str]:
    """``{relative path: sha256}`` for every file under *root*.

    Args:
        root: The directory to hash.
        exclude: File NAMES to leave out. Used for the sanctioned simulated
            artifact (``snapshot.json``), which is allowed to change.
    """
    excluded = set(exclude or ())
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in excluded:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out[str(path.relative_to(root)).replace("\\", "/")] = digest
    return out


def _offline_elo() -> dict[str, float]:
    """Fixture-coefficient Elo — the offline fallback the boot path uses."""
    fixtures = json.loads((UCL_DATA / "fixtures.json").read_text("utf-8"))
    coeffs = {t["name"]: t["coefficient"] for t in fixtures["schedule"]["teams"]}
    mx = max(coeffs.values())
    return {n: 1400.0 + (c / mx) * 400.0 for n, c in coeffs.items()}


def _seed_data_dir(tmp_path: Path) -> Path:
    """A minimal UCL data dir: fixtures + aliases + an empty results ledger."""
    for f in ("fixtures.json", "team_aliases.json"):
        shutil.copy(UCL_DATA / f, tmp_path / f)
    (tmp_path / "results.json").write_text(json.dumps({"matches": []}),
                                            encoding="utf-8")
    (tmp_path / "standings.json").write_text(json.dumps({"standings": []}),
                                              encoding="utf-8")
    return tmp_path


@pytest.fixture
def snapshot_mode(monkeypatch):
    import web.startup as startup
    monkeypatch.setenv("FOOTBALL_SNAPSHOT", "1")
    startup.set_session_decision(startup.StartupDecision("snapshot", ""))
    yield
    startup.set_session_decision(None)


class TestCanonicalStoreImmutability:
    """SIM-03: the simulation computation writes no canonical store."""

    def test_no_canonical_store_changes_after_sim(self, tmp_path):
        """A run over a data dir leaves every canonical file byte-identical.

        ``snapshot.json`` is excluded EXPLICITLY: it is the sanctioned
        simulated artifact (Assumption A1) and the only file a run may
        change. Every other file — including the canonical ``results.json``
        and ``standings.json`` — must be byte-identical afterwards.
        """
        from competitions.ucl.src.pipeline import run_mc_simulation

        _seed_data_dir(tmp_path)
        before = _hash_tree(tmp_path, exclude={SANCTIONED_SIMULATED_ARTIFACT})

        run_mc_simulation(str(tmp_path), n_iterations=5, seed=42,
                          elo_ratings_override=_offline_elo())

        after = _hash_tree(tmp_path, exclude={SANCTIONED_SIMULATED_ARTIFACT})
        assert after == before
        # The simulation never fabricates a canonical store file.
        assert not (tmp_path / "knockout_results.json").exists()

    def test_hash_tree_covers_canonical_files(self, tmp_path):
        """The gate is REAL: canonical files are hashed, snapshot.json is not.

        Without this, a helper that excluded everything would make the
        immutability test above a fake gate.
        """
        _seed_data_dir(tmp_path)
        (tmp_path / SANCTIONED_SIMULATED_ARTIFACT).write_text("{}", encoding="utf-8")

        before = _hash_tree(tmp_path, exclude={SANCTIONED_SIMULATED_ARTIFACT})
        assert "results.json" in before
        assert "standings.json" in before
        assert SANCTIONED_SIMULATED_ARTIFACT not in before

        # A canonical file change IS detected...
        (tmp_path / "results.json").write_text(json.dumps({"matches": [1]}),
                                                encoding="utf-8")
        changed = _hash_tree(tmp_path, exclude={SANCTIONED_SIMULATED_ARTIFACT})
        assert changed != before
        assert changed["results.json"] != before["results.json"]

        # ...while a change to the sanctioned artifact is not.
        (tmp_path / SANCTIONED_SIMULATED_ARTIFACT).write_text('{"x": 1}',
                                                               encoding="utf-8")
        assert _hash_tree(tmp_path,
                          exclude={SANCTIONED_SIMULATED_ARTIFACT}) == changed


class TestServedRunWritesOnlyTheSanctionedArtifact:
    """SIM-03 at the served path: the app may only create snapshot.json."""

    def test_simulation_run_creates_only_the_sanctioned_snapshot(
            self, snapshot_mode, tmp_path, monkeypatch):
        """A real ``POST /api/simulate`` touches no canonical store file."""
        import web.ucl_app as app
        from web.derived import holder
        from web.ucl_app import ucl_app

        for f in ("fixtures.json", "team_aliases.json", "current.json"):
            shutil.copy(UCL_DATA / f, tmp_path / f)
        (tmp_path / "knockout_results.json").unlink(missing_ok=True)
        (tmp_path / SANCTIONED_SIMULATED_ARTIFACT).unlink(missing_ok=True)
        (tmp_path / "results.json").write_text(json.dumps({"matches": []}),
                                                encoding="utf-8")
        monkeypatch.setattr(app, "DATA_DIR", tmp_path)

        # The offline Elo override keeps the run network-free.
        elo = _offline_elo()
        holder.publish_data("ucl", {"elo_ratings": elo, "champion": None},
                            mode="results", stamp=app._observed_stamp())
        before = _hash_tree(tmp_path, exclude={SANCTIONED_SIMULATED_ARTIFACT})

        try:
            with TestClient(ucl_app) as client:
                resp = client.post("/api/simulate",
                                    json={"iterations": 2, "seed": 42})
                assert resp.status_code == 200, resp.text
                task_id = resp.json()["task_id"]
                payload: dict = {}
                for _ in range(240):
                    time.sleep(0.25)
                    payload = client.get(
                        f"/api/simulation/progress/{task_id}").json()
                    if payload.get("status") in ("completed", "failed"):
                        break
                assert payload.get("status") == "completed", payload
        finally:
            holder.clear_sim("ucl")

        after = _hash_tree(tmp_path, exclude={SANCTIONED_SIMULATED_ARTIFACT})
        assert after == before
        # The sanctioned artifact WAS produced — the carve-out is load-bearing.
        assert (tmp_path / SANCTIONED_SIMULATED_ARTIFACT).exists()
        # ...and nothing else was created.
        assert set(after) - set(before) == set()
        assert not (tmp_path / "knockout_results.json").exists()
