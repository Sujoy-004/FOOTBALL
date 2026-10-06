"""Fixture-identity contract: three signatures, pinned, deliberately not unified.

A fixture id is the key of every persisted UCL and LaLiga fixture and result
record. Changing how one is derived does not raise an error -- it orphans every
record already on disk, silently, with the pipeline still reporting success.
So the derivation is a *contract*, and this module is its executable form.

The written form is ``docs/FIXTURE-IDENTITY.md``. The two must agree on every
value; the cases below fail if they ever stop agreeing.

The one-line rule, restated here so a reader who never opens the document
still gets it:

    **Changing any of these signatures requires a store migration.**

Three lookalike functions exist and are pinned exactly as they are:

* ``football_core.seasons.derive_fixture_id(namespace, home, away)`` -- the
  generic kernel; the namespace partitions competitions.
* ``competitions.ucl.src.seasons.derive_fixture_id(home, away, event_date)`` --
  its own private implementation; hardcodes its namespace, prefixes ``"gen-"``,
  and **ignores** ``event_date`` entirely.
* ``competitions.laliga.src.seasons.derive_fixture_id(home, away)`` -- a
  two-argument delegation onto the kernel with LaLiga's own namespace.

Unifying them is out of scope (D-27) and is the single change most likely to
be made by someone who has not read this file: it looks like obvious
duplication. It is not. Phase 5's retirement granularity depends on fixture
identity being per-competition, so World Cup retires per match while UCL and
LaLiga ship whole-snapshot retirement. Coarse, but never mis-retiring.

The World Cup has no ``derive_fixture_id`` at all, and that is a decision too
-- see case 7.

Expected values are **hardcoded literals**. A test that re-derives its own
expectation from the implementation proves only that the implementation is
deterministic, which case 6's delegation check already covers; it does not
prove the value is the right one.

Cases 1-5 use ``Manchester City`` / ``Real Madrid`` as the worked example, so
every golden id in this file matches the table in the document verbatim.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

from football_core.seasons import derive_fixture_id

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The worked example. Hardcoded rather than read from a store, so the vectors
#: below cannot drift because a season file was re-ingested.
HOME_TEAM = "Manchester City"
AWAY_TEAM = "Real Madrid"

#: `football_core.seasons.derive_fixture_id` over this basis: no prefix.
KERNEL_GOLDEN_ID = "88e56f07916e27e1"

#: What `competitions.ucl.src.seasons.derive_fixture_id` returns for the same
#: pair: the same 16 hex chars, behind the `"gen-"` prefix.
UCL_GOLDEN_ID = "gen-88e56f07916e27e1"

#: ...and with home/away reversed.
UCL_GOLDEN_REVERSED_ID = "gen-e4e36ce7b6753960"

#: The namespace UCL hardcodes into its own hash basis. Unlike LaLiga's, it is
#: not a named constant anywhere -- it is a string literal inside the function,
#: which is part of why it has to be pinned here.
UCL_HARDCODED_NAMESPACE = "ucl-season-fixture"


# ── case 1: the kernel signature, exact value ──────────────────────────────


def test_kernel_fixture_id_is_the_documented_golden_vector():
    """Case 1: `(namespace, home, away)` -> the exact documented id."""
    fid = derive_fixture_id(UCL_HARDCODED_NAMESPACE, HOME_TEAM, AWAY_TEAM)

    assert fid == KERNEL_GOLDEN_ID, (
        "the kernel fixture id moved. Every UCL and LaLiga fixture and result "
        "record already on disk is keyed by this value; a change here is a "
        f"store migration, not an edit. got {fid!r}, expected "
        f"{KERNEL_GOLDEN_ID!r}"
    )
    assert len(fid) == 16 and all(c in "0123456789abcdef" for c in fid)
    assert not fid.startswith("gen-"), (
        "the kernel never prefixes; only UCL's own implementation does. A "
        f"prefixed result means {fid!r} is a different function than the one "
        "this contract documents."
    )


# ── case 2: the namespace genuinely partitions ─────────────────────────────


def test_kernel_fixture_id_is_namespace_partitioned():
    """Case 2: same teams, two competitions' namespaces -> two different ids."""
    from competitions.laliga.src import seasons as laliga_seasons

    ucl = derive_fixture_id(UCL_HARDCODED_NAMESPACE, HOME_TEAM, AWAY_TEAM)
    laliga = derive_fixture_id(laliga_seasons.SEASON_NAMESPACE, HOME_TEAM, AWAY_TEAM)

    assert ucl != laliga, (
        "two competitions' namespaces produced the same id for the same pair, "
        "so the namespace is not participating in the hash. That is a "
        "cross-competition collision: one team's records would collide."
    )


