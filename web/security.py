"""Security hardening utilities: logging filter, CORS origin parsing, and error shielding.

SEC-01: API keys and credentials stay server-side.
SEC-02: Logs and error payloads are sanitized against secret leaks.
SEC-03: CORS restricts browser access to authorized origins and Cloudflare Pages.
"""

from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from football_core.domain import redact_secrets

logger = logging.getLogger(__name__)


class SecretRedactingFilter(logging.Filter):
    """Logging filter that scrubs credentials from log records and tracebacks."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(v) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(v) if isinstance(v, str) else v
                    for v in record.args
                )
            elif isinstance(record.args, list):
                record.args = [
                    redact_secrets(v) if isinstance(v, str) else v
                    for v in record.args
                ]

        # Format and redact tracebacks so secrets in exception arguments don't leak
        if record.exc_info and not record.exc_text:
            formatted = logging.Formatter().formatException(record.exc_info)
            record.exc_text = redact_secrets(formatted)
            record.exc_info = None
        elif record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)

        return True


def install_logging_filters() -> None:
    """Attach SecretRedactingFilter to root, uvicorn, football_core, and web loggers."""
    f = SecretRedactingFilter()
    root = logging.getLogger()
    root.addFilter(f)
    for h in root.handlers:
        h.addFilter(f)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "football_core", "web"):
        l = logging.getLogger(name)
        l.addFilter(f)
        for h in l.handlers:
            h.addFilter(f)


def get_allowed_origins() -> list[str]:
    """Parse ALLOWED_ORIGINS env var combined with standard localhost defaults."""
    defaults = [
        "http://localhost:8080",
        "http://localhost:3000",
        "http://127.0.0.1:8080",
        "http://127.0.0.1:3000",
    ]
    env_origins_str = os.environ.get("ALLOWED_ORIGINS", "").strip()
    origins: list[str] = []
    if env_origins_str:
        for item in env_origins_str.split(","):
            cleaned = item.strip()
            if cleaned and cleaned not in origins:
                origins.append(cleaned)
    for d in defaults:
        if d not in origins:
            origins.append(d)
    return origins


def register_exception_handlers(app: FastAPI) -> None:
    """Register unified JSON exception handlers shielding internal details and scrubbing secrets."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        detail = redact_secrets(str(exc.detail))
        return JSONResponse({"error": detail, "detail": detail}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception):
        logger.error("Unhandled exception on %s: %s", request.url.path, redact_secrets(str(exc)))
        return JSONResponse({"error": f"internal error: {exc.__class__.__name__}"}, status_code=500)
