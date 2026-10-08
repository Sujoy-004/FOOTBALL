"""Web-layer helpers.

``error_response`` and ``load_json`` are genuinely web concerns and live here.

``ts``, ``boot_step`` and ``get_data_provider`` are competition-agnostic
runtime utilities and now live in :mod:`football_core.runtime_support`. They
remain importable from this module as **delegating** wrappers rather than bare
re-exports, so that a single patched symbol is authoritative for the web layer
and every competition brain alike: a wrapper resolves ``runtime_support.<name>``
at call time, so patching the kernel is observed here, and patching the wrapper
is still observed by web-only callers.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from football_core import runtime_support


def ts() -> str:
    """Compatibility shim; the implementation lives in football_core.runtime_support."""
    return runtime_support.ts()


def boot_step(
    step_name: str, action: Callable[[], Any], boot_log: list
) -> Any:
    """Compatibility shim; the implementation lives in football_core.runtime_support."""
    return runtime_support.boot_step(step_name, action, boot_log)


def get_data_provider(
    bsd_api_key: str, football_data_org_key: str, bsd_league_id: int
) -> Any:
    """Compatibility shim; the implementation lives in football_core.runtime_support."""
    return runtime_support.get_data_provider(
        bsd_api_key, football_data_org_key, bsd_league_id
    )


def load_json(data_dir, name: str) -> dict:
    with open(data_dir / name, encoding="utf-8") as f:
        return dict(json.load(f))


#: Refresh-block ``reason`` for "this process never refreshed this
#: competition" (plan 02-06): a first-ever plain read must never read as
#: fresh or successful without evidence.
NOT_ATTEMPTED_REASON = "not_attempted"

#: Verbatim disclosure an explicit offline session carries (kept in one
#: place so the API surface, the pipeline report and the dashboard all
#: agree on the wording).
SNAPSHOT_SKIP_REASON = "snapshot mode selected at startup"


def not_attempted_report() -> dict:
    """Truthful refresh block for "nothing has been attempted".

    Always ``attempted=False``/``success=False``/``stale=True``. In an
    explicit offline session (``FOOTBALL_SNAPSHOT=1`` or ``--offline``) it
    also carries ``skipped_reason``, so the very first read can disclose
    "snapshot (offline)" instead of implying a live fetch happened —
    reads stay pure while the session's provenance stays visible.

    Returns:
        A fresh dict each call (callers merge it into their own blocks).
    """
    block: dict[str, Any] = {
        "provider": None,
        "attempted": False,
        "success": False,
        "error": None,
        "stale": True,
        "reason": NOT_ATTEMPTED_REASON,
    }
    from web.startup import is_snapshot_mode

    if is_snapshot_mode():
        block["skipped_reason"] = SNAPSHOT_SKIP_REASON
    return block


def error_response(
    exc: Exception,
    *,
    status: int = 500,
    context: str = "",
    public: str = "Internal server error",
):
    """Log the real cause; return a generic message to the client (no leak).

    Provider/internal exception text (URLs, tokens, file paths, upstream
    error bodies) must never reach an HTTP client. The traceback goes to
    the log; the caller gets a fixed ``public`` string.
    """
    import logging

    from fastapi.responses import JSONResponse

    logging.getLogger(__name__).exception(
        "request failed (%s): %s", context or "?", exc)
    return JSONResponse({"error": public}, status_code=status)
