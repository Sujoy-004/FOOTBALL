"""HARD-02 (D-11) ratchet: no swallowed failure on the ingestion/freshness surface.

Roadmap criterion 5's "a swallowed failure is no longer invisible" clause.

Two defect classes are scanned with AST (never regex — a comment or a
multi-line body defeats a line pattern):

* ``except ...: pass`` — the bare swallow. A failure that leaves no log, no
  report field and no exception is invisible to ops *and* to the dashboard.
* ``except ...: return {}`` / ``return dict()`` inside a reader — the
  silent-empty swallow. ``{}`` is indistinguishable from "nothing has been
  recorded yet", so an unreadable ledger renders as "no refresh ever ran"
  instead of "this file could not be read".

Scope (D-11): ``competitions/*/src/pipeline.py``, the three web sub-apps that
serve or write the ledger, ``football_core/freshness.py`` (the ledger owner)
and ``football_core/fetcher.py``.

Every remaining default-shape ``return {}`` is sanctioned **by exact
``path::symbol``** with a one-line reason — mirroring the keying of
``test_atomic_store_writes.py`` — and the sanctioned set must match the
discovered set exactly, so a new swallow fails and a fixed one fails too
(remove the entry when you fix the site).

This is the RED counterpart of ``tests/test_hard03_staleness.py``: the four
freshness readers still swallow into ``{}`` and the UCL alias-registration
block in ``fetch_live_data`` still swallows with ``pass``.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: The D-11 scan surface.
SCAN_FILES: list[Path] = sorted(ROOT.glob("competitions/*/src/pipeline.py")) + [
    ROOT / "web" / "wc_app.py",
    ROOT / "web" / "ucl_app.py",
    ROOT / "web" / "laliga_app.py",
    ROOT / "football_core" / "freshness.py",
    ROOT / "football_core" / "fetcher.py",
]

#: Sanctioned default-shape readers: ``path::symbol`` -> why it is not a lie.
#: All of them return the SAME value their own "file is missing" branch
#: already returns, so the except arm cannot change what a caller sees.
SANCTIONED: dict[str, str] = {
    "football_core/freshness.py::_read_unlocked": (
        "missing file -> {} by contract; every real read/parse failure logs "
        "with logger.exception and returns the unreadable marker"
    ),
    "competitions/laliga/src/pipeline.py::load_config": (
        "optional config: corrupt == missing == the same {} default "
        "(narrow JSONDecodeError/OSError, freshness path untouched)"
    ),
    "competitions/laliga/src/pipeline.py::load_elo_ratings": (
        "optional Elo seed: corrupt == missing == the same {} default"
    ),
    "competitions/laliga/src/pipeline.py::_alias_lookup": (
        "optional alias file: corrupt == missing == the same {} default"
    ),
    "competitions/laliga/src/pipeline.py::compute_signal_eval": (
        "signal-eval stats block, not the ingestion/freshness path (D-11 "
        "scope): empty stats is the UI's existing no-data shape"
    ),
    "competitions/ucl/src/pipeline.py::compute_signal_eval": (
        "signal-eval stats block, not the ingestion/freshness path (D-11 "
        "scope): empty stats is the UI's existing no-data shape"
    ),
    "competitions/ucl/src/pipeline.py::build_matchday_map": (
        "optional fixtures file: corrupt == missing == the same {} default"
    ),
    "competitions/worldcup/src/pipeline.py::_wc_bracket_node_rounds": (
        "optional bracket file: corrupt == missing == the same {} default "
        "(OSError/ValueError only)"
    ),
}


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _is_swallow(handler: ast.ExceptHandler) -> str | None:
    """Return the swallow kind for this handler body, or ``None``."""
    body = handler.body
    if len(body) == 1 and isinstance(body[0], ast.Pass):
        return "pass"
    if len(body) == 1 and isinstance(body[0], ast.Return):
        value = body[0].value
        if isinstance(value, ast.Dict) and not value.keys:
            return "return {}"
        if (
            isinstance(value, ast.Call)
            and isinstance(value.func, ast.Name)
            and value.func.id == "dict"
            and not value.args
            and not value.keywords
        ):
            return "return dict()"
    return None


def swallows_in(path: Path, source: str) -> list[dict]:
    """Swallow sites in one file's source, keyed ``path::symbol``."""
    tree = ast.parse(source, filename=str(path))
    stack = ["<module>"]
    found: list[dict] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            stack.append(node.name)
            self.generic_visit(node)
            stack.pop()

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            kind = _is_swallow(node)
            if kind is not None:
                found.append(
                    {
                        "key": f"{_rel(path)}::{stack[-1]}",
                        "symbol": stack[-1],
                        "line": node.lineno,
                        "kind": kind,
                    }
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


def _all_swallow_sites() -> list[dict]:
    hits: list[dict] = []
    scanned = 0
    for path in SCAN_FILES:
        assert path.is_file(), f"scan surface file missing: {path}"
        scanned += 1
        hits.extend(swallows_in(path, path.read_text(encoding="utf-8")))
    assert scanned >= 7, f"scan surface shrank to {scanned} files — glob broken"
    return hits


# ── the ratchet ─────────────────────────────────────────────────────────────


def test_no_unsanctioned_swallow_on_the_ingestion_surface():
    """Case 1: every swallow site is explicitly sanctioned, by path::symbol."""
    unsanctioned = sorted(
        {h["key"] for h in _all_swallow_sites()} - set(SANCTIONED)
    )
    assert unsanctioned == [], (
        "swallowed failure(s) on the ingestion/freshness surface — log with "
        "logger.exception, propagate, or route through freshness.read_ledger; "
        "only a proven default-shape reader may be sanctioned: "
        f"{unsanctioned}"
    )


def test_sanctioned_list_matches_discovered_exactly():
    """Case 2: no stale entries — a FIXED site must drop off the list too."""
    discovered = {h["key"] for h in _all_swallow_sites()}
    stale = sorted(set(SANCTIONED) - discovered)
    assert stale == [], (
        f"sanctioned entry no longer exists in the source (remove it): {stale}"
    )


def test_every_sanctioned_entry_documents_its_reason():
    """Case 3: a sanctioned swallow carries a non-trivial justification."""
    for key, reason in SANCTIONED.items():
        assert key.count("::") == 1, f"key must be path::symbol: {key}"
        assert len(reason.strip()) > 30, f"reason too thin for {key}: {reason!r}"


def test_scanner_flags_an_injected_swallow():
    """Case 4: non-vacuity — the detector fires on a synthetic swallow."""
    source = (
        (ROOT / "football_core" / "freshness.py").read_text(encoding="utf-8")
        + "\n\ndef _injected_swallow(value):\n"
        "    try:\n"
        "        return json.loads(value)\n"
        "    except Exception:\n"
        "        pass\n"
    )
    hits = swallows_in(ROOT / "football_core" / "freshness.py", source)
    assert any(
        h["symbol"] == "_injected_swallow" and h["kind"] == "pass" for h in hits
    ), f"detector missed the injected swallow: {hits}"


# ── loud readers (the unreadable marker reaches the API) ────────────────────


def _write_corrupt_ledger(tmp_path: Path) -> Path:
    ledger = tmp_path / "last_refresh.json"
    ledger.write_text("{ this is not json", encoding="utf-8")
    return ledger


def test_wc_refresh_reader_returns_the_unreadable_marker(tmp_path, monkeypatch):
    """wc_app's reader must not turn a corrupt ledger into "no refresh yet"."""
    from web import wc_app

    ledger = _write_corrupt_ledger(tmp_path)
    monkeypatch.setattr(wc_app, "_refresh_report_path", lambda: ledger)

    report = wc_app._current_refresh_report()
    assert report.get("ledger") == "unreadable", report
    assert report.get("detail"), "the marker must carry the exception class"
    assert report != {}, "an unreadable ledger must never render as {}"


def test_api_data_refresh_block_carries_the_unreadable_marker(
    tmp_path, monkeypatch
):
    """/api/data serves the marker so 02-08's UI can render the failure."""
    from fastapi.testclient import TestClient

    from web import wc_app

    ledger = _write_corrupt_ledger(tmp_path)
    monkeypatch.setattr(wc_app, "_refresh_report_path", lambda: ledger)

    with TestClient(wc_app.wc_app) as client:
        payload = client.get("/api/data").json()

    refresh = payload.get("refresh")
    assert isinstance(refresh, dict), payload
    assert refresh.get("ledger") == "unreadable", refresh
    assert "worldcup" not in refresh, (
        "the marker IS the failure signal; per-competition content is absent"
    )


def test_healthy_ledger_still_serves_the_worldcup_entry(tmp_path, monkeypatch):
    """Control: the loud reader keeps the healthy-path shape unchanged."""
    from web import wc_app

    ledger = tmp_path / "last_refresh.json"
    ledger.write_text(
        json.dumps({"worldcup": {"success": True, "stale": False}}), encoding="utf-8"
    )
    monkeypatch.setattr(wc_app, "_refresh_report_path", lambda: ledger)

    report = wc_app._current_refresh_report()
    assert report == {"success": True, "stale": False}
