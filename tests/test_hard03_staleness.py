"""HARD-03 + D-18: single-writer freshness ledger and the D-12 staleness rule.

Phase 02 roadmap criterion 5 ("the freshness ledger never reports a stale store
as fresh") and its D-18 single-writer half.

What is pinned here:

* **D-18 (one owner, one lock):** ``football_core.freshness.update_ledger`` is
  the ONLY writer of ``web/last_refresh.json``. Two threads racing 100 updates
  each must leave all 200 entries in the file — a lock-less read-modify-write
  loses entries precisely because a reader can see a half-updated payload.
* **Loudness (D-11/D-18):** a failed ledger write or read calls
  ``logger.exception`` and never pretends it did not happen. ``read_ledger``
  answers corruption with an explicit ``{"ledger": "unreadable", ...}`` marker
  instead of ``{}``, which is indistinguishable from "no refresh has ever run".
* **D-12 (staleness rule):** a store reads STALE iff ``last_success_at`` is
  missing, failed to advance between two reads, or predates the store file's
  mtime by more than the 1-second filesystem tolerance (catches out-of-band
  writes the ledger never saw: CLI backfill, ``git checkout`` of the
  partly-gitignored data dir). All comparisons are tz-aware.
* **D-18 (no hand-rolled RMW):** no ``json.dumps(...)`` + ``Path.write_text``
  read-modify-write survives in the three modules that used to own one.

Failure of this module in RED state is the point: ``football_core.freshness``
does not exist yet.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from football_core import freshness  # noqa: E401  (RED gate: ImportError until GREEN)

ROOT = Path(__file__).resolve().parents[1]
DEFERRED_FIXTURE = ROOT / "tests" / "fixtures" / "deferred_non_atomic_writes.json"

#: The three modules that used to hand-roll a lock-less ledger RMW.
FORMER_RMW_FILES = [
    ROOT / "competitions" / "worldcup" / "src" / "pipeline.py",
    ROOT / "web" / "ucl_app.py",
    ROOT / "web" / "laliga_app.py",
]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


NOW = datetime(2026, 10, 8, 12, 0, 0, tzinfo=timezone.utc)


# ── D-18: one owner, one lock ────────────────────────────────────────────────


def test_concurrent_updates_lose_no_entry(tmp_path):
    """2 threads x 100 keyed updates => all 200 survive, file stays valid JSON."""
    ledger = tmp_path / "last_refresh.json"

    def worker(tag: str) -> None:
        for i in range(100):
            freshness.update_ledger(ledger, f"{tag}_{i:03d}", {"i": i, "tag": tag})

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    raw = ledger.read_text(encoding="utf-8")
    payload = json.loads(raw)  # valid JSON, not a interleaved write
    mine = {k: v for k, v in payload.items() if k.startswith(("a_", "b_"))}
    assert len(mine) == 200, f"lost updates: {len(mine)} of 200 present"
    assert all(mine[k]["i"] == int(k.split("_")[1]) for k in mine), "crossed payloads"


def test_failed_ledger_write_logs_and_raises(tmp_path, caplog):
    """A write that cannot land is loud: logger.exception fires, then re-raise.

    The target's parent is a plain FILE, so the OS rejects the directory
    creation inside ``atomic_write_text``. (A read-only *directory* cannot
    express this on Windows — the directory write bit is ignored — so the
    parent-is-file shape gives the same OS-level write failure portably.)
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    ledger = blocker / "last_refresh.json"

    with caplog.at_level(logging.ERROR, logger="football_core.freshness"):
        try:
            freshness.update_ledger(ledger, "worldcup", {"stale": True})
        except Exception:  # noqa: BLE001 - the re-raise is the contract
            raised = True
        else:
            raised = False

    assert raised, "a failed ledger write must re-raise, not return silently"
    failures = [r for r in caplog.records if r.exc_info is not None]
    assert failures, (
        "logger.exception never fired — a swallowed ledger write is the exact "
        "defect HARD-02 exists to ratchet out"
    )
    assert all(r.levelno >= logging.ERROR for r in failures)


# ── loud read ───────────────────────────────────────────────────────────────