# ── case 3: home and away are ordered positions ────────────────────────────


def test_kernel_fixture_id_is_ordered_not_a_set():
    """Case 3: reversing home/away is a different fixture, not the same one."""
    forward = derive_fixture_id(UCL_HARDCODED_NAMESPACE, HOME_TEAM, AWAY_TEAM)
    reverse = derive_fixture_id(UCL_HARDCODED_NAMESPACE, AWAY_TEAM, HOME_TEAM)

    assert forward != reverse, (
        "the kernel sorted or otherwise normalised the pair. home and away are "
        "positions in a fixture, so a swap is a different match; normalising "
        "them merges every fixture with its reverse fixture."
    )


# ── case 4: UCL's signature, and the date-collision that is on purpose ─────


def test_ucl_fixture_id_is_the_documented_golden_vector():
    """Case 4: `(home, away, event_date)` -> the exact documented id, dated or not.

    The second assertion is the load-bearing one in this whole file. UCL writes
    provisional drawn fixtures at ``competitions/ucl/src/season_draw.py:161`` as
    ``derive_fixture_id(home, away, None)``, and
    ``competitions/ucl/src/ingest.py:1158`` later enriches them in place with
    the official dated fixture list. That enrichment is an update rather than a
    duplicate *only because* the date is excluded from the hash. The draw
    proposes who plays whom; the fixture confirms it. They are one identity.
    """
    from competitions.ucl.src.seasons import (
        derive_fixture_id as ucl_derive_fixture_id,
    )

    home, away = HOME_TEAM, AWAY_TEAM

    fid = ucl_derive_fixture_id(home, away, "2026-11-04")

    assert fid == UCL_GOLDEN_ID, (
        "the UCL fixture id moved. UCL's league-phase fixtures and results are "
        "persisted under `gen-`-prefixed ids; changing this orphans them. "
        f"got {fid!r}, expected {UCL_GOLDEN_ID!r}"
    )
    assert fid.startswith("gen-") and len(fid) == len("gen-") + 16

    # ...and the date is excluded, so the draw and the fixture are one identity.
    drawn = ucl_derive_fixture_id(home, away, None)

    assert drawn == fid, (
        "the provisional draw and the official dated fixture no longer produce "
        "the same id, which means the date has entered the hash. That is not a "
        "bug fix: it splits one fixture into two identities, so the official "
        "ingest appends duplicates instead of enriching the drawn rows in "
        "place, and both records then claim to be the same match."
    )
    assert drawn == UCL_GOLDEN_ID


# ── case 5: UCL's prefix and the reversed pair ─────────────────────────────


def test_ucl_reversed_pair_is_the_documented_golden_id():
    """Case 5: the reverse fixture has its own documented value, `"gen-"` first."""
    from competitions.ucl.src.seasons import (
        derive_fixture_id as ucl_derive_fixture_id,
    )

    fid = ucl_derive_fixture_id(AWAY_TEAM, HOME_TEAM, "2026-11-04")

    assert fid == UCL_GOLDEN_REVERSED_ID, (
        "the reversed UCL fixture id moved, which means UCL's implementation "
        "stopped being a pure function of the ordered pair. "
        f"got {fid!r}, expected {UCL_GOLDEN_REVERSED_ID!r}"
    )
    assert fid.startswith("gen-")
    assert fid != UCL_GOLDEN_ID


