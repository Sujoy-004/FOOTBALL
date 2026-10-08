"""Ratchet: no module under the audited trees may write a store file non-atomically.

Phase 01 roadmap criterion 4 ("one atomic writer"; `PHASE1-C4` in the plan's
frontmatter). It is not a `REQUIREMENTS.md` id -- that file carries LAYR-01
through LAYR-03 only.

D-25 fixes the audit scope: ``football_core/``, ``web/``, ``competitions/*/src/``
and ``competitions/*/data/``. ``web/`` is in scope because ``snapshot.json`` is
written by three web writers and ``web/last_refresh.json`` has four lock-less
read-modify-write sites across three modules (worldcup pipeline x2, ucl_app,
laliga_app) whose single-writer fix belongs to Phase 2.

D-26 fixes the expectation, and it is deliberately **not** "all green": the
``write_text`` call sites are not all converted in this phase. This test is a
**ratchet**, not a blanket ban:

* the known-deferred offenders are enumerated in
  ``tests/fixtures/deferred_non_atomic_writes.json``;
* the discovered offender set must be **exactly** that list, so a NEW
  non-atomic write fails the test, and so does one that has been FIXED --
  which is the signal telling Phase 2 to update the list;
* the list is printed by ``path:lineno`` on every run, so Phase 2 inherits a
  ready-made worklist rather than re-deriving one from memory.

An empty allowlist is not achievable (D-26) and an unbounded one rots. An
exact-match ratchet is the only shape that satisfies both.

``football_core/state.py`` is exempt as a whole file -- it holds the sanctioned
implementation, which writes through a file descriptor from
``tempfile.mkstemp`` and so cannot be expressed as an ``open()``/``write_text``
call at all. Exempting a whole file rather than line numbers means a future
edit inside it is still checked by
``test_atomic_write_implementation_is_unique_and_delegating``, which asserts
the real invariants: one definition, ``os.replace`` in the body, and a JSON
writer that delegates instead of writing.
"""

from __future__ import annotations

import ast
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFERRED_FIXTURE = ROOT / "tests" / "fixtures" / "deferred_non_atomic_writes.json"

#: The one sanctioned implementation (D-25/D-26 exemption, whole file).
SANCTIONED_SOURCE = "football_core/state.py"

#: Modes that can mutate a file. ``r+``/``x`` included: they open for update or
#: exclusive creation, both of which truncate or create content in place.
WRITE_MODES = {"w", "a", "wb", "ab", "w+", "a+", "r+", "x", "xb", "x+"}

#: Sentinel for a mode argument that is not a literal string. A dynamic mode
#: cannot be statically proven safe, and this codebase's explicit-semantics
#: rule requires a store write to state its mode, so it is flagged.
DYNAMIC_MODE = "<dynamic>"

_PATH_WRITE_ATTRS = {"write_text", "write_bytes"}


# ── audit scope ──────────────────────────────────────────────────────────────


def _audit_roots() -> list[pathlib.Path]:
    """The D-25 audit roots, globbed so a new competition is covered free."""
    roots = [ROOT / "football_core", ROOT / "web"]
    competitions = ROOT / "competitions"
    roots += sorted(competitions.glob("*/src"))
    roots += sorted(competitions.glob("*/data"))
    return [r for r in roots if r.is_dir()]


def _is_test_module(path: pathlib.Path) -> bool:
    """True for pytest modules, which write scratch fixtures, not stores.

    D-25's root list already excludes the repository's main ``tests/`` tree,
    and it carries ~55 legitimate ``write_text``/``open(...,"w")`` calls that
    write ``tmp_path`` fixtures. ``football_core/tests`` and
    ``competitions/*/tests`` sit *inside* the audited roots by accident of
    layout, so they are filtered out explicitly: a pytest fixture has no reader
    to protect and no durability requirement, and listing one in the deferred
    worklist would be an entry case 2 could not honestly describe.
    """
    return "tests" in path.parts or path.name.startswith("test_")


def _audited_files() -> list[pathlib.Path]:
    """Every non-test Python file under the D-25 roots."""
    files: list[pathlib.Path] = []
    for root in _audit_roots():
        files.extend(
            p
            for p in root.rglob("*.py")
            if "__pycache__" not in p.parts and not _is_test_module(p)
        )
    return sorted(set(files))


