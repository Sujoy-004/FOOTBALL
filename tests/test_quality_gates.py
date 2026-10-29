"""Unified Quality Gate & Section J Invariants Suite (D-04, HARD-04).

Enforces repo-wide architectural invariants mechanically via AST inspection
and domain contract proofs. Section J invariant coverage:

  1. Bare ``except: pass`` ratchet.
  2. Zero brain-to-web imports (``competitions/*/src`` must not import ``web``).
  3. Zero kernel upward imports (``football_core`` must not import
     ``competitions``/``web``).
  4. Simulation engines are pure in-memory (no file-writing calls).
  5. Ingestion contract: zero ingested matches can never claim success.
  6. Fixture uniqueness and orphan prevention across all three competitions.
  7. Standings simulation invariance (FMT-04) contract suite presence.
  8. Simulation run provenance (``seed``/``n_simulations``/``provenance``).
  9. Secret hygiene: zero committed API keys in tracked sources.

Invariant 1 is the targeted swallow lens (bare ``except: pass`` only) and is
complemented by the broader swallowed-exception ratchet in
``tests/test_hard02_swallow_sites.py`` (D-30 noqa ratchet).

All detectors are pure functions over parsed ASTs / raw sources so the suite
verifies each gate in BOTH directions: real-tree violations fail the specific
invariant gate, and synthetic violating snippets are asserted to be caught by
the same detectors (non-vacuity self-checks, D-32 pattern from
``test_layering_architecture.py``).
"""

from __future__ import annotations

import ast
import inspect
import json
import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

SCAN_ROOTS: tuple[str, ...] = ("football_core", "web", "competitions")

# ---------------------------------------------------------------------------
# Section J invariant 1: bare ``except: pass`` ratchet
# ---------------------------------------------------------------------------

# ``<file>::<enclosing-symbol>`` for every sanctioned bare swallow site.
# The ratchet is exact and two-way: any NEW site fails, and a site whose
# swallow was removed must also drop its entry (no stale entries allowed).
SANCTIONED_PASS_SITES: dict[str, str] = {
    "football_core/state.py::atomic_write_text": (
        "best-effort os.unlink(tmp_path) on the atomic-write failure path; "
        "cleanup must not mask the original raise"
    ),
    "competitions/ucl/src/seasons.py::normalize_season_token": (
        "recursive int fast-path fallback: the nested call raises ValueError "
        "for bare-year tokens; swallowing falls through to the regex parse"
    ),
    "competitions/ucl/src/shadow_eval.py::refreeze_production": (
        "best-effort os.unlink(tmp_results_path) in the finally block; "
        "cleanup must not mask the primary evaluation result"
    ),
}


def _is_test(path: pathlib.Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def _non_test_py_files(root_name: str) -> list[pathlib.Path]:
    return sorted(
        p for p in (ROOT / root_name).rglob("*.py") if not _is_test(p)
    )


def _handler_symbols(tree: ast.AST) -> dict[int, str]:
    """Map ``id(ExceptHandler)`` to the nearest enclosing def/class name."""
    out: dict[int, str] = {}

    def visit(node: ast.AST, symbol: str) -> None:
        for child in ast.iter_child_nodes(node):
            child_symbol = symbol
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                child_symbol = child.name
            if isinstance(child, ast.ExceptHandler):
                out[id(child)] = child_symbol
            visit(child, child_symbol)

    visit(tree, "<module>")
    return out


def _find_bare_swallows(source: str) -> list[tuple[str, int]]:
    """Return ``(enclosing_symbol, line)`` for every bare ``except: pass``."""
    tree = ast.parse(source)
    symbols = _handler_symbols(tree)
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ExceptHandler)
            and len(node.body) == 1
            and isinstance(node.body[0], ast.Pass)
        ):
            out.append((symbols.get(id(node), "<module>"), node.lineno))
    return out


