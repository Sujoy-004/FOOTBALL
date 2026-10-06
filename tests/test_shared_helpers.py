"""One patch target per shared runtime helper, across both layers.

``ts``, ``boot_step``, ``get_data_provider`` and ``is_snapshot_mode`` are
competition-agnostic runtime utilities. They used to live in ``web/``, which
forced the competition brains to import the web layer to reach them. They now
live in :mod:`football_core.runtime_support`, and ``web.common`` /
``web.startup`` keep the same public names as **delegating** wrappers.

The property these tests defend is not "the helpers moved". It is that a
single patched symbol is authoritative for the web layer *and* every
competition brain. A bare re-export would break ~24 test modules' intent
silently: they patch the provider factory precisely so the whole refresh path
uses a fake, and two independent bindings cannot both be the patch target.

The snapshot flag carries a sharper version of the same risk. Assigning
``web.startup._last_decision`` used to work because ``is_snapshot_mode()``
read that global. Once the mode check moved to the kernel, such an assignment
became a silent no-op and the test would quietly run LIVE. Case 4 and case 6
are what stop that.
"""

from __future__ import annotations

import ast
from pathlib import Path

from football_core import runtime_support

REPO_ROOT = Path(__file__).resolve().parents[1]

# Every test module in the repo that may legitimately patch or force a mode.
TEST_ROOTS = ("tests", "competitions/ucl/tests", "competitions/worldcup/tests",
              "competitions/laliga/tests", "football_core/tests")

STALE_PATCH_PATTERNS = (
    # string-form monkeypatch targets
    '"web.common.get_data_provider"',
    "'web.common.get_data_provider'",
    '"web.startup.is_snapshot_mode"',
    "'web.startup.is_snapshot_mode'",
    # attribute-form targets
    'web.common, "get_data_provider"',
    "web.common, 'get_data_provider'",
    'web.startup, "is_snapshot_mode"',
    "web.startup, 'is_snapshot_mode'",
    # direct global assignment instead of the explicit setter
    "_last_decision =",
    # ...and the multi-line monkeypatch spelling of the same mistake
    'setattr(startup, "_last_decision"',
    "setattr(startup, '_last_decision'",
    'startup, "_last_decision"',
    "startup, '_last_decision'",
)


def _test_files():
    this_file = Path(__file__).resolve()
    for root in TEST_ROOTS:
        base = REPO_ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("test_*.py")):
            # This module necessarily contains the patterns it bans, so it
            # cannot be subject to its own scan.
            if path.resolve() == this_file:
                continue
            yield path


# ── case 1: one patch target, observed by web and by a competition brain ──


def test_kernel_patch_is_seen_by_web_shim(monkeypatch):
    """Case 1a: the web-layer shim resolves the kernel symbol at call time."""
    monkeypatch.setattr(
        runtime_support, "get_data_provider", lambda *a: "FAKE")
    from web.common import get_data_provider  # noqa: PLC0415

    assert get_data_provider(None, None, None) == "FAKE"


def test_kernel_patch_is_seen_by_competition_brain(monkeypatch, tmp_path):
    """Case 1b: the World Cup brain resolves the SAME kernel symbol.

    ``fetch_live_data`` constructs the provider before it touches any data
    file, so an empty ``tmp_path`` is enough: the fake is constructed and then
    the call reports unreadable local data. What matters here is only that the
    brain called the patched kernel symbol rather than its own binding.
    """
    import web.startup as startup  # noqa: PLC0415

    monkeypatch.delenv(runtime_support.SNAPSHOT_ENV_VAR, raising=False)
    monkeypatch.setattr(startup, "set_session_decision", startup.set_session_decision)
    startup.set_session_decision(None)

    calls: list[tuple] = []

    def _fake_provider(*args):
        calls.append(args)
        return object()

    monkeypatch.setattr(runtime_support, "get_data_provider", _fake_provider)

    from competitions.worldcup.src.pipeline import fetch_live_data  # noqa: PLC0415

    fetch_live_data("bsd", "fdo", tmp_path)

    assert len(calls) == 1, (
        "the World Cup brain did not call the patched kernel provider factory; "
        f"it called something else (calls={calls!r})"
    )


# ── case 2: the snapshot shim delegates ──────────────────────────────────


def test_kernel_snapshot_patch_is_seen_by_web_shim(monkeypatch):
    """Case 2: patching the kernel is observed through ``web.startup``."""
    import web.startup as startup  # noqa: PLC0415

    monkeypatch.setattr(
        runtime_support, "is_snapshot_mode", lambda: "FROM-KERNEL")
    assert startup.is_snapshot_mode() == "FROM-KERNEL"


