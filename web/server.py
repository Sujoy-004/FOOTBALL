"""Unified FOOTBALL web app — single FastAPI on port 8080.

Mounts competition sub-apps under /worldcup and /ucl.
Serves the SPA shell from /static and the landing page at /.
"""

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

mimetypes.add_type('image/webp', '.webp')

import fastapi
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

from web.competitions import REGISTRY


HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    from web.startup import apply_session_overrides, run_startup_flow

    # Interactive live-vs-snapshot decision (never prompts without a TTY).
    decision = run_startup_flow()
    if decision.fdo_key:
        apply_session_overrides(decision.fdo_key)

    import web.wc_app as _wc
    import web.ucl_app as _ucl

    # Each app's fetch wrapper self-gates on snapshot mode: calling it
    # unconditionally records a truthful skipped/snapshot report (zero
    # network in snapshot) instead of leaving the refresh ledger empty.
    _wc._fetch_live_data()
    _wc.cache = _wc.compute_overview()

    _ucl._fetch_live_data()
    # Route through compute_all so every on-disk state gets the truthful
    # boot: real results -> results view; no/partial results -> honest
    # simulation-available view (never an empty cache).
    try:
        _ucl.cache = _ucl.compute_all()
    except Exception as e:
        logger.error("[UCL] compute_all failed: %s", e)
        _ucl.cache = {}
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


asgi_app: ASGIApp = _NoCacheASGI(app)

if __name__ == "__main__":
    uvicorn.run("web.server:asgi_app", host="127.0.0.1", port=8080, reload=False)