def _collect_repo_swallow_sites() -> tuple[list[str], int]:
    """Walk ``SCAN_ROOTS``; return ``([f'{rel}::{symbol}'], parse_failures)``."""
    sites: list[str] = []
    parse_failures = 0
    for root_name in SCAN_ROOTS:
        for path in _non_test_py_files(root_name):
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                parse_failures += 1
                continue
            try:
                ast.parse(source, filename=str(path))
            except (SyntaxError, ValueError, UnicodeDecodeError):
                parse_failures += 1
                continue
            rel = path.relative_to(ROOT).as_posix()
            for symbol, _lineno in _find_bare_swallows(source):
                sites.append(f"{rel}::{symbol}")
    return sites, parse_failures


def test_no_unsanctioned_bare_except_pass() -> None:
    sites, parse_failures = _collect_repo_swallow_sites()
    assert parse_failures == 0, (
        f"Unparseable non-test files under {SCAN_ROOTS}: {parse_failures}"
    )
    unsanctioned = sorted(set(sites) - set(SANCTIONED_PASS_SITES))
    stale = sorted(set(SANCTIONED_PASS_SITES) - set(sites))
    assert not unsanctioned, f"Unsanctioned bare except: pass sites: {unsanctioned}"
    assert not stale, (
        f"Stale ratchet entries: sanctioned sites no longer exist, "
        f"remove them from SANCTIONED_PASS_SITES: {stale}"
    )


def test_gate_swallow_detector_flags_synthetic_violations() -> None:
    """Non-vacuity: the swallow detector must catch synthetic violations."""
    function_scoped = (
        "def f():\n"
        "    try:\n"
        "        do_work()\n"
        "    except Exception:\n"
        "        pass\n"
    )
    module_scoped = (
        "try:\n"
        "    boot()\n"
        "except Exception:\n"
        "    pass\n"
    )
    class_scoped = (
        "class C:\n"
        "    def m(self):\n"
        "        try:\n"
        "            step()\n"
        "        except Exception:\n"
        "            pass\n"
    )
    assert _find_bare_swallows(function_scoped) == [("f", 4)]
    assert _find_bare_swallows(module_scoped) == [("<module>", 3)]
    assert _find_bare_swallows(class_scoped) == [("m", 5)]

    # Negative controls: handled exceptions are not bare swallows.
    logging_handler = (
        "import logging\n"
        "def g():\n"
        "    try:\n"
        "        do_work()\n"
        "    except Exception:\n"
        "        logging.exception('failed')\n"
    )
    assert _find_bare_swallows(logging_handler) == []
    non_bare_neutral = (
        "def h():\n"
        "    try:\n"
        "        do_work()\n"
        "    except Exception as exc:\n"
        "        raise RuntimeError('retrace') from exc\n"
    )
    assert _find_bare_swallows(non_bare_neutral) == []


# ---------------------------------------------------------------------------
# Section J invariants 2 & 3: layering boundaries (brain->web, kernel-upward)
# ---------------------------------------------------------------------------


def _import_roots(tree: ast.AST) -> list[tuple[int, str]]:
    """Collect ``(lineno, module_root)`` for absolute import statements.

    Relative imports (``from . import x``) are intra-package by definition
    and never flagged.
    """
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((node.lineno, alias.name.split(".")[0]))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            out.append((node.lineno, node.module.split(".")[0]))
    return out


def _web_import_offences(tree: ast.AST) -> list[str]:
    return [module for _lineno, module in _import_roots(tree) if module == "web"]


def _kernel_upward_offences(tree: ast.AST) -> list[str]:
    return [
        module
        for _lineno, module in _import_roots(tree)
        if module in ("competitions", "web")
    ]


