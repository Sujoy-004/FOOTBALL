"""Interactive startup flow: choose live API access or snapshot data.

Runs once at server startup (inside the FastAPI lifespan) and answers a
single question: can we attempt live access with configured credentials?

Decision flow:
    usable FOOTBALL_DATA_ORG_KEY configured?
        ├─ yes ─▶ live mode (no prompt)
        └─ no
           interactive TTY?
            ├─ yes ─▶ menu: [1] enter key (validated live, session-only)
            │              [2] snapshot (skips refresh, marked stale)
            └─ no  ─▶ snapshot (never blocks)

Entered keys live in session memory only; nothing is persisted.
"""

from __future__ import annotations

import getpass
import os
import sys
from typing import Callable, NamedTuple


class StartupDecision(NamedTuple):
    mode: str          # "live-configured" | "live-entered" | "snapshot"
    fdo_key: str       # session key to propagate ("" for snapshot)


_last_decision: StartupDecision | None = None


def is_snapshot_mode() -> bool:
    """True once startup chose snapshot mode (unset => live semantics)."""
    return _last_decision is not None and _last_decision.mode == "snapshot"


def is_interactive() -> bool:
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:
        return False


def _is_placeholder(value: str) -> bool:
    v = value.strip().lower()
    return (not v) or v.startswith("your_")


def has_usable_fdo_key(key: str | None) -> bool:
    """True when the configured football-data.org key looks real.

    Real provider validation happens later at refresh time — this only
    filters empty/example values so we don't pointlessly prompt users who
    already configured a credential.
    """
    return not _is_placeholder(key or "")


def validate_fdo_key(key: str) -> tuple[bool, str | None]:
    """Attempt real live access with *key* using the existing FDO provider."""
    from football_core.data_providers.football_data_org_provider import (
        FootballDataOrgProvider,
    )
    provider = FootballDataOrgProvider(key)
    matches = provider.fetch_matches(competition_id="WC")
    if matches:
        return True, None
    return False, (getattr(provider, "last_error", None) or "no matches returned")


def apply_session_overrides(fdo_key: str) -> None:
    """Propagate a session-entered key into this process without persisting it."""
    os.environ["FOOTBALL_DATA_ORG_KEY"] = fdo_key
    # Update already-imported app modules directly (sys.modules covers both
    # the production case and any pre-imported state under test runners).
    for name in ("web.wc_app", "web.ucl_app"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "FOOTBALL_DATA_ORG_KEY"):
            mod.FOOTBALL_DATA_ORG_KEY = fdo_key


def run_startup_flow(
    input_fn: Callable[[str], str] | None = None,
    validate_fn: Callable[[str], tuple[bool, str | None]] | None = None,
    interactive_fn: Callable[[], bool] | None = None,
    echo: Callable[[str], None] | None = None,
    key_input_fn: Callable[[str], str] | None = None,
) -> StartupDecision:
    input_fn = input_fn or input
    validate_fn = validate_fn or validate_fdo_key
    interactive_fn = interactive_fn or is_interactive
    key_input_fn = key_input_fn or getpass.getpass
    echo = echo or print

    global _last_decision

    def _decide(mode, key=''):
        global _last_decision
        _last_decision = StartupDecision(mode, key)
        return _last_decision
    existing = os.getenv("FOOTBALL_DATA_ORG_KEY", "")

    # Case A — usable key already configured: no prompt.
    if has_usable_fdo_key(existing):
        echo("Live data provider configured.")
        echo("Starting server...")
        return _decide("live-configured", existing)

    # Case B — no key: prompt only in an interactive terminal.
    if not interactive_fn():
        echo("No valid live API key configured (non-interactive) — "
             "using existing snapshot data.")
        return _decide("snapshot", "")

    echo("")
    echo("FOOTBALL Data Mode")
    echo("────────────────────────────")
    echo("")
    echo("No valid live API key is configured.")
    echo("")

    while True:
        echo("[1] Enter an API key and refresh live data")
        echo("[2] Continue using existing snapshot data")
        choice = (input_fn("Choose [1/2]: ") or "").strip()

        if choice == "2":
            echo("Starting with existing snapshot data.")
            echo("Live refresh was skipped by user.")
            return _decide("snapshot", "")

        if choice != "1":
            echo("Please choose 1 or 2.")
            continue

        # Option 1 — key entry loop with failure sub-menu.
        while True:
            key = key_input_fn("API key: ").strip()
            if not key:
                echo("No key entered.")
            else:
                ok, err = validate_fn(key)
                if ok:
                    echo("Live API access confirmed.")
                    echo("Data refresh completed.")
                    echo("Starting server...")
                    return _decide("live-entered", key)
                echo(f"Live API validation/refresh failed: {err}")

            while True:
                sub = (input_fn("Choose [1/2/3]: ") or "").strip()
                if sub == "1":
                    break                      # retry key entry
                if sub == "2":
                    echo("Starting with existing snapshot data.")
                    echo("Live refresh was skipped by user.")
                    return _decide("snapshot", "")
                if sub == "3":
                    raise SystemExit(0)
                echo("Please choose 1, 2 or 3.")
