"""Unified FOOTBALL web app — single FastAPI on port 8080.

Mounts competition sub-apps under /worldcup and /ucl.
Serves the SPA shell from /static and the landing page at /.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import fastapi
from fastapi.responses import HTMLResponse, JSONResponse
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

from web.wc_app import wc_app
from web.ucl_app import ucl_app


HERE = Path(__file__).parent
STATIC_DIR = HERE / "static"


@asynccontextmanager
async def lifespan(app: fastapi.FastAPI):
    import web.wc_app as _wc
    import web.ucl_app as _ucl
    _wc.cache = _wc.compute_or_load()
    try:
        _ucl.cache = _ucl.compute_all()
    except Exception as e:
        print(f"[UCL] compute_all failed: {e}")
        _ucl.cache = {}
    yield


app = fastapi.FastAPI(title="FOOTBALL", lifespan=lifespan)


@app.get("/")
def landing():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(html)


@app.get("/euro")
def euro_stub():
    return JSONResponse({"status": "coming_soon", "message": "Euro 2028 coming soon."})


app.mount("/worldcup", wc_app)
app.mount("/ucl", ucl_app)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


asgi_app: ASGIApp = _NoCacheASGI(app)

if __name__ == "__main__":
    uvicorn.run("web.server:asgi_app", host="127.0.0.1", port=8080, reload=False)
