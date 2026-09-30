"""Unified FOOTBALL web app — single FastAPI on port 8080.

Mounts competition sub-apps under /worldcup and /ucl.
Serves the SPA shell from /static and the landing page at /.

Boot policy (Exchange 4 v2): the lifespan performs ZERO provider calls.
Caches are computed from validated on-disk stores only; acquisition is
lazy and competition-scoped — each sub-app attempts its own fresh fetch
at most once per process, on its first data-API request (see
web.competitions.try_lazy_refresh). Explicit offline sessions
(FOOTBALL_SNAPSHOT=1, or the --offline CLI flag) never attempt.

Environment flags:
    FOOTBALL_SNAPSHOT=1     explicit OFFLINE execution mode: acquisition
                            wrappers self-gate, zero network all session.
    FOOTBALL_PRELOAD_ALL=1  optional eager preload: the lifespan refreshes
                            every registered competition via
                            adapter.refresh() for warm-tab deployments
                            (default unset = lazy).
"""

import logging
import mimetypes
import os
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

mimetypes.add_type('image/webp', '.webp')

import fastapi
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Receive, Scope, Send
import uvicorn


class _NoCacheASGI:
    """ASGI wrapper — adds Cache-Control: no-cache to every /static/ response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start" and scope.get("path", "").startswith("/static/"):
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            await send(message)

        await self.app(scope, receive, send_wrapper)

from web.cache_control import no_store_for_competition_api
from web.competitions import REGISTRY, consume_lazy_gate


HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


def _ensure_ucl_default_season() -> None:
    """Initialize the shipped UCL draw as the default season when needed.

    This is local-only and idempotent. An existing current.json pointer is
    never changed, so an explicit historical-season selection is preserved.
    """
    from competitions.ucl.src.seasons import get_current_season
    from competitions.ucl.src.season_draw import ensure_draw_season
    import web.ucl_app as _ucl

    draw_snapshot = _ucl.DATA_DIR / "draws" / "2026_27_league_draw.json"
    if get_current_season(_ucl.DATA_DIR) is None and draw_snapshot.exists():
        ensure_draw_season(_ucl.DATA_DIR)
        logger.info("[boot] UCL default season initialized from shipped draw: 2026/27")


def _preload_registered_competitions() -> None:
    """FOOTBALL_PRELOAD_ALL=1 hook: refresh every registered competition.

    Blocking (network acquisition), so the lifespan runs it in a worker
    thread. Each adapter's refresh() never raises; this loop is still
    guarded by the caller so an adapter-level surprise cannot kill boot.
    """
    for _adapter in REGISTRY.list():
        report = _adapter.refresh()  # never raises
        consume_lazy_gate(_adapter.id)
        logger.info("[boot] %s preload refresh: attempted=%s success=%s",
                    _adapter.id, report.get("attempted"),
                    report.get("success"))


async def _boot_step(label: str, fn, *args):
    """Run one boot step in a worker thread; a failure is logged, not fatal.

    Returns the step's value, or None if it raised. The server must come
    up even when one competition's data is unreadable — the tab that needs
    it shows empty, the others serve normally.
    """
    try:
        return await run_in_threadpool(fn, *args)
    except Exception as exc:
        logger.error("[boot] %s failed: %s", label, exc)
        return None


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    from web.startup import apply_session_overrides, run_startup_flow

    # Startup decision (never prompts; normal modes are always
    # fresh-first — see web.startup). Trivial env reads: stays sync.
    try:
        decision = run_startup_flow()
        if decision.fdo_key:
            apply_session_overrides(decision.fdo_key)
    except Exception as exc:
        logger.warning("[boot] startup flow skipped: %s", exc)

    import web.wc_app as _wc
    import web.ucl_app as _ucl

    # Self-bootstrap the shipped UCL draw as the default active season on a
    # fresh runtime. This is local-only and preserves any existing pointer.
    # Disk IO — off the event loop.
    await _boot_step("UCL default-season bootstrap", _ensure_ucl_default_season)

    # Optional eager preload (FOOTBALL_PRELOAD_ALL=1): restore warm-tab
    # behavior by refreshing every registered competition through its own
    # scoped adapter hook. Default (unset): ZERO provider calls at boot.
    if os.environ.get("FOOTBALL_PRELOAD_ALL", "").strip() == "1":
        await _boot_step("eager preload", _preload_registered_competitions)

    # Caches are computed from validated disk stores. No wrapper fetches
    # here: a crashing provider can no longer take down boot, and an
    # unused tab never triggers another competition's provider. All three
    # are CPU/IO-bound (standings, bracket resolution, simulation prep), so
    # they run in worker threads and are individually guarded — a broken
    # competition degrades to an empty cache, never an aborted boot.
    #
    # Route through compute_all so every on-disk state gets the truthful
    # boot: real results -> results view; no/partial results -> honest
    # simulation-available view (never an empty cache).
    _wc.cache = await _boot_step("World Cup compute_overview",
                                 _wc.compute_overview) or {}
    _ucl.cache = await _boot_step("UCL compute_all", _ucl.compute_all) or {}

    import web.laliga_app as _laliga

    _laliga.cache = await _boot_step("LaLiga compute_all",
                                    _laliga.compute_all) or {}
    yield


app = fastapi.FastAPI(title="FOOTBALL", lifespan=lifespan)


@app.get("/")
def landing():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


# Competition mounts come from the registry: the single place to read to
# see which competitions exist. A new competition registers an adapter
# here and is mounted automatically.
for _adapter in REGISTRY.list():
    app.mount(_adapter.mount_prefix, _adapter.subapp)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Cache policy (Exchange 9C): every competition API response is
# Cache-Control: no-store (registry-derived prefixes) so an open tab always
# re-fetches fresh data; the outer wrapper keeps /static/ no-cache and the
# landing page untouched. Simulation endpoints are included — idempotent
# reads that never recompute server state.
asgi_app: ASGIApp = _NoCacheASGI(no_store_for_competition_api(app))

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        prog="python -m web.server",
        description="FOOTBALL web server (port 8080)")
    parser.add_argument(
        "--offline", action="store_true",
        help="Explicit OFFLINE execution mode: equivalent to "
             "FOOTBALL_SNAPSHOT=1 — acquisition wrappers self-gate and "
             "make zero network requests; stored data is served as-is.")
    args = parser.parse_args()
    if args.offline:
        os.environ["FOOTBALL_SNAPSHOT"] = "1"
    uvicorn.run("web.server:asgi_app", host="127.0.0.1", port=8080,
                reload=False)
