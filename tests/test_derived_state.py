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

import os
from dataclasses import FrozenInstanceError
from pathlib import Path

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