def test_corrupt_ledger_reads_as_unreadable_not_empty(tmp_path, caplog):
    """Corrupt file => explicit marker + logged traceback, never ``{}``."""
    ledger = tmp_path / "last_refresh.json"
    ledger.write_text("{ this is not json", encoding="utf-8")

    with caplog.at_level(logging.ERROR, logger="football_core.freshness"):
        data = freshness.read_ledger(ledger)

    assert data["ledger"] == "unreadable"
    assert isinstance(data["detail"], str) and data["detail"], (
        "the unreadable marker must carry the exception class"
    )
    assert "Error" in data["detail"], f"detail must be an exception class: {data!r}"
    assert data != {}, "'{}' means 'nothing recorded', not 'could not read'"


def test_missing_ledger_is_empty_not_unreadable(tmp_path, caplog):
    """A ledger that has never been written is legitimately empty (not an error)."""
    with caplog.at_level(logging.ERROR, logger="football_core.freshness"):
        data = freshness.read_ledger(tmp_path / "never-written.json")
    assert data == {}
    assert not [r for r in caplog.records if r.exc_info is not None]


def test_read_is_locked_against_a_concurrent_write(tmp_path):
    """read_ledger takes the same lock: it never observes a half-written file."""
    ledger = tmp_path / "last_refresh.json"
    freshness.update_ledger(ledger, "ucl", {"stale": False})
    seen: list[dict] = []

    def reader() -> None:
        for _ in range(100):
            seen.append(freshness.read_ledger(ledger))

    t = threading.Thread(target=reader)
    writer_ok = {"done": False}

    def writer() -> None:
        for i in range(100):
            freshness.update_ledger(ledger, f"w{i:03d}", {"i": i})
        writer_ok["done"] = True

    t2 = threading.Thread(target=writer)
    t.start()
    t2.start()
    t.join()
    t2.join()

    assert writer_ok["done"]
    assert all(isinstance(s, dict) for s in seen)
    # every observation is a complete JSON document (marker never appears)
    assert all(s.get("ledger") != "unreadable" for s in seen)


# ── D-12: staleness rule ────────────────────────────────────────────────────


def test_is_stale_when_last_success_at_is_missing():
    """Missing timestamp can never render as fresh (D-12 clause 1)."""
    assert freshness.is_stale({}, previous_last_success_at=None, store_mtime=0.0) is True
    assert (
        freshness.is_stale(
            {"last_success_at": None},
            previous_last_success_at=None,
            store_mtime=0.0,
        )
        is True
    )


def test_is_stale_when_last_success_at_does_not_advance():
    """Non-advancing timestamp reads stale (D-12 clause 2)."""
    advanced = _iso(NOW)
    previous = _iso(NOW - timedelta(hours=1))

    # unchanged between two reads
    assert (
        freshness.is_stale(
            {"last_success_at": advanced},
            previous_last_success_at=advanced,
            store_mtime=0.0,
        )
        is True
    )
    # went BACKWARDS (clock skew / ledger restored from backup)
    assert (
        freshness.is_stale(
            {"last_success_at": previous},
            previous_last_success_at=advanced,
            store_mtime=0.0,
        )
        is True
    )
    # first observation ever: nothing to compare against => not stale on this rule
    assert (
        freshness.is_stale(
            {"last_success_at": advanced},
            previous_last_success_at=None,
            store_mtime=0.0,
        )
        is False
    )


def test_is_stale_when_store_is_newer_than_the_ledger_timestamp():
    """Out-of-band store write the ledger never saw (D-12 clause 3)."""
    ts = _iso(NOW)
    entry = {"last_success_at": ts}

    # store touched 5s after the recorded success => stale
    assert (
        freshness.is_stale(
            entry, previous_last_success_at=None, store_mtime=NOW.timestamp() + 5
        )
        is True
    )
    # within the 1-second FAT-timestamp tolerance => fresh
    assert (
        freshness.is_stale(
            entry, previous_last_success_at=None, store_mtime=NOW.timestamp() + 0.5
        )
        is False
    )
    # store older than the recorded success => fresh
    assert (
        freshness.is_stale(
            entry, previous_last_success_at=None, store_mtime=NOW.timestamp() - 30
        )
        is False
    )


