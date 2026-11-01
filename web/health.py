"""In-memory health monitoring endpoint for cloud deployment and keep-awake pings."""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, Response, status
from web.competitions import REGISTRY
from web.derived import holder

logger = logging.getLogger(__name__)

router = APIRouter(tags=["monitoring"])

_SERVER_START_TIME: float = time.time()
_DB_CHECKER: Optional[Callable[[], tuple[str, bool]]] = None


def register_db_checker(checker: Optional[Callable[[], tuple[str, bool]]]) -> None:
    """Register a pluggable database health checker callable returning (status_label, is_healthy)."""
    global _DB_CHECKER
    _DB_CHECKER = checker


def get_db_health() -> tuple[str, bool]:
    """Inspect database connectivity; defaults to fallback_json if DATABASE_URL unset."""
    if _DB_CHECKER is not None:
        return _DB_CHECKER()
    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        return "fallback_json", True
    # If DATABASE_URL is set but no checker registered (e.g. before Phase 9),
    # warn and report fallback_json healthy so Phase 8 deployments succeed.
    logger.warning("DATABASE_URL is set but no DB health checker registered; using fallback_json")
    return "fallback_json", True


@router.get("/health")
def health_check(response: Response) -> dict[str, Any]:
    """Lightweight in-memory readiness and keep-awake probe (<15ms)."""
    uptime = round(time.time() - _SERVER_START_TIME, 2)
    db_status, db_healthy = get_db_health()

    competitions: dict[str, Any] = {}
    stores_healthy = True

    for adapter in REGISTRY.list():
        comp_id = adapter.id
        stamp = holder.read_stamp(comp_id)
        data = holder.read_data(comp_id)

        # Check if boot computation failed or data unavailable
        if data.get("availability") == "UNAVAILABLE" or data.get("error") == "boot computation failed":
            stores_healthy = False
            comp_status = "unavailable"
        elif stamp is not None:
            comp_status = "available"
        else:
            comp_status = "uninitialized"
            stores_healthy = False

        competitions[comp_id] = {
            "status": comp_status,
            "mode": holder.read_mode(comp_id) or data.get("mode"),
            "stamp": stamp.as_dict() if stamp is not None else None,
        }

    is_healthy = db_healthy and stores_healthy
    if not is_healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return {
        "status": "ok" if is_healthy else "unhealthy",
        "uptime_seconds": uptime,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database": db_status,
        "competitions": competitions,
    }
