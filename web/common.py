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
from fastapi.responses import JSONResponse


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


def offline_refresh_report() -> dict:
    """Full IngestReport-schema report for an explicit offline session (plan 02-06).

    The refresh wrappers' snapshot branch previously recorded a four-key
    ad-hoc dict, so ``POST /api/refresh`` answered with a *partial* body in
    offline mode — exactly the shape the plan forbids. This helper keeps the
    whole disclosure on the SAME schema every other outcome uses: zeroed
    finished counters, ``stages: []`` (no row may invent work that never
    happened), ``deferred: True`` with ``reason="deferred"``, and the
    verbatim ``skipped_reason`` wording the dashboard reads.

    Returns:
        A fresh full-schema dict, always ``attempted=False``/``success=False``.
    """
    from football_core.fetcher import IngestReport

    report = IngestReport(
        provider=None,
        attempted=False,
        success=False,
        error=None,
        stale=True,
        deferred=True,
        reason="deferred",
    ).to_dict()
    report["skipped_reason"] = SNAPSHOT_SKIP_REASON
    return report


def _utc_z(value: str | None) -> str | None:
    """Normalize an ISO-8601 UTC instant to the contract's ``Z`` suffix.

    Older app-level entries record ``last_refresh`` with the ``+00:00``
    offset; the IngestReport contract spells the same instant with ``Z``.
    Anything that is not already UTC (``+00:00`` / ``Z``) is left verbatim —
    an unparseable instant must never be silently rewritten.
    """
    if not isinstance(value, str) or not value:
        return None
    if value.endswith("+00:00"):
        return value[:-6] + "Z"
    return value


def refresh_response_body(report: dict, mode: str | None = None) -> dict:
    """Full IngestReport-shaped ``POST /api/refresh`` body (plan 02-06).

    The report IS the outcome: ``attempted``/``success``/``error``/``stale``
    /``reason``/``stages``/``provider``/``last_success_at`` all ride along
    verbatim, so a consumer never has to infer anything from a status string.
    HTTP stays 200 — the acquisition wrapper never raises, and a truthful
    failure is data, not an HTTP error (503 is reserved for the unexpected
    exception path via :func:`error_response`).

    Two normalizations happen here because the ADAPTER returns each app's
    own ledger-shaped report, which historically omitted keys the IngestReport
    contract guarantees (CS-3):

    1. **Key-set completeness** — every ``IngestReport.to_dict`` key is
       present. Absent keys are filled with honest defaults (nothing
       attempted → ``attempted=False``, no recorded rows → ``stages=[]``);
       counters fall back to the contract's zeroed ``finished`` shape, never
       to a fabricated success.
    2. **``status`` shim** — the legacy key now MIRRORS the report instead of
       meaning "no exception was raised". A brain-supplied transport status
       (e.g. UCL's ``"deferred"``) is preserved; otherwise it is derived as
       ``ok`` (attempted and succeeded), ``error`` (attempted and failed) or
       ``skipped`` (nothing attempted).

    ``refreshed`` and ``mode`` are kept for the existing dashboard contract.
    """
    from football_core.fetcher import _zero_finished_counters

    body = dict(report)
    success = bool(report.get("success"))

    # 1. Full IngestReport key set (missing ≠ "nothing happened" — the
    #    defaults describe "no evidence", they never assert a fresh run).
    body.setdefault("provider", None)
    body.setdefault("attempted", False)
    body.setdefault("success", False)
    body.setdefault("error", None)
    body.setdefault("stale", not success)
    body.setdefault("finished", _zero_finished_counters())
    body.setdefault("stages", [])
    body.setdefault("written_files", [])
    body.setdefault("deferred", False)
    body.setdefault("reason", None)
    if not body.get("last_success_at"):
        # A successful run IS the last success; the adapter entries record
        # `last_refresh` (attempt instant), which equals it for that run.
        body["last_success_at"] = (
            _utc_z(report.get("last_refresh")) if success else None
        )
    else:
        body["last_success_at"] = _utc_z(body["last_success_at"])
    if success and not body["last_success_at"]:
        from datetime import datetime, timezone

        body["last_success_at"] = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z")

    # 2. Legacy `status`: derived FROM the report, never asserted beside it,
    #    so the shim cannot contradict `success`/`attempted`/`deferred`
    #    (D-13: a transport "ok" that ingested nothing reads as an error,
    #    a configured-but-unpublished provider reads as `deferred`, an
    #    offline session as `skipped`).
    attempted = bool(body.get("attempted"))
    reason = str(body.get("reason") or "")
    deferred = bool(body.get("deferred")) or reason.startswith("deferred")
    body["deferred"] = deferred  # one truth: the flag and `status` agree
    if not attempted:
        body["status"] = "skipped"
    elif success:
        body["status"] = "ok"
    elif deferred:
        body["status"] = "deferred"
    else:
        body["status"] = "error"
    body["refreshed"] = success
    if mode is not None:
        body["mode"] = mode
    return body


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


def _json_default(obj):
    """JSON fallback for the frozen containers the derived snapshot serves.

    ``MappingProxyType`` is not serializable by a bare ``json.dumps`` (FastAPI's
    ``jsonable_encoder`` handles it, but the ~120 existing ``JSONResponse(``
    call sites do not). ``RobustJSONResponse`` routes through here so payloads
    that became frozen need no per-call-site churn.
    """
    from types import MappingProxyType

    if isinstance(obj, MappingProxyType):
        return dict(obj)
    if isinstance(obj, (set, frozenset)):
        return list(obj)
    raise TypeError(
        f"Object of type {type(obj).__name__} is not JSON serializable"
    )


class RobustJSONResponse(JSONResponse):
    """``JSONResponse`` that serializes frozen (proxy/tuple/frozenset) payloads."""

    def render(self, content) -> bytes:
        return json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            indent=None,
            separators=(",", ":"),
            default=_json_default,
        ).encode("utf-8")
