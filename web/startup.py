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
kind ("auto", "live-configured") lets acquisition happen lazily per
competition (see web.competitions.try_lazy_refresh); failed attempts
never delete or overwrite existing factual stores.

Credentials live in the process environment only; nothing is persisted.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, NamedTuple

SNAPSHOT_ENV_VAR = "FOOTBALL_SNAPSHOT"

_FALSY_ENV_VALUES = ("", "0", "false", "no", "off")

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


def _env_snapshot_forced() -> bool:
    """True when FOOTBALL_SNAPSHOT explicitly requests an offline session."""
    raw = os.environ.get(SNAPSHOT_ENV_VAR, "")
    return raw.strip().lower() not in _FALSY_ENV_VALUES


def is_snapshot_mode() -> bool:
    """True ONLY for explicit offline-snapshot sessions.

    Snapshot semantics require an explicit choice: the FOOTBALL_SNAPSHOT
    env override or a forced decision of kind "snapshot" (tests). The
    default "auto" decision attempts fresh acquisition and therefore is
    NOT snapshot mode.
    """
    if _env_snapshot_forced():
        return True
    return _last_decision is not None and _last_decision.mode == "snapshot"


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
    """Propagate a session key into this process without persisting it."""
    os.environ["FOOTBALL_DATA_ORG_KEY"] = fdo_key
    # Update already-imported app modules directly (sys.modules covers both
    # the production case and any pre-imported state under test runners).
    for name in ("web.wc_app", "web.ucl_app"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "FOOTBALL_DATA_ORG_KEY"):
            mod.FOOTBALL_DATA_ORG_KEY = fdo_key


def run_startup_flow(
    echo: Callable[[str], None] | None = None,
) -> StartupDecision:
    """Decide this session's acquisition posture. Never prompts.

    Normal execution always ends in a fresh-first decision kind
    ("live-configured" or "auto"); the only route to "snapshot" is the
    FOOTBALL_SNAPSHOT env override (or a forced decision in tests).
    """
    echo = echo or print

    global _last_decision

    def _decide(mode, key=''):
        global _last_decision
        _last_decision = StartupDecision(mode, key)
        return _last_decision

    # Explicit offline override wins over everything else this session
    # (documented in .env.example): zero scraping regardless of keys.
    if _env_snapshot_forced():
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
    # fresh-first policy. Acquisition stays lazy per competition
    # (web.competitions.try_lazy_refresh); with no provider configured
    # each attempt resolves to a truthful "no data provider configured"
    # report instead of network traffic.
    echo(NO_PROVIDER_BANNER)
    return _decide("auto", "")