def _definition_scope_files() -> list[pathlib.Path]:
    """Every non-test Python file in the product packages.

    Deliberately wider than the D-25 audit set: "exactly one implementation"
    is a repo-wide claim, so it also covers CLI entry points such as
    ``competitions/*/main.py`` that sit outside ``src/``.
    """
    files: list[pathlib.Path] = []
    for package in ("football_core", "web", "competitions"):
        root = ROOT / package
        if not root.is_dir():
            continue
        for p in root.rglob("*.py"):
            if "__pycache__" in p.parts or _is_test_module(p):
                continue
            files.append(p)
    return sorted(set(files))


# ── detection ────────────────────────────────────────────────────────────────


def _rel(path: pathlib.Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _mode_of(call: ast.Call) -> str:
    """Resolve an ``open()`` mode, or :data:`DYNAMIC_MODE` if not a literal."""
    if len(call.args) >= 2:
        node: ast.expr = call.args[1]
    else:
        node = next((kw.value for kw in call.keywords if kw.arg == "mode"), None)
    if node is None:
        return "r"
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return DYNAMIC_MODE


def _violations_in(path: pathlib.Path, source: str) -> list[dict]:
    """Non-atomic write call sites in one file's source."""
    found: list[dict] = []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:  # pragma: no cover - a broken file fails the suite anyway
        return found

    class SymbolVisitor(ast.NodeVisitor):
        def __init__(self, path):
            self.path = path
            self.symbol_stack = ["<module>"]
            self.found = []

        def visit_FunctionDef(self, node: ast.FunctionDef):
            self.symbol_stack.append(node.name)
            self.generic_visit(node)
            self.symbol_stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
            self.symbol_stack.append(node.name)
            self.generic_visit(node)
            self.symbol_stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef):
            self.symbol_stack.append(node.name)
            self.generic_visit(node)
            self.symbol_stack.pop()

        def visit_Call(self, node: ast.Call):
            func = node.func
            reason: str | None = None
            if isinstance(func, ast.Name) and func.id == "open":
                mode = _mode_of(node)
                if mode in WRITE_MODES or mode == DYNAMIC_MODE:
                    reason = f"open(mode={mode})"
            elif isinstance(func, ast.Attribute):
                if func.attr in _PATH_WRITE_ATTRS:
                    reason = f"Path.{func.attr}"
                elif (
                    func.attr == "write"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    reason = "os.write"
            if reason is not None:
                self.found.append(
                    {
                        "path": _rel(self.path) if self.path.is_absolute() else self.path.as_posix(),
                        "line": node.lineno,
                        "symbol": self.symbol_stack[-1],
                        "reason": reason,
                    }
                )
            self.generic_visit(node)

    visitor = SymbolVisitor(path)
    visitor.visit(tree)
    found = visitor.found
    return found


def _all_violations() -> list[dict]:
    """Every non-atomic write call site in the audited trees."""
    found: list[dict] = []
    for path in _audited_files():
        if _rel(path) == SANCTIONED_SOURCE:
            continue
        found.extend(_violations_in(path, path.read_text(encoding="utf-8")))
    return found


def _deferred() -> list[dict]:
    return json.loads(DEFERRED_FIXTURE.read_text(encoding="utf-8"))


# ── the ratchet ──────────────────────────────────────────────────────────────


def test_write_ban_matches_deferred_list():
    """Case 1: discovered offender set == committed deferred list, exactly."""
    found = {f"{v['path']}::{v.get('symbol', '<module>')}" for v in _all_violations()}
    known = {f"{d['path']}::{d.get('symbol', '<module>')}" for d in _deferred()}
    print("\ndeferred non-atomic store writes (Phase 2 worklist):")
    for entry in _deferred():
        print(
            f"  {entry['path']}:{entry['line']}  "
            f"{entry.get('symbol', '?')}  -> {entry.get('owner', '?')}"
        )
    assert found == known, (
        "non-atomic write set changed.\n"
        f"NEW (must be fixed or added to the deferred list): "
        f"{sorted(found - known)}\n"
        f"FIXED (remove from the deferred list): {sorted(known - found)}"
    )


def test_deferred_list_is_not_empty():
    """Case 2: the list is real work, and every entry is actionable."""
    deferred = _deferred()
    assert deferred, (
        "deferred list is empty -- D-26 requires Phase 2 to inherit a real "
        "worklist, so the ratchet cannot be satisfied by deleting the file"
    )
    for entry in deferred:
        assert set(entry) >= {"path", "line", "symbol", "owner"}, (
            f"deferred entry missing required keys: {entry}"
        )
        assert entry["symbol"].strip(), f"deferred entry names no store: {entry}"
        assert entry["owner"].strip(), f"deferred entry names no owner: {entry}"


def test_audit_covers_the_documented_scope():
    """Case 3: all four D-25 roots, discovered by glob."""
    roots = {_rel(r) for r in _audit_roots()}
    assert {"football_core", "web"} <= roots, f"missing core roots: {roots}"
    competitions = ROOT / "competitions"
    for pattern in ("*/src", "*/data"):
        for candidate in competitions.glob(pattern):
            if candidate.is_dir():
                assert _rel(candidate) in roots, f"{candidate} not audited"
    assert any(
        _rel(f).startswith("competitions/") and "/src/" in _rel(f)
        for f in _audited_files()
    ), "no competition brain file is audited -- the glob is broken"


def test_audit_discovers_enough_files_to_be_non_vacuous():
    """Case 4: a broken glob cannot make cases 1-3 pass by finding nothing."""
    discovered = len(_audited_files())
    assert discovered > 40, (
        f"glob is broken -- only {discovered} files audited, "
        "so the ratchet would pass vacuously"
    )


def test_atomic_write_implementation_is_unique_and_delegating():
    """Case 5: one sanctioned writer, containing os.replace, delegating for JSON."""
    files = _definition_scope_files()
    text_defs: list[tuple[str, ast.FunctionDef]] = []
    json_defs: list[tuple[str, ast.FunctionDef]] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, ast.FunctionDef):
                if node.name == "atomic_write_text":
                    text_defs.append((_rel(path), node))
                elif node.name == "_atomic_write_json":
                    json_defs.append((_rel(path), node))

    assert len(text_defs) == 1, (
        f"expected exactly one atomic_write_text definition, got "
        f"{[p for p, _ in text_defs]}"
    )
    text_path, text_def = text_defs[0]
    assert text_path == SANCTIONED_SOURCE, (
        f"atomic_write_text must live in {SANCTIONED_SOURCE}, found {text_path}"
    )
    replace_calls = [
        n
        for n in ast.walk(text_def)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "replace"
        and isinstance(n.func.value, ast.Name)
        and n.func.value.id == "os"
    ]
    assert replace_calls, (
        "atomic_write_text does not call os.replace -- a writer that truncates "
        "in place is not atomic"
    )

    assert len(json_defs) == 1, (
        f"expected exactly one _atomic_write_json definition, got "
        f"{[p for p, _ in json_defs]}"
    )
    json_path, json_def = json_defs[0]
    assert json_path == SANCTIONED_SOURCE, (
        f"_atomic_write_json must live in {SANCTIONED_SOURCE}, found {json_path}"
    )
    delegated = any(
        isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "atomic_write_text"
        for n in ast.walk(json_def)
    )
    assert delegated, "_atomic_write_json does not delegate to atomic_write_text"
    self_writes = _violations_in(
        ROOT / SANCTIONED_SOURCE,
        ast.unparse(json_def),
    )
    assert not self_writes, (
        f"_atomic_write_json writes a file itself instead of delegating: "
        f"{self_writes}"
    )


def test_detector_flags_an_injected_non_atomic_write():
    """Case 6: the detector actually fires on each banned construct."""
    source = (
        "from pathlib import Path\n"
        "import os\n"
        "def f(p, q):\n"
        "    p.write_text('x')\n"
        "    Path(q).write_bytes(b'x')\n"
        "    with open(q, 'w') as h:\n"
        "        pass\n"
        "    with open(q, 'a') as h:\n"
        "        pass\n"
        "    with open(q, mode='r+') as h:\n"
        "        pass\n"
        "    with open(q, some_mode) as h:\n"
        "        pass\n"
        "    os.write(1, b'x')\n"
        "    with open(q) as h:\n"
        "        return h.read()\n"
    )
    found = _violations_in(pathlib.Path("football_core/injected.py"), source)
    assert {v["line"] for v in found} == {4, 5, 6, 8, 10, 12, 14}, found
    assert all(v["path"] == "football_core/injected.py" for v in found)
