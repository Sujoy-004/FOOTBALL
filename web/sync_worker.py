"""FastAPI lifespan periodic background sync worker.

SEC-04: Automated 1-hour periodic background sync worker runs inside FastAPI
lifespan to ingest new match results and refresh odds without manual user
intervention.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool

from web.competitions import REGISTRY, consume_lazy_gate

logger = logging.getLogger(__name__)


class SyncWorker:
    """Manages periodic wall-clock background data refresh across all competitions."""

    def __init__(self, interval_seconds: float = 3600.0, tick_seconds: float = 60.0):
        self.interval_seconds = float(interval_seconds)
        self.tick_seconds = float(tick_seconds)
        self.last_sync_timestamp: float = 0.0
        self._lock = asyncio.Lock()
        self._running = False
        self._task: Optional[asyncio.Task] = None

    async def run_sync_all(self, force: bool = False) -> dict[str, Any]:
        """Execute refresh across all registered competitions under mutex lock."""
        if self._lock.locked() and not force:
            return {"status": "skipped", "reason": "sync_in_progress"}

        async with self._lock:
            start_time = time.time()
            results: dict[str, Any] = {}
            logger.info("[sync_worker] Starting sync across registered competitions")

            for adapter in REGISTRY.list():
                try:
                    report = await run_in_threadpool(adapter.refresh)
                    consume_lazy_gate(adapter.id)
                    results[adapter.id] = {
                        "attempted": (report or {}).get("attempted", False),
                        "success": (report or {}).get("success", False),
                        "error": (report or {}).get("error"),
                    }
                except Exception as exc:
                    logger.exception("[sync_worker] Refresh failed for %s", adapter.id)
                    results[adapter.id] = {
                        "attempted": True,
                        "success": False,
                        "error": str(exc),
                    }

            self.last_sync_timestamp = time.time()
            elapsed = round(self.last_sync_timestamp - start_time, 2)
            logger.info("[sync_worker] Sync finished in %ss: %s", elapsed, results)
            return {
                "status": "completed",
                "elapsed_seconds": elapsed,
                "timestamp": self.last_sync_timestamp,
                "results": results,
            }

    async def _loop(self) -> None:
        """Periodic background evaluation loop."""
        while self._running:
            try:
                await asyncio.sleep(self.tick_seconds)
                now = time.time()
                # Run if never synced or interval exceeded
                if self.last_sync_timestamp == 0.0 or (now - self.last_sync_timestamp) >= self.interval_seconds:
                    await self.run_sync_all()
            except asyncio.CancelledError:
                logger.info("[sync_worker] Background sync loop cancelled")
                break
            except Exception:
                logger.exception("[sync_worker] Unexpected error in sync loop")

    def start(self) -> asyncio.Task:
        """Start the background sync task if not already running."""
        if self._task and not self._task.done():
            return self._task
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="periodic_sync_worker")
        return self._task

    async def stop(self) -> None:
        """Gracefully stop and cancel the background sync task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                logger.info("[sync_worker] Shutdown join: background sync task cancelled (expected)")
        self._task = None


# Module-level singleton worker
sync_worker = SyncWorker()
