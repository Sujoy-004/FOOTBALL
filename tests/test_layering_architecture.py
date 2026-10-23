"""AST-based layering enforcement for both forbidden dependency directions.

Plan 01-07 makes the layering rule executable (LAYR-02). The rule, as written
in ``01-07-PLAN.md``::

    football_core/            may import: stdlib, numpy, itself
    competitions/<name>/src/  may import: stdlib, numpy, football_core, itself
    web/                      may import: all of the above
    tests/                    unconstrained

Two directions are forbidden: **kernel upward** (``football_core`` importing a
competition or the web layer) and **brain upward** (a competition brain's
``src/`` importing ``web``). Phase 01 removed nine instances of the second kind
by hand; this file is what stops the tenth.

Why AST rather than grep: a text scan misses multi-line and aliased imports and
``importlib.import_module("web.wc_app")``, and it false-positives on the word
``web`` inside a docstring or a URL. Only ``ast.Import`` and ``ast.ImportFrom``
nodes are inspected.

Scoping (decided from the plan's rule table and ``01-01-import-manifest.json``):

* The kernel scan covers ``football_core/**/*.py`` **minus test modules**. The
  plan's rule table makes ``tests/`` unconstrained, and
  ``tests/test_atomic_store_writes.py`` already excludes test modules that sit
  inside the audited roots with the same predicate — ``football_core/tests/``
  lives inside the kernel tree by accident of layout and legitimately imports
  ``competitions.laliga.src``.
* The brain scan covers ``competitions/*/src/**/*.py``, which is the manifest's
  own scope string (``"competitions/*/src/**/*.py"``). ``competitions/ucl/main.py``
  is a CLI entry point outside ``src/`` and is out of scope, exactly as
  ``01-01-BASELINE.md`` records under "Not in scope".
* Test modules are recognised structurally (a ``tests/`` path component or a
  ``test_*`` file name), never by a per-file skip list.

D-06: there is **no** allowlist here. Cases 1 and 2 carry zero exemptions; a
name added to a skip list to reach green is precisely the failure mode D-06
exists to prevent. The single exact-match expectation in this file is the D-14
suppression ratchet in case 3 — the two intra-brain ``src.engine`` lazy imports
plan 01-06 recorded as staying — and it governs the *count* of ``noqa: PLC0415``
comments, not an exemption from the import scan.

Non-vacuity (D-09)
------------------

A guard that has never been observed failing is a guard of unknown value, so
this file was run against reproduced pre-move violations before it shipped.
Both injections were added, observed to fail, and removed byte-wise; neither
was ever committed, and ``git diff`` on the injected file came back empty:

* ``from web.wc_app import compute_full_bracket`` re-inserted at module scope
  in ``competitions/worldcup/src/pipeline.py`` — cases 2 and 4 fail and name
  ``pipeline.py:14`` (4 passed);
* ``from web.common import ts`` re-inserted at module scope in
  ``competitions/ucl/src/orchestrator.py`` — cases 2 and 4 fail and name
  ``orchestrator.py:12`` (run with ``-k "brain or baseline"``: 2 failed,
  case 5 passed — an import it never touches — 3 deselected).

To reproduce either one: add the line, run
``python -m pytest tests/test_layering_architecture.py``, delete the line
again. Case 1 (kernel upward) deliberately does not fire on either injection —
both land in a brain, which is why case 2 exists.

Phase 5 (RECON-02) additions
----------------------------

Three injections were added, observed to fail, and removed byte-wise; none was
ever committed:

1. ``from web.reconciliation import reconcile_now`` in
   ``competitions/worldcup/src/pipeline.py`` -> assertion (A) and (B) fire.
2. ``on_store_written: Callable[[dict], None] = None`` added to a brain's
   ``fetch_live_data`` signature -> assertion (C) fires.
3. ``hook: Callable = None`` added to ``IngestReport`` -> assertion (D) fires.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
import pathlib
import re
import socket

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BASELINE = (
    ROOT
    / ".planning"
    / "phases"
    / "01-layering-inversion-deprecated-path-removal"
    / "01-01-BASELINE.md"
)

KERNEL_ROOTS = ("competitions", "web")
BRAIN_ROOTS = ("web",)

# Case 6's floor. Measured 2026-10-06: 34 kernel modules + 52 brain modules =
# 86 audited files. 40 leaves headroom so a future file removal does not fail
# the guard while still catching a glob that silently returns nothing.
MIN_AUDITED_FILES = 40

# D-14: exactly two PLC0415 suppressions survive in the source trees, both on
# the intra-brain `from src.engine import build_engine_from_caches` lazy
# imports in the World Cup pipeline. Exact-match ratchet (D-26 shape): a third
# suppression, a second file, or the removal of either entry all fail and force
# a decision, instead of drifting silently.
SUPPRESSION_RATCHET: dict[str, int] = {"competitions/worldcup/src/pipeline.py": 2}

BASELINE_HEADING = "## BRAIN -> WEB IMPORTS"
BASELINE_ENTRY_COUNT = 9
BASELINE_ENTRY_RE = re.compile(
    r"^[ \t]*(competitions/[^:\s]+\.py):(\d+)[ \t]+((?:from|import)\s+[^\s#].*)$",
    re.MULTILINE,
)

# Case 5 lists modules explicitly rather than globbing: a blanket import of
# every module would execute side effects nobody intends.
NO_NETWORK_MODULES = (
    "football_core",
    "football_core.seasons",
    "football_core.runtime_support",
    "football_core.simulation",
    "football_core.signal",
    "competitions.worldcup.src.pipeline",
    "competitions.ucl.src.pipeline",
    "competitions.laliga.src.pipeline",
    "football_core.reconcile",
)

#: Public names of the web-layer invalidation owner (Phase 5). A competition
#: brain must never reach for one of these: the brain REPORTS what changed
#: as data on its IngestReport, and the web layer decides (C-01, C-06).
FORBIDDEN_RECONCILER_SYMBOLS = frozenset({
    "reconcile_now",
    "reconcile_if_needed",
    "reconciliation_block",
    "reconcile",
    "retire_matching",
    "retire_whole_snapshot",
    "publish_sim_state",
    "clear_sim",
    "invalidate",
    "retire",
})


def _rel(path: pathlib.Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _is_test_module(path: pathlib.Path) -> bool:
    """The test layer is unconstrained, wherever it sits in the tree."""
    parts = path.relative_to(ROOT).parts
    return "tests" in parts or path.name.startswith("test_")


def _kernel_files() -> list[pathlib.Path]:
    """Every production module under ``football_core/``."""
    return sorted(
        p
        for p in (ROOT / "football_core").rglob("*.py")
        if "__pycache__" not in p.parts and not _is_test_module(p)
    )


def _brain_files() -> list[pathlib.Path]:
    """Every production module under each competition's ``src/`` package."""
    out: list[pathlib.Path] = []
    for pkg in sorted((ROOT / "competitions").glob("*/src")):
        out.extend(
            p
            for p in pkg.rglob("*.py")
            if "__pycache__" not in p.parts and not _is_test_module(p)
        )
    return sorted(out)