def test_zero_brain_to_web_imports() -> None:
    brain_files: list[pathlib.Path] = []
    for competition_dir in sorted((ROOT / "competitions").glob("*/src")):
        brain_files.extend(
            p
            for p in competition_dir.rglob("*.py")
            if not _is_test(p)
        )
    # Glob floor self-check: the gate must never pass vacuously because the
    # walk found nothing (three competition brains exist today, each > 10
    # modules).
    assert len(brain_files) >= 40, (
        f"Brain-file audit floor failed: walked {len(brain_files)} files"
    )

    offences: list[str] = []
    for path in brain_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for flag in _web_import_offences(tree):
            offences.append(f"{path.relative_to(ROOT).as_posix()}:{flag}")
    assert offences == [], f"Brain-to-web imports detected: {offences}"


def test_zero_kernel_upward_imports() -> None:
    kernel_files = _non_test_py_files("football_core")
    assert len(kernel_files) >= 20, (
        f"Kernel-file audit floor failed: walked {len(kernel_files)} files"
    )

    offences: list[str] = []
    for path in kernel_files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for flag in _kernel_upward_offences(tree):
            offences.append(f"{path.relative_to(ROOT).as_posix()}:{flag}")
    assert offences == [], f"Kernel upward imports detected: {offences}"


def test_gate_import_detectors_flag_synthetic_violations() -> None:
    """Non-vacuity: both import analyzers must flag synthetic violations."""
    synthetic = (
        "import random\n"
        "import web.cache_control\n"
        "from competitions.worldcup.src import constants\n"
        "from . import relative_ok\n"  # relative imports are never flagged
    )
    tree = ast.parse(synthetic)
    web_hits = _web_import_offences(tree)
    kernel_hits = _kernel_upward_offences(tree)
    assert web_hits == ["web"], f"web import not flagged: {web_hits}"
    assert kernel_hits == ["web", "competitions"], (
        f"kernel-upward imports not flagged: {kernel_hits}"
    )

    clean = (
        "import random\n"
        "from football_core.domain import MatchStatus\n"
        "from . import sibling\n"
    )
    clean_tree = ast.parse(clean)
    assert _web_import_offences(clean_tree) == []
    assert _kernel_upward_offences(clean_tree) == []


# ---------------------------------------------------------------------------
# Section J invariant 4: simulation engines are pure in-memory
# ---------------------------------------------------------------------------

SIM_ENGINE_FILES: tuple[str, ...] = (
    "football_core/simulation.py",
    "competitions/worldcup/src/simulation.py",
    "competitions/ucl/src/simulation.py",
    "competitions/laliga/src/simulation.py",
)

# football_core + ucl + laliga engines exist; worldcup has none today.
MIN_SIM_AUDIT_FILES = 3

_WRITE_ATTR_CALLS = {"write_text", "write_bytes"}
_WRITE_NAME_CALLS = {"atomic_write_text", "atomic_write_json"}
_WRITE_MODE_CHARS = set("wax+")


def _open_write_mode(node: ast.Call) -> str | None:
    """Return the write-mode string of an ``open(...)`` call, else None."""
    mode: str | None = None
    if (
        len(node.args) >= 2
        and isinstance(node.args[1], ast.Constant)
        and isinstance(node.args[1].value, str)
    ):
        mode = node.args[1].value
    for kw in node.keywords:
        if (
            kw.arg == "mode"
            and isinstance(kw.value, ast.Constant)
            and isinstance(kw.value.value, str)
        ):
            mode = kw.value.value
    if mode and set(mode) & _WRITE_MODE_CHARS:
        return mode
    return None


