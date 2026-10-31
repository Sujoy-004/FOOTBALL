"""Startup data-acquisition decision flow.

Runs once at server startup (inside the FastAPI lifespan) and decides how
this session acquires competition data.

Policy: fresh acquisition FIRST, validated snapshot FALLBACK. Normal
execution NEVER offers a choice that disables scraping — the historical
interactive menu ([1] key / [2] offline) was removed in Exchange 4 v2
because option [2] could be mistaken for a normal startup path.

Decision flow:
    FOOTBALL_SNAPSHOT=1 set?
        ├─ yes ─▶ snapshot (explicit offline session, zero network)
        └─ no
           usable provider credential configured?
             ├─ yes ─▶ live-configured (no prompt, no banner)
             └─ no  ─▶ auto: acquisition will be attempted but no provider
                       is configured - stored data will be used until
                       credentials are provided. Never blocks, never
                       prompts, interactive or not.

"snapshot" mode is EXPLICIT only: the FOOTBALL_SNAPSHOT override or a
forced StartupDecision("snapshot") (tests). In snapshot mode the fetch
wrappers self-gate and make ZERO network requests. Every other decision
kind ("auto", "live-configured") lets acquisition happen on the explicit
per-competition refresh trigger (POST /api/refresh, FOOTBALL_PRELOAD_ALL
preload, or a test — see web.competitions); failed attempts
never delete or overwrite existing factual stores.

Credentials live in the process environment only; nothing is persisted.

Layer rule: the snapshot *mode flag* and its environment predicate live in
:mod:`football_core.runtime_support` so competition brains can ask whether the
session is offline without importing the web layer. This module keeps the
decision *type* and the decision *lifecycle*, which are web-session concerns,
and ``is_snapshot_mode`` stays importable here as a delegating shim.
"""

from __future__ import annotations

import os
from typing import Callable, NamedTuple

from football_core import runtime_support

# Re-exported from the kernel so the documented constant keeps one definition.
SNAPSHOT_ENV_VAR = runtime_support.SNAPSHOT_ENV_VAR

# Required banner shown when normal execution proceeds without any usable
# provider credential. Worded so nobody mistakes auto mode for offline.
NO_PROVIDER_BANNER = (
    "acquisition will be attempted but no provider is configured - "
    "stored data will be used until credentials are provided")


class StartupDecision(NamedTuple):
    mode: str          # "live-configured" | "auto" | "snapshot"
                       # ("live-entered" remains constructible for tests/
                       #  backwards compatibility; no flow produces it)
    fdo_key: str       # configured key ("" for auto/snapshot)


_last_decision: StartupDecision | None = None


def is_snapshot_mode() -> bool:
    """Compatibility shim; the implementation lives in football_core.runtime_support."""
    return runtime_support.is_snapshot_mode()


def set_session_decision(decision: StartupDecision | None) -> None:
    """Record this session's decision and sync the kernel's snapshot flag.

    This is the ONLY writer of ``_last_decision``. Assigning the module global
    directly would leave the kernel flag stale, and the failure would be silent:
    an "offline" session would keep reaching the network.
    """
    global _last_decision
    _last_decision = decision
    runtime_support.set_snapshot_session(
decision is not None and decision.mode == "snapshot")


def _is_placeholder(value: str) -> bool:

    v = value.strip().lower()
    return (not v) or v.startswith("your_")


def has_usable_fdo_key(key: str | None) -> bool:
    """True when the configured football-data.org key looks real.

    Real provider validation happens later at refresh time — this only
    filters empty/example values so we don't announce live mode for a
    template credential.
    """
    return not _is_placeholder(key or "")


def apply_session_overrides(fdo_key: str) -> None:
    """Propagate a session key into this process without persisting it.

    The competition apps read their credentials at CALL time (via
    ``_football_data_org_key()``), so setting the env var
    is enough — no ``sys.modules`` write-back patching of already-imported
    app modules is needed (and none is correct: it would diverge from every
    module that never got patched).
    """
    os.environ["FOOTBALL_DATA_ORG_KEY"] = fdo_key


def run_startup_flow(
    echo: Callable[[str], None] | None = None,
) -> StartupDecision:
    """Decide this session's acquisition posture. Never prompts.

    Normal execution always ends in a fresh-first decision kind
    ("live-configured" or "auto"); the only route to "snapshot" is the
    FOOTBALL_SNAPSHOT env override (or a forced decision in tests).
    """
    echo = echo or print

    def _decide(mode, key=''):
        set_session_decision(StartupDecision(mode, key))
        return _last_decision

    # Explicit offline override wins over everything else this session
    # (documented in .env.example): zero scraping regardless of keys.
    if runtime_support.env_snapshot_forced():
        echo(f"{SNAPSHOT_ENV_VAR} is set — working offline with existing "
             "snapshot data (no scraping this session).")
        return _decide("snapshot", "")

    existing = os.getenv("FOOTBALL_DATA_ORG_KEY", "")

    # Usable key already configured: no prompt, no banner.
    if has_usable_fdo_key(existing):
        echo("Live data provider configured.")
        echo("Starting server...")
        return _decide("live-configured", existing)

    # No usable credential: informational banner, then the normal
    # fresh-first policy. Acquisition stays on the explicit trigger
    # (POST /api/refresh, FOOTBALL_PRELOAD_ALL preload, or a test); with
    # no provider configured each attempt resolves to a truthful "no data
    # provider configured" report instead of network traffic.
    echo(NO_PROVIDER_BANNER)
    return _decide("auto", "")
