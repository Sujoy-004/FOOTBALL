"""Wave-0 contract tests for the race-free derived-state substrate (RECON-03/04).

These tests pin the two primitives that every web sub-app migrates onto in
plans 04-02..04-04:

* :func:`football_core.store_stamp.stamp_store` — a **content-independent**,
  **role-keyed** freshness stamp built from ``os.stat`` metadata alone. A
  request handler decides "my cache is fresh" from ONE comparison of
  ``(role, mtime_ns, size)`` — store contents are never re-read or diffed
  (D-02/D-03, RECON-03).
* the ``web/derived/`` holder — a per-competition single-reference frozen
  snapshot rebound in a single assignment (D-01, RECON-04). Holder tests live
  in the same file (plan task 2) so the package-level contract is one suite.

The stamp keys on the LOGICAL ROLE (``"results"``, ``"fixtures"`` …), never on
the filename or the contents: a missing role file is ABSENCE (omitted from
``entries``), not a zero entry, and an unrelated file in the directory never
changes the stamp.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest

from football_core.store_stamp import StoreStamp, stamp_store


def _stat_ns_size(path: Path) -> tuple[int, int]:
    st = path.stat()
    return st.st_mtime_ns, st.st_size


def test_stamp_store_keys_on_role(tmp_path: Path) -> None:
    """``(role, mtime_ns, size)`` for each present store, keyed by ROLE."""
    (tmp_path / "results.json").write_text('{"matches": []}', encoding="utf-8")
    stamp = stamp_store(tmp_path, {"results": "results.json"})
    mtime_ns, size = _stat_ns_size(tmp_path / "results.json")
    assert stamp.entries == (("results", mtime_ns, size),)
    assert stamp.as_dict() == {"results": [mtime_ns, size]}


def test_stamp_store_omits_missing_role_file(tmp_path: Path) -> None:
    """A MISSING role file is absent from ``entries`` entirely — never a zero."""
    (tmp_path / "results.json").write_text("x", encoding="utf-8")
    stamp = stamp_store(
        tmp_path, {"results": "results.json", "fixtures": "fixtures.json"}
    )
    roles = [entry[0] for entry in stamp.entries]
    assert roles == ["results"]


def test_stamp_store_rewrite_changes_stamp(tmp_path: Path) -> None:
    """A rewrite moves the file, so the stamp is not equal to the old one."""
    path = tmp_path / "results.json"
    path.write_text('{"matches": []}', encoding="utf-8")
    before = stamp_store(tmp_path, {"results": "results.json"})
    # Force a distinct nanosecond mtime: same-size rewrite would otherwise be
    # the only robust distinguisher on a coarse filesystem.
    st = path.stat()
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    after = stamp_store(tmp_path, {"results": "results.json"})
    assert after != before


def test_stamp_store_ignores_unrelated_files(tmp_path: Path) -> None:
    """An unrelated new file in the dir does NOT change the stamp (roles explicit)."""
    (tmp_path / "results.json").write_text("x", encoding="utf-8")
    before = stamp_store(tmp_path, {"results": "results.json"})
    (tmp_path / "unrelated.txt").write_text("hello", encoding="utf-8")
    after = stamp_store(tmp_path, {"results": "results.json"})
    assert before == after


def test_stamp_store_role_mapping_is_the_key(tmp_path: Path) -> None:
    """Renaming the ROLE (not the file) changes the entry's role key."""
    (tmp_path / "results.json").write_text("x", encoding="utf-8")
    stamp = stamp_store(tmp_path, {"fixtures": "results.json"})
    assert stamp.entries[0][0] == "fixtures"


def test_store_stamp_is_frozen() -> None:
    """``StoreStamp`` is a frozen value object — assignment raises."""
    stamp = StoreStamp(entries=())
    with pytest.raises(FrozenInstanceError):
        stamp.entries = (("results", 1, 2),)  # type: ignore[misc]


def test_role_maps_map_logical_role_to_filename() -> None:
    """The three competition role maps carry the documented filenames."""
    from web.derived.stamps import LALIGA_ROLES, UCL_ROLES, WC_ROLES

    assert UCL_ROLES == {
        "league_results": "results.json",
        "fixtures": "fixtures.json",
        "knockout_results": "knockout_results.json",
    }
    assert LALIGA_ROLES == {
        "fixtures": "fixtures.json",
        "results": "results.json",
    }
    assert WC_ROLES == {
        "teams": "teams.json",
        "groups": "groups.json",
        "bracket": "bracket.json",
        "annex_c": "annex_c.json",
        "played": "played.json",
        "played_groups": "played_groups.json",
    }


# ── Holder (plan task 2): frozen single-ref snapshot + sim slot ──────────────