def test_is_stale_accepts_z_suffix_and_offset_iso_strings():
    """The codebase emits both ``...+00:00`` and ``...Z``; both parse tz-aware."""
    zed = NOW.isoformat().replace("+00:00", "Z")
    assert (
        freshness.is_stale(
            {"last_success_at": zed},
            previous_last_success_at=None,
            store_mtime=NOW.timestamp() - 30,
        )
        is False
    )
    assert (
        freshness.is_stale(
            {"last_success_at": zed},
            previous_last_success_at=None,
            store_mtime=NOW.timestamp() + 30,
        )
        is True
    )


def test_is_stale_fresh_when_everything_agrees():
    """The control: a coherent, advancing, newer-than-store entry is fresh."""
    assert (
        freshness.is_stale(
            {"last_success_at": _iso(NOW)},
            previous_last_success_at=_iso(NOW - timedelta(hours=1)),
            store_mtime=NOW.timestamp() - 10,
        )
        is False
    )


# ── D-12 as served: an app never claims fresh what it cannot prove ──────────


def _touch(path: Path, when: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}", encoding="utf-8")
    stamp = when.timestamp()
    os.utime(path, (stamp, stamp))


def _seed_wc_stores(stores: Path) -> None:
    """Valid World Cup store set in a tmp dir (repo data; skips on a clone)."""
    import arch_util as au

    au.seed_wc_dir(stores)


def _wc_ledger(tmp_path: Path, entry: dict) -> Path:
    ledger = tmp_path / "last_refresh.json"
    ledger.write_text(json.dumps({"worldcup": entry}), encoding="utf-8")
    return ledger


def test_served_stale_uses_last_refresh_and_skips_absent_stores():
    """UCL/LaLiga record ``last_refresh`` — the same rule must apply there."""
    old = NOW.timestamp() - 30
    ahead = NOW.timestamp() + 30

    # fresh record + store untouched since => fresh
    assert freshness.served_stale({"last_refresh": _iso(NOW)}, [old]) is False
    # store written after the recorded refresh => stale
    assert freshness.served_stale({"last_refresh": _iso(NOW)}, [ahead]) is True
    # no store to compare (absent file) => the timestamp alone decides
    assert freshness.served_stale({"last_refresh": _iso(NOW)}, [None, None]) is False
    # neither timestamp at all => never fresh (clause 1)
    assert freshness.served_stale({}, [None]) is True
    assert freshness.served_stale({"stale": False}, []) is True
    # when both fields exist, ``last_success_at`` is the recorded instant
    both = {
        "last_success_at": _iso(NOW),
        "last_refresh": _iso(NOW - timedelta(days=1)),
    }
    assert freshness.served_stale(both, [old]) is False
    assert freshness.served_stale(both, [ahead]) is True


def test_wc_served_report_goes_stale_when_the_store_moved_on(tmp_path, monkeypatch):
    """Ledger claims fresh, store written afterwards => served as stale (D-12)."""
    from web import wc_app

    stores = tmp_path / "wc"
    _seed_wc_stores(stores)
    entry = {"success": True, "stale": False, "last_success_at": _iso(NOW)}
    ledger = _wc_ledger(tmp_path, entry)
    monkeypatch.setattr(wc_app, "_refresh_report_path", lambda: ledger)
    monkeypatch.setattr(wc_app, "DATA_DIR", stores)

    # control: both factual stores predate the recorded success => still fresh
    _touch(stores / "played.json", NOW - timedelta(minutes=5))
    _touch(stores / "played_groups.json", NOW - timedelta(minutes=5))
    assert wc_app._current_refresh_report()["stale"] is False

    # out-of-band write the ledger never saw => stale, success untouched
    _touch(stores / "played.json", NOW + timedelta(minutes=5))
    report = wc_app._current_refresh_report()
    assert report["stale"] is True
    assert report["success"] is True, "D-12 only upgrades the stale flag"


