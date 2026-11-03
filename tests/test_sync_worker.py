"""Tests for web.sync_worker.SyncWorker and lifespan background sync integration.

Covers SEC-04:
- Periodic background evaluation loop
- Wall-clock elapsed time checking
- Mutex lock via asyncio.Lock preventing overlapping sync runs
- Threadpool delegation for adapter.refresh()
- Error isolation across competitions
- Graceful cancellation on lifespan shutdown
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.testclient import TestClient

from web.competitions import CompetitionAdapter, CompetitionRegistry, reset_lazy_gates
from web.sync_worker import SyncWorker


@pytest.fixture(autouse=True)
def clean_lazy_gates():
    reset_lazy_gates()
    yield
    reset_lazy_gates()


@pytest.mark.asyncio
async def test_run_sync_all_success():
    """SyncWorker.run_sync_all() iterates through registered competitions,

    delegates refresh to thread pool, consumes lazy gates, and records results.
    """
    mock_adapter1 = MagicMock(spec=CompetitionAdapter)
    mock_adapter1.id = "comp1"
    mock_adapter1.refresh.return_value = {"attempted": True, "success": True, "error": None}

    mock_adapter2 = MagicMock(spec=CompetitionAdapter)
    mock_adapter2.id = "comp2"
    mock_adapter2.refresh.return_value = {"attempted": True, "success": True, "error": None}

    mock_registry = MagicMock(spec=CompetitionRegistry)
    mock_registry.list.return_value = [mock_adapter1, mock_adapter2]

    worker = SyncWorker(interval_seconds=3600.0, tick_seconds=1.0)

    with patch("web.sync_worker.REGISTRY", mock_registry):
        result = await worker.run_sync_all()

    assert result["status"] == "completed"
    assert "elapsed_seconds" in result
    assert result["timestamp"] > 0
    assert result["results"]["comp1"]["success"] is True
    assert result["results"]["comp2"]["success"] is True
    assert mock_adapter1.refresh.called
    assert mock_adapter2.refresh.called


@pytest.mark.asyncio
async def test_run_sync_all_error_isolation():
    """An error in one competition refresh does not halt other competition refreshes."""
    mock_adapter1 = MagicMock(spec=CompetitionAdapter)
    mock_adapter1.id = "comp1"
    mock_adapter1.refresh.side_effect = RuntimeError("Provider down")

    mock_adapter2 = MagicMock(spec=CompetitionAdapter)
    mock_adapter2.id = "comp2"
    mock_adapter2.refresh.return_value = {"attempted": True, "success": True, "error": None}

    mock_registry = MagicMock(spec=CompetitionRegistry)
    mock_registry.list.return_value = [mock_adapter1, mock_adapter2]

    worker = SyncWorker()

    with patch("web.sync_worker.REGISTRY", mock_registry):
        result = await worker.run_sync_all()

    assert result["status"] == "completed"
    assert result["results"]["comp1"]["success"] is False
    assert "Provider down" in result["results"]["comp1"]["error"]
    assert result["results"]["comp2"]["success"] is True


@pytest.mark.asyncio
async def test_run_sync_all_mutex_locking():
    """When lock is held and force=False, returns skipped immediately without blocking."""
    worker = SyncWorker()
    await worker._lock.acquire()

    try:
        result = await worker.run_sync_all(force=False)
        assert result["status"] == "skipped"
        assert result["reason"] == "sync_in_progress"
    finally:
        worker._lock.release()


@pytest.mark.asyncio
async def test_loop_periodic_execution():
    """Background loop triggers sync when wall-clock threshold is met."""
    worker = SyncWorker(interval_seconds=0.1, tick_seconds=0.01)

    sync_calls = 0

    async def fake_sync(*args, **kwargs):
        nonlocal sync_calls
        sync_calls += 1
        worker.last_sync_timestamp = time.time()
        return {"status": "completed"}

    worker.run_sync_all = fake_sync

    worker.start()
    await asyncio.sleep(0.05)  # Initial run triggers
    assert sync_calls >= 1

    initial_count = sync_calls
    await asyncio.sleep(0.15)  # Interval exceeded, triggers again
    assert sync_calls > initial_count

    await worker.stop()


@pytest.mark.asyncio
async def test_stop_cancels_cleanly():
    """Stopping SyncWorker cancels the background task without unhandled exceptions."""
    worker = SyncWorker(interval_seconds=3600.0, tick_seconds=0.05)
    task = worker.start()

    assert not task.done()
    assert worker._running is True

    await worker.stop()

    assert worker._running is False
    assert task.done()
    assert worker._task is None


def test_server_lifespan_sync_worker_integration():
    """FastAPI server lifespan starts SyncWorker on boot and stops it on shutdown."""
    from web.server import app

    with patch("web.sync_worker.sync_worker.start") as mock_start, \
         patch("web.sync_worker.sync_worker.stop", new_callable=AsyncMock) as mock_stop:
        with TestClient(app) as client:
            mock_start.assert_called_once()
            res = client.get("/health")
            assert res.status_code == 200

        mock_stop.assert_awaited_once()