def _file_write_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """Collect ``(lineno, label)`` for file-writing calls in a parsed AST."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if func.attr in _WRITE_ATTR_CALLS:
                out.append((node.lineno, f"...{func.attr}()"))
            elif func.attr == "open":
                mode = _open_write_mode(node)
                if mode:
                    out.append((node.lineno, f"...open(mode={mode!r})"))
        elif isinstance(func, ast.Name):
            if func.id in _WRITE_NAME_CALLS:
                out.append((node.lineno, func.id))
            elif func.id == "open":
                mode = _open_write_mode(node)
                if mode:
                    out.append((node.lineno, f"open(mode={mode!r})"))
    return out


def test_simulation_engines_contain_no_file_writes() -> None:
    audited = 0
    offences: list[str] = []
    for rel in SIM_ENGINE_FILES:
        path = ROOT / rel
        if not path.exists():
            continue
        audited += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offences.extend(
            f"{rel}:{lineno}:{label}" for lineno, label in _file_write_calls(tree)
        )
    assert audited >= MIN_SIM_AUDIT_FILES, (
        f"Simulation-audit floor failed: audited {audited} engines "
        f"(expected >= {MIN_SIM_AUDIT_FILES}); SIM_ENGINE_FILES drifted?"
    )
    assert offences == [], f"File-writing calls in simulation engines: {offences}"


def test_gate_write_detector_flags_synthetic_violations() -> None:
    """Non-vacuity: the write detector must catch synthetic violations."""
    write_text = (
        "from pathlib import Path\n"
        "def persist(path):\n"
        "    Path(path).write_text('data')\n"
    )
    write_bytes = (
        "def b(path):\n"
        "    path.write_bytes(b'x')\n"
    )
    atomic_write = (
        "from football_core.state import atomic_write_text\n"
        "def persist(path):\n"
        "    atomic_write_text(path, 'x')\n"
    )
    atomic_write_json = (
        "def persist(path, data):\n"
        "    atomic_write_json(path, data)\n"
    )
    open_write_kwargs = (
        "def w(path):\n"
        "    fh = open(path, mode='w', encoding='utf-8')\n"
    )
    open_write_positional = (
        "def w(path):\n"
        "    fh = open(path, 'wt')\n"
    )
    open_append = (
        "def a(path):\n"
        "    fh = open(path, 'ab')\n"
    )

    assert len(_file_write_calls(ast.parse(write_text))) == 1
    assert len(_file_write_calls(ast.parse(write_bytes))) == 1
    assert len(_file_write_calls(ast.parse(atomic_write))) == 1
    assert len(_file_write_calls(ast.parse(atomic_write_json))) == 1
    assert len(_file_write_calls(ast.parse(open_write_kwargs))) == 1
    assert len(_file_write_calls(ast.parse(open_write_positional))) == 1
    assert len(_file_write_calls(ast.parse(open_append))) == 1

    # Negative control: read-only opens are not file-writing calls.
    open_read = (
        "def r(path):\n"
        "    fh = open(path, 'rb')\n"
    )
    assert _file_write_calls(ast.parse(open_read)) == []
    open_read_default = (
        "def r(path):\n"
        "    fh = open(path)\n"
    )
    assert _file_write_calls(ast.parse(open_read_default)) == []


# ---------------------------------------------------------------------------
# Section J invariant 5: ingestion contract on zero matches (D-13)
# ---------------------------------------------------------------------------


def test_ingestion_zero_matches_cannot_be_success() -> None:
    """D-13 contract: ``success`` is derived from counters, never declared.

    Pins the full ``derive_success(provider, attempted, finished)`` decision
    table — the zero-match path can never report success, and every
    counter-inconsistent shape fails closed.
    """
    from football_core.fetcher import derive_success

    # Nothing attempted -> deferred, never success.
    assert derive_success("p", False, {"received": 5}) == (False, "deferred")

    # Attempted but zero received (HTTP 200 with empty body) -> provider-empty.
    assert derive_success("p", True, {"received": 0}) == (
        False, "deferred/provider-empty",
    )
    assert derive_success("p", True, {}) == (False, "deferred/provider-empty")

    # Zero ingested matches with zero re-offers -> counters broken -> False.
    assert derive_success("p", True, {
        "received": 1, "normalized": 1, "ingested": 0,
        "skipped_unmatchable": 0, "skipped_no_target": 0,
        "skipped_missing_score": 0,
    }) == (False, "counter_inconsistent")

    # Inconsistent shape #2: measured > counted.
    assert derive_success("p", True, {
        "received": 2, "normalized": 2, "ingested": 3,
        "skipped_unmatchable": 0, "skipped_no_target": 0,
        "skipped_missing_score": 0,
    }) == (False, "counter_inconsistent")

    # Incomplete counters -> fails closed.
    assert derive_success("p", True, {"received": 1}) == (
        False, "counter_inconsistent",
    )

    # D-14 re-offer bucket present but with a bad value -> fails closed.
    assert derive_success("p", True, {
        "received": 1, "normalized": 1, "ingested": 0,
        "skipped_unmatchable": 0, "skipped_no_target": 0,
        "skipped_missing_score": 0, "skipped_no_change": "two",
    }) == (False, "counter_inconsistent")

    # Consistent, real work -> success.
    assert derive_success("p", True, {
        "received": 1, "normalized": 1, "ingested": 1,
        "skipped_unmatchable": 0, "skipped_no_target": 0,
        "skipped_missing_score": 0,
    }) == (True, None)

    # Consistent partition across skip buckets -> legit success.
    assert derive_success("p", True, {
        "received": 2, "normalized": 2, "ingested": 0,
        "skipped_unmatchable": 1, "skipped_no_target": 1,
        "skipped_missing_score": 0,
    }) == (True, None)

    # D-14 re-offer bucket consistent -> legit success.
    assert derive_success("p", True, {
        "received": 2, "normalized": 2, "ingested": 1,
        "skipped_unmatchable": 0, "skipped_no_target": 0,
        "skipped_missing_score": 0, "skipped_no_change": 1,
    }) == (True, None)


# ---------------------------------------------------------------------------
# Section J invariant 6: fixture uniqueness + orphan prevention
# ---------------------------------------------------------------------------

# Loose floors so refactors of source lists cannot starve the gate silently.
_WC_MIN_FIXTURES = 100  # 72 group fixtures + 32 knockout entities
_UCL_MIN_FIXTURES = 100  # 8 Swiss matchdays x 18
_LALIGA_MIN_FIXTURES = 100  # >= 300 for a full 380-fixture season


def _duplicates_in(values: list) -> list:
    """Return duplicates from ``values`` preserving first-seen order."""
    seen: set = set()
    duplicates: list = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return duplicates


def _wc_fixture_ids() -> list[str]:
    wc_data = ROOT / "competitions" / "worldcup" / "data"
    groups = json.loads((wc_data / "groups.json").read_text(encoding="utf-8"))
    bracket = json.loads((wc_data / "bracket.json").read_text(encoding="utf-8"))

    fixture_ids: list[str] = []
    for group in groups.get("groups", {}).values():
        for match in group.get("matches", []):
            if "match_id" in match:
                fixture_ids.append(match["match_id"])
    bracket_matches: list = (
        bracket if isinstance(bracket, list) else bracket.get("matches", [])
    )
    for match in bracket_matches:
        if "match_id" in match:
            fixture_ids.append(match["match_id"])
    return fixture_ids


def test_wc_fixture_uniqueness_and_no_orphans() -> None:
    """World Cup: fixture IDs unique across group+bracket; played store maps."""
    fixture_ids = _wc_fixture_ids()
    assert len(fixture_ids) >= _WC_MIN_FIXTURES
    duplicates = _duplicates_in(fixture_ids)
    assert duplicates == [], f"Duplicate World Cup fixture IDs: {duplicates}"
    id_set = set(fixture_ids)

    wc_data = ROOT / "competitions" / "worldcup" / "data"
    for basename in ("played_groups.json", "played.json"):
        path = wc_data / basename
        if not path.exists():
            # gitignored runtime store absent on a fresh checkout: the
            # zero-played state has no orphans to check.
            pytest.skip(f"{basename} absent (fresh checkout)")
        played = json.loads(path.read_text(encoding="utf-8"))
        orphans = [match_id for match_id in played if match_id not in id_set]
        assert orphans == [], f"Orphan played matches in {basename}: {orphans}"


def test_ucl_fixture_uniqueness_and_no_orphans() -> None:
    """UCL: unique Swiss-phase fixture IDs; results map to known fixtures."""
    ucl_data = ROOT / "competitions" / "ucl" / "data"
    fixtures = json.loads(
        (ucl_data / "fixtures.json").read_text(encoding="utf-8")
    )

    mids: list[str] = []
    if isinstance(fixtures, dict):
        schedule = fixtures.get("schedule", {})
        matchdays = schedule.get("matchdays", []) if isinstance(schedule, dict) else []
        for matchday in matchdays:
            if isinstance(matchday, list):
                entries = matchday
            elif isinstance(matchday, dict):
                entries = matchday.get("matches", [])
            else:
                entries = []
            for match in entries:
                if not isinstance(match, dict):
                    continue
                mid = match.get("match_id") or match.get("id")
                if mid:
                    mids.append(mid)
        for stage in ("playoffs", "knockout"):
            for match in fixtures.get(stage, []):
                if not isinstance(match, dict):
                    continue
                mid = match.get("match_id") or match.get("id")
                if mid:
                    mids.append(mid)

    assert len(mids) >= _UCL_MIN_FIXTURES, "No UCL fixtures extracted"
    duplicates = _duplicates_in(mids)
    assert duplicates == [], f"Duplicate UCL fixture IDs: {duplicates}"
    id_set = set(mids)

    results_file = ucl_data / "results.json"
    if not results_file.exists():
        pytest.skip("ucl results.json absent (gitignored runtime store)")
    results = json.loads(results_file.read_text(encoding="utf-8"))
    orphans = []
    for played in results.get("matches", []):
        if not isinstance(played, dict):
            continue
        rmid = played.get("match_id") or played.get("id")
        if rmid and rmid not in id_set:
            orphans.append(rmid)
    assert orphans == [], f"Orphan UCL played results: {orphans}"


def test_laliga_fixture_uniqueness_and_no_orphans() -> None:
    """LaLiga: every season's fixtures unique; results map to fixtures."""
    seasons_root = ROOT / "competitions" / "laliga" / "data" / "seasons"
    season_dirs = sorted(
        d for d in seasons_root.iterdir() if d.is_dir()
    ) if seasons_root.exists() else []
    assert season_dirs, "LaLiga seasons directory missing entirely"

    audited_seasons = 0
    for season_dir in season_dirs:
        fix_file = season_dir / "fixtures.json"
        if not fix_file.exists():
            continue
        fix_data = json.loads(fix_file.read_text(encoding="utf-8"))
        matches: list = (
            fix_data.get("fixtures", []) if isinstance(fix_data, dict) else fix_data
        )
        mids = [
            match["match_id"]
            for match in matches
            if isinstance(match, dict) and "match_id" in match
        ]
        assert len(mids) >= _LALIGA_MIN_FIXTURES, (
            f"No fixtures extracted for LaLiga season {season_dir.name}"
        )
        duplicates = _duplicates_in(mids)
        assert duplicates == [], (
            f"Duplicate LaLiga fixture IDs in {season_dir.name}: {duplicates}"
        )
        audited_seasons += 1
        id_set = set(mids)

        results_file = season_dir / "results.json"
        if results_file.exists():
            results = json.loads(results_file.read_text(encoding="utf-8"))
            result_matches: list = (
                results.get("matches", []) if isinstance(results, dict) else results
            )
            orphans = []
            for played in result_matches:
                if not isinstance(played, dict):
                    continue
                rmid = played.get("match_id") or played.get("id")
                if rmid and rmid not in id_set:
                    orphans.append(rmid)
            assert orphans == [], (
                f"Orphan LaLiga results in {season_dir.name}: {orphans}"
            )

    assert audited_seasons >= 1, "No LaLiga season was audited"