# ── case 3: D-02's import-path promise still holds ───────────────────────


def test_legacy_import_paths_still_resolve():
    """Case 3: no web caller had to change its import statement."""
    from web.common import boot_step, get_data_provider, load_json, ts  # noqa: PLC0415
    from web.startup import is_snapshot_mode, set_session_decision  # noqa: PLC0415

    for symbol in (ts, boot_step, get_data_provider, load_json,
                   is_snapshot_mode, set_session_decision):
        assert callable(symbol), symbol


# ── case 4: forcing snapshot mode through the setter syncs both layers ────


def test_set_session_decision_syncs_kernel_flag(monkeypatch):
    """Case 4: snapshot on -> True, cleared -> False, in BOTH layers."""
    import web.startup as startup  # noqa: PLC0415

    monkeypatch.delenv(runtime_support.SNAPSHOT_ENV_VAR, raising=False)

    startup.set_session_decision(startup.StartupDecision("snapshot", ""))
    assert runtime_support.is_snapshot_mode() is True
    assert startup.is_snapshot_mode() is True
    assert startup._last_decision.mode == "snapshot"

    startup.set_session_decision(None)
    assert runtime_support.is_snapshot_mode() is False
    assert startup.is_snapshot_mode() is False


def test_set_session_decision_does_not_sync_kernel_mid_decision(monkeypatch):
    """A non-snapshot decision must clear the kernel flag, not leave it set."""
    import web.startup as startup  # noqa: PLC0415

    monkeypatch.delenv(runtime_support.SNAPSHOT_ENV_VAR, raising=False)

    startup.set_session_decision(startup.StartupDecision("snapshot", ""))
    assert runtime_support.is_snapshot_mode() is True

    startup.set_session_decision(startup.StartupDecision("auto", ""))
    assert runtime_support.is_snapshot_mode() is False


# ── case 5: the env override still wins ──────────────────────────────────


def test_env_override_beats_every_session_decision(monkeypatch):
    """Case 5: FOOTBALL_SNAPSHOT=1 is a hard offline guarantee."""
    import web.startup as startup  # noqa: PLC0415

    falsy = ("", "0", "false", "no", "off")
    for raw in ("1", "true", "yes", "on", "0", "", "off", "FALSE"):
        monkeypatch.setenv(runtime_support.SNAPSHOT_ENV_VAR, raw)
        startup.set_session_decision(startup.StartupDecision("auto", ""))
        expected = raw.strip().lower() not in falsy
        assert runtime_support.is_snapshot_mode() is expected, raw
        assert startup.is_snapshot_mode() is expected, raw


# ── case 6: no test module patches a shim or pokes the global ────────────


def test_no_test_module_patches_a_web_shim_or_the_decision_global():
    """Case 6: the stale patch surface is empty, repo-wide.

    This is the ratchet. A re-introduced ``monkeypatch.setattr("web.common.
    get_data_provider", ...)`` would un-fake only the web layer and let the
    brain reach the network; a re-introduced ``startup._last_decision = ...``
    would silently force the wrong mode. Both fail loudly here instead.
    """
    offences = []
    for path in _test_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern in STALE_PATCH_PATTERNS:
                if pattern in line:
                    offences.append(
                        f"{path.relative_to(REPO_ROOT).as_posix()}:{lineno}: {line.strip()}"
                    )
    assert not offences, "stale patch targets remain:\n" + "\n".join(offences)


def test_no_competition_brain_imports_web_for_a_shared_helper():
    """The six brain->web imports this plan removed are gone for good.

    Scanned with an AST walk rather than a regex so a multi-line import cannot
    hide. ``compute_full_bracket`` / ``compute_signal_eval`` /
    ``compute_overview`` are plan 01-05's work and are deliberately allowed.
    """
    shared = {"ts", "boot_step", "get_data_provider", "is_snapshot_mode"}
    offenders = []
    for src in sorted((REPO_ROOT / "competitions").glob("*/src/**/*.py")):
        tree = ast.parse(src.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.module
                    and node.module.split(".")[0] == "web"):
                for alias in node.names:
                    if alias.name in shared:
                        offenders.append(
                            f"{src.relative_to(REPO_ROOT).as_posix()}:{node.lineno}: "
                            f"{alias.name}"
                        )
    assert not offenders, "\n".join(offenders)