# ── case 6: LaLiga delegates onto the kernel with its own namespace ────────


def test_laliga_delegates_to_the_kernel_with_its_own_namespace():
    """Case 6: LaLiga's 2-arg form is the kernel under a LaLiga namespace.

    The namespace is read from the module, never hardcoded, so this stays
    correct if the constant is renamed or its value changes *together with* the
    delegating call. What is pinned is the shape: LaLiga owns a namespace and
    hands it to the kernel. Its actual value is checked against a real
    competitor in case 2.
    """
    from competitions.laliga.src import seasons as laliga_seasons

    home, away = "FC Barcelona", "Real Madrid CF"

    first = laliga_seasons.derive_fixture_id(home, away)
    second = laliga_seasons.derive_fixture_id(home, away)
    reversed_ = laliga_seasons.derive_fixture_id(away, home)
    expected = derive_fixture_id(laliga_seasons.SEASON_NAMESPACE, home, away)

    assert first == second, "LaLiga's fixture id is not deterministic"
    assert first == expected, (
        "LaLiga's wrapper no longer delegates to football_core.seasons with "
        "SEASON_NAMESPACE. If that is deliberate it is a contract change, and "
        "every persisted LaLiga fixture and result record is keyed by it."
    )
    assert first != reversed_, "LaLiga's fixture id stopped being order-sensitive"
    assert not first.startswith("gen-"), (
        "LaLiga ids are bare 16 hex chars; the `gen-` prefix is UCL's alone, "
        f"got {first!r}"
    )


# ── case 7: the World Cup's absence is a decision, not an oversight ─────────


def test_world_cup_has_no_derive_fixture_id():
    """Case 7: the World Cup brain deliberately derives no fixture id.

    DECISION (D-27/D-28), not an oversight. The World Cup is a fixed tournament
    bracket, not a repeated home/away season: there is no (home, away)
    relationship to hash, and a bracket fixture's identity is its stage plus
    its slot, not a team pairing. Successor: Phase 5 reconciles the World Cup
    per match through the shared fixture vocabulary in
    ``football_core.domain``, which is where a per-match World Cup identity
    belongs.

    Adding a ``derive_fixture_id`` to ``competitions/worldcup/src/`` to "make
    the three consistent" would invent an identity for records that already have
    one, and would be the first step toward the unification D-27 forbids.
    """
    pipeline = importlib.import_module("competitions.worldcup.src.pipeline")
    assert not hasattr(pipeline, "derive_fixture_id"), (
        "competitions.worldcup.src.pipeline now exposes derive_fixture_id. The "
        "World Cup is a fixed tournament bracket and deliberately has no "
        "fixture-id derivation (D-27/D-28); its per-match identity belongs in "
        "Phase 5's shared fixture vocabulary, not in a home/away hash."
    )

    # The absence holds across the whole brain, not just the pipeline. An AST
    # walk rather than a regex, so a definition, a re-export, or a lazy
    # function-local import in any module is caught too.
    offenders: list[str] = []
    for path in sorted((REPO_ROOT / "competitions" / "worldcup" / "src").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == "derive_fixture_id":
                    offenders.append(f"{path.name}:{node.lineno} (definition)")
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name.split(".")[-1] == "derive_fixture_id":
                        offenders.append(
                            f"{path.name}:{node.lineno} (imported as "
                            f"{alias.asname or alias.name})"
                        )
    assert not offenders, (
        "the World Cup brain now references derive_fixture_id:\n  "
        + "\n  ".join(offenders)
        + "\nIts absence is D-27/D-28's deliberate decision. Do not add it to "
        "match the other two competitions."
    )