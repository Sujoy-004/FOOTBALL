"""Cache-control policy for competition API responses (Exchange 9C).

A browser tab that stays open across a server-side refresh must be able to
re-fetch fresh data: unreleased JSON responses are the reason the live UCL
tab silently kept serving yesterday's match scores (Phase 9B root cause).
Python-side caching (http.cache, uvicorn-level) was already avoided, but the
HTTP layer shipped no explicit opt-out, so shared caches (and devtool
replay) were free to serve stale competition payloads.

This module is the single, registry-derived answer: a reusable ASGI
middleware that stamps ``Cache-Control: no-store`` onto every response whose
path belongs to a mounted competition API. Prefixes are derived from the
REGISTRY adapter ``api_prefix`` values at composition time, so a future
competition registered there is covered automatically without a second edit.

Simulation endpoints are included on purpose: they are idempotent reads (a
re-fetch never recomputes server state) and the no-store policy keeps
request/render ordering truthful for the user.
"""

from __future__ import annotations

from typing import Iterable

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send


def competition_api_prefixes() -> list[str]:
    """The mounted competition API prefixes (e.g. ``/ucl/api``).

    Read live from the registry so the policy follows registration order
    and any future competition is included automatically.
    """
    from web.competitions import REGISTRY

    return [a.api_prefix for a in REGISTRY.list() if a.api_prefix]


class _NoStoreForCompetitionAPI:
    """ASGI wrapper — stamps ``Cache-Control: no-store`` on competition API
    responses (any path equal to, or under, a configured API prefix)."""

    def __init__(self, app: ASGIApp, prefixes: Iterable[str]) -> None:
        self.app = app
        self._prefixes = tuple(p.rstrip("/") for p in prefixes if p)

    def _applies(self, path: str) -> bool:
        for prefix in self._prefixes:
            if path == prefix or path.startswith(prefix + "/"):
                return True
        return False

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._applies(scope.get("path", "")):
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_wrapper)


def no_store_for_competition_api(app: ASGIApp,
                                 prefixes: Iterable[str] | None = None) -> ASGIApp:
    """Wrap ``app`` so every competition API response is ``Cache-Control:
    no-store``.

    ``prefixes`` default to the registered competition ``api_prefix``
    values (``competition_api_prefixes()``), so calling this with no
    argument keeps the policy in lock-step with the registry.
    """
    if prefixes is None:
        prefixes = competition_api_prefixes()
    return _NoStoreForCompetitionAPI(app, prefixes)