def test_freeze_blocks_mutation_at_every_depth() -> None:
    """Recursive freeze: dict->proxy, list/tuple->tuple, set->frozenset."""
    from web.derived.holder import _freeze

    frozen = _freeze({"a": {"b": [1, {"c": 2}]}})
    assert isinstance(frozen, MappingProxyType)
    assert isinstance(frozen["a"], MappingProxyType)
    assert isinstance(frozen["a"]["b"], tuple)
    assert isinstance(frozen["a"]["b"][1], MappingProxyType)
    with pytest.raises(TypeError):
        frozen["x"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen["a"]["x"] = 1  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen["a"]["b"][0] = 99  # type: ignore[index]
    with pytest.raises(TypeError):
        frozen["a"]["b"][1]["x"] = 1  # type: ignore[index]


def test_get_or_rebuild_reuses_snapshot_when_stamp_unchanged() -> None:
    """A stamp-equal read returns the SAME object and never calls build again."""
    from web.derived.holder import get_or_rebuild, read_stamp, reset

    reset("ucl")
    calls: list[int] = []

    def build():
        calls.append(1)
        return {"teams": ["A"]}, "results"

    stamp = StoreStamp(entries=(("results", 1, 10),))
    first = get_or_rebuild("ucl", stamp, build)
    assert len(calls) == 1
    second = get_or_rebuild("ucl", stamp, build)
    assert second is first
    assert len(calls) == 1
    assert read_stamp("ucl") == stamp


def test_get_or_rebuild_rebuilds_when_stamp_changes() -> None:
    """A changed stamp rebuilds once and publishes the new stamp atomically."""
    from web.derived.holder import get_or_rebuild, read_stamp, reset

    reset("ucl")

    def build_a():
        return {"teams": ["A"]}, "results"

    def build_b():
        return {"teams": ["A", "B"]}, "results"

    s1 = StoreStamp(entries=(("results", 1, 10),))
    s2 = StoreStamp(entries=(("results", 2, 10),))
    first = get_or_rebuild("ucl", s1, build_a)
    second = get_or_rebuild("ucl", s2, build_b)
    assert second is not first
    assert second == {"teams": ("A", "B")}
    assert read_stamp("ucl") == s2


def test_publish_sim_read_sim_clear_sim() -> None:
    """The sim slot is a frozen single reference; clear rebinds to {}."""
    from web.derived.holder import clear_sim, publish_sim, read_sim, reset

    reset("ucl")
    assert read_sim("ucl") == {}
    publish_sim("ucl", {"status": "completed", "teams": ["A"]})
    sim = read_sim("ucl")
    assert sim == {"status": "completed", "teams": ("A",)}
    with pytest.raises(TypeError):
        sim["status"] = "failed"  # type: ignore[index]
    clear_sim("ucl")
    assert read_sim("ucl") == {}


def test_reset_clears_state_and_sim() -> None:
    """reset(comp) clears both the snapshot and the sim slot."""
    from web.derived.holder import (
        publish_data,
        publish_sim,
        read_data,
        read_mode,
        read_sim,
        read_stamp,
        reset,
    )

    reset("ucl")
    publish_data("ucl", {"x": 1}, "results", StoreStamp(entries=()))
    publish_sim("ucl", {"status": "completed"})
    reset("ucl")
    assert read_data("ucl") == {}
    assert read_sim("ucl") == {}
    assert read_stamp("ucl") is None
    assert read_mode("ucl") is None


def test_read_path_never_mutates_published_state() -> None:
    """Readers are idempotent and return immutable views (RECON-04)."""
    from web.derived.holder import publish_data, read_data, read_mode, read_sim, reset

    reset("ucl")
    publish_data("ucl", {"teams": ["A"]}, "results",
                  StoreStamp(entries=(("results", 1, 5),)))
    before = read_data("ucl")
    assert read_data("ucl") is before
    assert read_mode("ucl") == "results"
    assert read_data("ucl") == {"teams": ("A",)}
    assert read_sim("ucl") == {}
    with pytest.raises(TypeError):
        before["teams"] = ("B",)  # type: ignore[index]


def test_json_default_serializes_frozen_containers() -> None:
    """``_json_default`` handles MappingProxyType and frozenset."""
    from web.common import _json_default

    out = json.dumps(
        {"x": MappingProxyType({"y": 1}), "c": frozenset([1, 2])},
        default=_json_default,
    )
    assert json.loads(out) == {"x": {"y": 1}, "c": [1, 2]}


def test_boot_ledger_publish_append_reset() -> None:
    """Boot ledger is an immutable tuple slot; append is lost-update safe."""
    from web.derived.holder import (
        append_boot,
        publish_boot,
        read_boot,
        reset,
    )

    reset("ucl")
    publish_boot("ucl", [{"step": "a"}])
    append_boot("ucl", {"step": "b"})
    assert read_boot("ucl") == ({"step": "a"}, {"step": "b"})
    reset("ucl")
    assert read_boot("ucl") == ()


def test_append_boot_is_lost_update_safe_under_threads() -> None:
    """Two concurrent appends under one lock both survive (no lost update)."""
    from web.derived.holder import append_boot, publish_boot, read_boot, reset

    reset("ucl")
    publish_boot("ucl", [])
    barrier = threading.Barrier(2)

    def append(entry: dict) -> None:
        barrier.wait()
        append_boot("ucl", entry)

    t1 = threading.Thread(target=append, args=({"step": "a"},))
    t2 = threading.Thread(target=append, args=({"step": "b"},))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    entries = read_boot("ucl")
    assert len(entries) == 2
    assert {e["step"] for e in entries} == {"a", "b"}