def test_gate_duplicate_detector_flags_synthetic_collisions() -> None:
    """Non-vacuity: the duplicate detector must flag synthetic collisions."""
    assert _duplicates_in(["a", "b", "a", "c", "b"]) == ["a", "b"]
    assert _duplicates_in(["unique", "ids"]) == []


# ---------------------------------------------------------------------------
# Section J invariant 8: simulation run provenance (SIM-02)
# ---------------------------------------------------------------------------


def test_simulation_run_provenance() -> None:
    """SIM-02: sim responses carry non-null seed/n_simulations/provenance."""
    from football_core.domain import ResultProvenance
    from football_core.simulation import MonteCarloEngine, SimulationRequest, ValueCounter

    class _OneLaneRules:
        """Minimal SimulationRules: single ValueCounter lane over a fixed pick."""

        def declare_aggregations(self):
            return {"c": lambda: ValueCounter("c")}

        def simulate_one(self, context):
            return {"c": "win"}

        def provenance_attestation(self):
            return {}

    request = SimulationRequest(
        competition_id="quality-gate",
        season="2026_27",
        n_simulations=10,
        seed=123,
    )
    result = MonteCarloEngine().run(request, _OneLaneRules())

    assert result.metadata.n_simulations == 10
    assert result.metadata.seed == 123
    assert result.metadata.provenance == "simulated"
    # The canonical vocabulary agrees with the string form.
    assert ResultProvenance.SIMULATED.value == "simulated"
    # The run is non-vacuous: rules actually produced aggregate output.
    assert result.aggregates["c"]["counts"] == {"win": 10}
    assert result.aggregates["c"]["n"] == 10