def test_api_data_serves_stale_when_the_store_outgrew_the_ledger(
    tmp_path, monkeypatch
):
    """/api/data flips refresh.stale for a store write the ledger never saw."""
    from fastapi.testclient import TestClient

    from web import wc_app

    stores = tmp_path / "wc"
    _seed_wc_stores(stores)
    entry = {"success": True, "stale": False, "last_success_at": _iso(NOW)}
    ledger = _wc_ledger(tmp_path, entry)
    monkeypatch.setattr(wc_app, "_refresh_report_path", lambda: ledger)
    monkeypatch.setattr(wc_app, "DATA_DIR", stores)
    _touch(stores / "played.json", NOW + timedelta(minutes=5))
    _touch(stores / "played_groups.json", NOW + timedelta(minutes=5))

    # Reads are pure (plan 02-06): GET /api/data never acquires, so this
    # test reads the served block without any disarm — and without the
    # risk of a real refresh into the repo store (unpatched paths).
    with TestClient(wc_app.wc_app) as client:
        payload = client.get("/api/data").json()

    refresh = payload.get("refresh")
    assert isinstance(refresh, dict), payload
    assert refresh["stale"] is True
    assert refresh["success"] is True


def test_ucl_served_refresh_goes_stale_when_the_store_moved_on(tmp_path, monkeypatch):
    """The UCL serving path applies the same D-12 gate (``last_refresh``)."""
    from web import ucl_app

    season = "2026/27"
    data_dir = tmp_path / "ucl"
    data_dir.mkdir(parents=True, exist_ok=True)
    results = data_dir / "results.json"
    results.write_text(json.dumps({"matches": []}), encoding="utf-8")

    entry = {"success": True, "stale": False, "last_refresh": _iso(NOW)}
    ledger = tmp_path / "last_refresh.json"
    ledger.write_text(json.dumps({"ucl_seasons": {season: entry}}), encoding="utf-8")

    monkeypatch.setattr(ucl_app, "_refresh_report_path", lambda: ledger)
    monkeypatch.setattr(ucl_app, "DATA_DIR", data_dir)
    monkeypatch.setattr(ucl_app, "_refresh_report", {})
    monkeypatch.setattr(ucl_app, "_refresh_reports", {})
    monkeypatch.setattr(ucl_app, "_refresh_reports_seeded", False)

    # control: store older than the recorded refresh => fresh
    _touch(results, NOW - timedelta(minutes=5))
    assert ucl_app._refresh_report_for(season)["stale"] is False

    # out-of-band write after the recorded refresh => served stale
    _touch(results, NOW + timedelta(minutes=5))
    report = ucl_app._refresh_report_for(season)
    assert report["stale"] is True
    assert report["success"] is True


# ── D-18: no hand-rolled read-modify-write survives ─────────────────────────


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _inline_rmw_violations() -> list[str]:
    """``Path.write_text(json.dumps(...))`` call sites outside the fixture."""
    sanctioned = {
        f"{d['path']}::{d['symbol']}"
        for d in json.loads(DEFERRED_FIXTURE.read_text(encoding="utf-8"))
    }
    violations: list[str] = []
    for path in FORMER_RMW_FILES:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        stack = ["<module>"]

        class Visitor(ast.NodeVisitor):
            def visit_FunctionDef(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_AsyncFunctionDef(self, node):  # pragma: no cover - symmetry
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            def visit_Call(self, node):
                if (
                    isinstance(node.func, ast.Attribute)
                    and node.func.attr in {"write_text", "write_bytes"}
                    and any(
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "dumps"
                        for n in ast.walk(node)
                    )
                ):
                    key = f"{_rel(path)}::{stack[-1]}"
                    if key not in sanctioned:
                        violations.append(f"{key}:{node.lineno}")
                self.generic_visit(node)

        Visitor().visit(tree)
    return violations


def test_inline_ledger_read_modify_write_is_gone():
    """D-18: the RMW now lives in football_core.freshness and nowhere else."""
    found = _inline_rmw_violations()
    assert found == [], (
        "hand-rolled json.dumps + Path.write_text RMW survived the conversion "
        f"(add nothing new; fix the site): {found}"
    )