def _source_files() -> list[pathlib.Path]:
    """Every non-test module in the three source trees (case 3's repo-wide scan)."""
    out: list[pathlib.Path] = []
    for name in ("football_core", "competitions", "web"):
        base = ROOT / name
        if base.is_dir():
            out.extend(
                p
                for p in base.rglob("*.py")
                if "__pycache__" not in p.parts and not _is_test_module(p)
            )
    return sorted(out)


def _imported_modules(
    path: pathlib.Path,
) -> list[tuple[int, str, tuple[str, ...], str]]:
    """``(lineno, resolved module, imported names, source line)`` for every import.

    A relative ``ImportFrom`` is flattened with ``("." * level + module).lstrip(".")``,
    so ``from ..web import x`` resolves to ``web`` and is flagged like the absolute
    form; ``from . import web`` carries an empty module and is caught through the
    imported-name check instead.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines()
    found: list[tuple[int, str, tuple[str, ...], str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = ("." * node.level + (node.module or "")).lstrip(".")
            names = tuple(alias.name for alias in node.names)
            src = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            found.append((node.lineno, mod, names, src))
        elif isinstance(node, ast.Import):
            src = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            for alias in node.names:
                found.append((node.lineno, alias.name, (alias.name,), src))
    return found


def _named_symbols(path: pathlib.Path) -> list[tuple[int, str, str]]:
    """``(lineno, symbol, source line)`` for every identifier a module NAMES.

    Walks ``ast.Name`` (load context) and ``ast.Attribute`` (the attribute
    part), so a brain that reaches for the owner through either
    ``reconcile_now(...)`` or ``owner.reconcile_now(...)`` is caught.
    """
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    lines = text.splitlines()
    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            src = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            found.append((node.lineno, node.id, src))
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            src = lines[node.lineno - 1].strip() if node.lineno <= len(lines) else ""
            found.append((node.lineno, node.attr, src))
    return found


def _matches(mod: str, roots: tuple[str, ...]) -> bool:
    """Prefix match on a segment boundary, so stdlib ``webbrowser`` never trips."""
    return any(mod == root or mod.startswith(root + ".") for root in roots)


def _forbidden_imports(
    paths: list[pathlib.Path], roots: tuple[str, ...]
) -> list[str]:
    """``path:lineno  <source line>`` for every import reaching into ``roots``."""
    violations: list[str] = []
    for path in paths:
        for lineno, mod, names, src in _imported_modules(path):
            if _matches(mod, roots) or any(_matches(n, roots) for n in names):
                violations.append(f"{_rel(path)}:{lineno}  {src}")
    return sorted(violations)


def _split_statement(stmt: str) -> tuple[str, tuple[str, ...]]:
    """``(module, imported names)`` for a one-line import statement."""
    stmt = stmt.split("#", 1)[0].strip()
    words = stmt.split()
    if not words:
        return "", ()
    if words[0] == "from":
        module = words[1] if len(words) > 1 else ""
        names: tuple[str, ...] = ()
        if "import" in words:
            tail = " ".join(words[words.index("import") + 1 :])
            names = tuple(n.strip() for n in tail.split(",") if n.strip())
        return module, names
    first = words[1] if len(words) > 1 else ""
    return first.split(",")[0].strip(), tuple(
        part.strip().split(" ")[0] for part in first.split(",") if part.strip()
    )


def _parse_baseline() -> list[tuple[str, int, str, tuple[str, ...]]]:
    """The nine recorded brain -> web imports as ``(file, lineno, module, names)``.

    Raises (caught by the caller) when the planning artifact is missing, moved
    or reshaped, so a deleted baseline degrades the test instead of failing a
    runtime architecture assertion on a file nobody owns.
    """
    text = BASELINE.read_text(encoding="utf-8")
    start = text.find(BASELINE_HEADING)
    if start < 0:
        raise ValueError(f"{BASELINE_HEADING!r} heading not found in {BASELINE}")
    end = text.find("\n## ", start)
    section = text[start:] if end < 0 else text[start:end]
    entries: list[tuple[str, int, str, tuple[str, ...]]] = []
    for match in BASELINE_ENTRY_RE.finditer(section):
        module, names = _split_statement(match.group(3))
        entries.append((match.group(1), int(match.group(2)), module, names))
    return entries


def test_audit_covers_the_trees() -> None:
    """Case 6 — the self-check that protects cases 1-4 from passing vacuously.

    A layering test whose glob returns nothing passes forever while enforcing
    nothing, so this runs first.
    """
    files = _kernel_files() + _brain_files()
    assert len(files) > MIN_AUDITED_FILES, (
        f"audit only discovered {len(files)} modules (expected > {MIN_AUDITED_FILES}, "
        "measured 86 on 2026-10-06) -- the glob is broken and cases 1-4 would pass "
        "without checking anything"
    )


def test_kernel_never_imports_competitions_or_web() -> None:
    """Case 1 — kernel upward: the reusable kernel depends on nothing above it."""
    violations = _forbidden_imports(_kernel_files(), KERNEL_ROOTS)
    assert not violations, (
        "football_core must import only the stdlib, numpy and itself; "
        "forbidden kernel-upward imports found:\n" + "\n".join(violations)
    )


def test_competition_brains_never_import_web() -> None:
    """Case 2 — brain upward: tournament rules never depend on HTTP transport."""
    violations = _forbidden_imports(_brain_files(), BRAIN_ROOTS)
    # A relative import can only reach a package that exists inside competitions/,
    # so asserting no `web` module lives there settles `from ..web import x`.
    violations.extend(
        f"{_rel(stray)}  a module named 'web' inside competitions/"
        for stray in (ROOT / "competitions").rglob("web")
    )
    assert not violations, (
        "a competition brain's src/ must not import web; "
        "brain-upward imports found:\n" + "\n".join(sorted(violations))
    )


def test_plc0415_suppressions_are_ratcheted() -> None:
    """Case 3 — no suppression may ride a cross-layer import, and the count is pinned.

    The ban is on suppressing the lazy-import warning *for a forbidden import*.
    Two intra-brain ``src.engine`` lazy imports stay per D-14 (they cross no
    layer), so the count is an exact-match ratchet rather than zero: growth,
    shrinkage and file moves all fail.
    """
    hits: list[str] = []
    cross_layer: list[str] = []
    for path in _source_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "noqa: PLC0415" not in line:
                continue
            hits.append(f"{_rel(path)}:{lineno}")
            code = line.split("#", 1)[0]
            if re.search(r"\bfrom[ \t]+web\b|\bimport[ \t]+web\b", code):
                cross_layer.append(f"{_rel(path)}:{lineno}  {line.strip()}")
    assert not cross_layer, (
        "noqa: PLC0415 may only ride an intra-brain import; "
        "cross-layer suppressions found:\n" + "\n".join(sorted(cross_layer))
    )

    discovered: dict[str, int] = {}
    for hit in hits:
        file = hit.rsplit(":", 1)[0]
        discovered[file] = discovered.get(file, 0) + 1
    assert discovered == SUPPRESSION_RATCHET, (
        f"noqa: PLC0415 ratchet broken (D-14 expects exactly {SUPPRESSION_RATCHET}); "
        f"discovered {discovered} at {sorted(hits)}. "
        "Changing this set is a decision, not a fix."
    )


def test_baseline_manifest_entries_are_gone() -> None:
    """Case 4 — each of the nine recorded violations is absent, by name.

    The manifest is parsed rather than copied: a second copy of the list in this
    file would drift. When the planning artifact cannot be read the test degrades
    to asserting zero violations, so a missing baseline never fails a runtime
    architecture test.
    """
    try:
        entries = _parse_baseline()
    except (OSError, ValueError) as exc:
        violations = _forbidden_imports(_kernel_files(), KERNEL_ROOTS) + (
            _forbidden_imports(_brain_files(), BRAIN_ROOTS)
        )
        assert not violations, (
            f"{BASELINE} is unreadable ({exc}); falling back to a zero-violation "
            "assertion, which still found:\n" + "\n".join(sorted(violations))
        )
        return

    assert len(entries) == BASELINE_ENTRY_COUNT, (
        f"{BASELINE} must record exactly {BASELINE_ENTRY_COUNT} brain->web imports, "
        f"parsed {len(entries)}: {entries}"
    )
    for _file, _lineno, module, _names in entries:
        assert _matches(module, BRAIN_ROOTS), (
            f"baseline entry is not a web import, manifest reshaped: {module!r}"
        )

    symbols = {name for _f, _l, _m, names in entries for name in names}
    violations = []
    for path in _brain_files():
        for lineno, mod, names, src in _imported_modules(path):
            if _matches(mod, BRAIN_ROOTS) and symbols.intersection(names):
                violations.append(f"{_rel(path)}:{lineno}  {src}")
    assert not violations, (
        "imports recorded in the 01-01 baseline are still present in a brain:\n"
        + "\n".join(sorted(violations))
    )


def test_kernel_and_brains_import_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Case 5 — importing a module must not grant network capability.

    Credentials are read at call time, so no provider environment variable is
    set here: importing with no keys present has to work.
    """

    def _blocked(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("network access at import time")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    for name in NO_NETWORK_MODULES:
        importlib.import_module(name)


def test_brains_never_name_a_reconciler_symbol() -> None:
    """Assertion B (Phase 5, C-06): brains report data only, never name reconciler symbols."""
    violations: list[str] = []
    for path in _brain_files():
        for lineno, sym, src in _named_symbols(path):
            if sym in FORBIDDEN_RECONCILER_SYMBOLS:
                violations.append(f"{_rel(path)}:{lineno}  {src}")
    assert not violations, (
        "competitions/*/src must never name a reconciler symbol; "
        "violations found:\n" + "\n".join(sorted(violations))
    )


def test_fetch_live_data_has_no_hook_parameter() -> None:
    """Assertion C (Phase 5, C-01): fetch_live_data has no hook/callback parameter."""
    brain_modules = (
        "competitions.worldcup.src.pipeline",
        "competitions.ucl.src.pipeline",
        "competitions.laliga.src.pipeline",
    )
    for mod_name in brain_modules:
        mod = importlib.import_module(mod_name)
        if hasattr(mod, "fetch_live_data"):
            sig = inspect.signature(mod.fetch_live_data)
            for param in sig.parameters.values():
                name_lower = param.name.lower()
                is_hook = (
                    name_lower.startswith("on_")
                    or "hook" in name_lower
                    or "callback" in name_lower
                    or "invalidate" in name_lower
                )
                assert not is_hook, (
                    f"forbidden hook parameter in {mod_name}.fetch_live_data: {param.name}"
                )
                ann_str = str(param.annotation)
                assert "Callable" not in ann_str, (
                    f"forbidden Callable annotation in {mod_name}.fetch_live_data: {param.name}"
                )


def test_ingest_report_has_no_callable_field() -> None:
    """Assertion D (Phase 5, D-05): IngestReport has no Callable-typed field."""
    from football_core.fetcher import IngestReport

    for f in dataclasses.fields(IngestReport):
        ann = str(f.type)
        assert "Callable" not in ann and "callable" not in ann, (
            f"IngestReport field {f.name} has callable type annotation: {ann}"
        )


def test_ingest_report_carries_the_changed_channel() -> None:
    """Assertion E (Phase 5, D-05/D-06): IngestReport has changed and changed_match_ids."""
    from football_core.fetcher import IngestReport

    field_names = {f.name for f in dataclasses.fields(IngestReport)}
    assert "changed" in field_names
    assert "changed_match_ids" in field_names

    d = IngestReport(provider=None, attempted=False, success=False, error=None).to_dict()
    assert "changed" in d
    assert "changed_match_ids" in d


def test_reconcile_kernel_is_importable_and_network_free() -> None:
    """Assertion F (Phase 5, C-02): football_core.reconcile is network-free and imports no web/competitions."""
    assert "football_core.reconcile" in NO_NETWORK_MODULES
    mod = importlib.import_module("football_core.reconcile")
    path = pathlib.Path(mod.__file__)
    for _lineno, m, _names, _src in _imported_modules(path):
        assert not _matches(m, KERNEL_ROOTS), f"reconcile imports forbidden module: {m}"
