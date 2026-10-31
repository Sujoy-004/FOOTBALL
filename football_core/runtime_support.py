"""Kernel-level runtime utilities.

Shared by the competition brains and the web layer so that neither imports the
other. These four helpers used to live in ``web/common.py`` and
``web/startup.py``, which forced ``competitions/*/src/`` to import ``web.*``
purely to reach a competition-agnostic utility. They carry no HTTP semantics,
no request object and no tournament knowledge, so the kernel is their home.

Layer rule: this module imports nothing from ``web.*`` or ``competitions.*``.
The web layer keeps ``web.common`` / ``web.startup`` as thin delegating shims
so every existing import path and every web caller keeps working unchanged.

Credentials: ``get_data_provider`` reads the process environment at CALL time,
never at import time. Zero provider calls at boot is hard project policy, so an
import of this module must never construct a provider or read a key.

Authority: ``web/common.py`` and ``web/startup.py`` resolve these symbols on
this module at call time rather than re-exporting them, so a single patched
symbol is authoritative for the web layer and every competition brain alike.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Environment variable that forces an explicitly offline session. Re-exported
# by ``web.startup`` so the documented constant has exactly one definition.
SNAPSHOT_ENV_VAR = "FOOTBALL_SNAPSHOT"

_FALSY_ENV_VALUES = ("", "0", "false", "no", "off")

# Session-level snapshot decision: ``None`` = no decision has been recorded,
# ``True``/``False`` = the decision resolved by the startup flow or a caller of
# ``set_snapshot_session``. Only ``True`` selects offline mode; the env var
# always wins over it.
_snapshot_session: bool | None = None


def ts() -> str:
    """Return the current UTC time as ``YYYY-MM-DD HH:MM:SS``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def boot_step(
    step_name: str, action: Callable[[], Any], boot_log: list
) -> Any:
    """Run one startup/boot step, recording the outcome in ``boot_log``.

    Contract (unchanged by the move, and relied on by boot diagnostics):

    - On success, append an ``ok`` entry and return the action's result.
    - On failure, append an ``error`` entry carrying the exception text and
      return ``None``. This function never raises: one failing boot step must
      not take the server down, and the recorded entry is what the diagnostics
      surface reports.
    """
    t0 = time.time()
    try:
        result = action()
        elapsed = time.time() - t0
        boot_log.append({
            "step": step_name, "status": "ok",
            "elapsed": round(elapsed, 2),
            "output": f"[{ts()}] {step_name} — done in {elapsed:.1f}s",
        })
        return result
    except Exception as e:
        elapsed = time.time() - t0
        boot_log.append({
            "step": step_name, "status": "error",
            "elapsed": round(elapsed, 2),
            "output": f"[{ts()}] {step_name} — FAILED ({e})",
        })
        return None


def _usable_key(value: str | None) -> str | None:
    """Return the key when it is a real credential, else None.

    A placeholder ("your_api_key_here" style) or empty value selects
    nothing - a template key must never reach the network as if live.
    """
    text = (value or "").strip()
    if not text or text.lower().startswith("your_"):
        return None
    return text


def get_data_provider(
    *args,
    football_data_org_key: str = "",
    **kwargs,
) -> Any:
    """Single provider-selection factory for every competition.

    Precedence:
      1. DATA_PROVIDER=football-data + FDO key  -> FootballDataOrgProvider
      2. no env var -> FootballDataOrgProvider if key is present
      3. no usable key at all -> None (caller skips live fetch)

    Empty or "your_..." placeholder keys never select a provider.

    Credentials are read from ``os.environ`` when this is called, never when
    this module is imported, so a cold boot makes zero provider calls.
    """
    from football_core.data_providers.football_data_org_provider import (
        FootballDataOrgProvider,
    )

    fdo_key = None
    if len(args) >= 2:
        # Positional compatibility: (ignored_key, football_data_org_key, ...)
        fdo_key = _usable_key(args[1]) or _usable_key(args[0])
    elif len(args) == 1:
        fdo_key = _usable_key(args[0])

    if not fdo_key:
        fdo_key = _usable_key(
            football_data_org_key
            or kwargs.get("football_data_org_key")
            or kwargs.get("fdo_key")
            or os.environ.get("FOOTBALL_DATA_ORG_KEY")
        )

    mode = os.getenv("DATA_PROVIDER", "").lower()
    if mode in ("", "football-data", "auto") and fdo_key:
        return FootballDataOrgProvider(fdo_key)
    if fdo_key:
        return FootballDataOrgProvider(fdo_key)
    return None


def env_snapshot_forced() -> bool:
    """True when ``FOOTBALL_SNAPSHOT`` explicitly requests an offline session.

    Read from the environment on every call so a test (or ``.env`` edit) takes
    effect without a reimport.
    """
    raw = os.environ.get(SNAPSHOT_ENV_VAR, "")
    return raw.strip().lower() not in _FALSY_ENV_VALUES


def set_snapshot_session(enabled: bool) -> None:
    """Record this session's snapshot decision for :func:`is_snapshot_mode`."""
    global _snapshot_session
    _snapshot_session = enabled


def is_snapshot_mode() -> bool:
    """True ONLY for explicit offline-snapshot sessions.

    Snapshot semantics require an explicit choice: the ``FOOTBALL_SNAPSHOT``
    env override or a recorded session decision of kind "snapshot". The env
    override always wins. The default "auto" decision attempts fresh
    acquisition and therefore is NOT snapshot mode; an unrecorded session with
    no env override is ``False``, never an error and never ``None``.
    """
    if env_snapshot_forced():
        return True
    return _snapshot_session is True
