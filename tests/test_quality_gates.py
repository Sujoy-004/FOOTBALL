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
import pathlib

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
