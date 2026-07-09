"""Unified FOOTBALL web app — single FastAPI on port 8080.

Mounts competition sub-apps under /worldcup and /ucl.
Serves the SPA shell from /static and the landing page at /.
"""

from contextlib import asynccontextmanager
from pathlib import Path

import fastapi
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

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


if __name__ == "__main__":
    uvicorn.run("web.server:app", host="127.0.0.1", port=8080, reload=False)