# ---------------------------------------------------------------------------
# Section J invariant 7: standings simulation invariance (FMT-04)
# ---------------------------------------------------------------------------

_FMT04_CONTRACT_METHODS: tuple[str, ...] = (
    "test_wc_simulation_standings_invariance",
    "test_ucl_simulation_standings_invariance",
    "test_laliga_simulation_standings_invariance",
)


def _assert_invariance_contract(contract_class: type) -> None:
    """Pin the FMT-04 contract suite's presence and fixture wiring.

    The Phase 06 invariance tests are fixture-wired real contract tests
    (monkeypatch + tmp_path; they run in every full suite pass). This gate
    enforces that the contract suite keeps covering all three competitions —
    deleting or renaming a method, or stripping its fixtures so it stops
    being a real test, fails this gate.
    """
    for name in _FMT04_CONTRACT_METHODS:
        method = getattr(contract_class, name, None)
        assert method is not None, f"FMT-04 contract method missing: {name}"
        assert callable(method), f"FMT-04 contract method not callable: {name}"
        params = inspect.signature(method).parameters
        assert "monkeypatch" in params, (
            f"{name} must be fixture-wired (monkeypatch) to be a real contract"
        )
        assert "tmp_path" in params, (
            f"{name} must be fixture-wired (tmp_path) to be a real contract"
        )


def _load_invariance_contract_class() -> type:
    """Load the Phase 06 FMT-04 contract class by module file path.

    Importing via ``tests.<module>`` is unreliable under pytest rootdir
    path modes, so the contract module is loaded directly from its
    resolved location — same mechanics the verifier of this repo uses.
    """
    import importlib.util

    contract_path = ROOT / "tests" / "test_standings_simulation_invariance.py"
    spec = importlib.util.spec_from_file_location(
        "test_standings_simulation_invariance", contract_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    contract_class = getattr(module, "TestStandingsSimulationInvariance", None)
    assert contract_class is not None, (
        "TestStandingsSimulationInvariance missing from contract module"
    )
    return contract_class


def test_standings_simulation_invariance_contract() -> None:
    _assert_invariance_contract(_load_invariance_contract_class())


def test_gate_invariance_contract_rejects_stub_class() -> None:
    """Non-vacuity: a stubbed/unwired class fails the contract gate."""
    class _Stub:
        test_wc_simulation_standings_invariance = lambda self: None  # noqa: E731
        test_ucl_simulation_standings_invariance = lambda self: None
        test_laliga_simulation_standings_invariance = lambda self: None

    with pytest.raises(AssertionError):
        _assert_invariance_contract(_Stub)


# ---------------------------------------------------------------------------
# Section J invariant 9: secret hygiene (zero committed API keys)
# ---------------------------------------------------------------------------

_SECRET_KEY_PATTERN = re.compile(
    r"(BSD_API_KEY|FOOTBALL_DATA_ORG_KEY|THE_ODDS_API_KEY)"
    r"\s*[\"']?\s*[=:]\s*[\"']([A-Za-z0-9\-_]{16,})[\"']"
)

# Loose floors: the tracked-universe scan must never pass vacuously just
# because git enumeration returned nothing (291 py / 191 json today).
_MIN_TRACKED_PY = 200
_MIN_TRACKED_JSON = 100


def _tracked_source_files() -> list[str]:
    """Tracked ``*.py``/``*.json`` paths tracked by git in this repo."""
    proc = subprocess.run(
        ["git", "ls-files", "--", "*.py", "*.json"],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=True,
    )
    return sorted(line for line in proc.stdout.splitlines() if line.strip())


def _find_committed_keys(content: str) -> list[str]:
    """Return the env-names whose quoted literal value looks like a key."""
    return [match.group(1) for match in _SECRET_KEY_PATTERN.finditer(content)]


def test_zero_committed_api_keys() -> None:
    """No committed BSD / football-data.org / Odds API credentials."""
    tracked = _tracked_source_files()
    py_files = [rel for rel in tracked if rel.endswith(".py")]
    json_files = [rel for rel in tracked if rel.endswith(".json")]
    assert len(py_files) >= _MIN_TRACKED_PY, (
        f"Tracked python universe floor failed: {len(py_files)}"
    )
    assert len(json_files) >= _MIN_TRACKED_JSON, (
        f"Tracked json universe floor failed: {len(json_files)}"
    )

    offenders: list[str] = []
    for rel in tracked:
        path = ROOT / rel
        content = path.read_text(encoding="utf-8", errors="ignore")
        if _find_committed_keys(content):
            offenders.append(rel)
    assert offenders == [], f"Committed API keys found in: {offenders}"


def test_gate_secret_scanner_flags_synthetic_keys() -> None:
    """Non-vacuity: the secret scanner must flag synthetic key literals.

    Positive samples are assembled from concatenated fragments so this
    tracked source file never itself contains a matching literal.
    """
    # env-style single-quote name + double-quoted value.
    committed_key = "BSD_API" + '_KEY = "aBcDeFgH1234567890Zx"'
    assert _find_committed_keys(committed_key) == ["BSD_API_KEY"]

    # JSON-style: quoted name, colon, quoted value.
    json_style = (
        '{"FOOTBALL_DATA' + '_ORG_KEY": "1234567890abcdefgh"}'
    )
    assert _find_committed_keys(json_style) == ["FOOTBALL_DATA_ORG_KEY"]

    # Single-quoted name, colon, rounded single-quoted value (YAML-like).
    colons_kv = "THE_ODDS_API" + "_KEY: 'ZxWvUtSrQpOnMlKj-98'"
    assert _find_committed_keys(colons_kv) == ["THE_ODDS_API_KEY"]

    # Negative controls: env reads and short/dashed values are not keys.
    env_read = 'os.environ.get("BSD_API_KEY", "")'
    assert _find_committed_keys(env_read) == []
    short_value = "BSD_API_KEY = \"short\""
    assert _find_committed_keys(short_value) == []
    empty_env = 'THE_ODDS_API_KEY = ""'
    assert _find_committed_keys(empty_env) == []
