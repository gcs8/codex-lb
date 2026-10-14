from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.main import run_http_bridge_durable_ownership_maintenance, run_http_bridge_idle_sweep_maintenance
from app.modules.proxy.ring_lifecycle import BridgeRingPeriodicLifecycle

pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_heartbeat_maintenance_runs_all_bridge_passes() -> None:
    """Retain all three passes from the former combined maintenance regression."""
    service = SimpleNamespace(
        reconcile_durable_http_bridge_ownership=AsyncMock(return_value=0),
        abandon_stale_http_bridge_operations=AsyncMock(return_value=0),
        prune_idle_http_bridge_sessions=AsyncMock(return_value=0),
    )
    await run_http_bridge_durable_ownership_maintenance(service)
    await run_http_bridge_idle_sweep_maintenance(service)
    service.reconcile_durable_http_bridge_ownership.assert_awaited_once()
    service.abandon_stale_http_bridge_operations.assert_awaited_once()
    service.prune_idle_http_bridge_sessions.assert_awaited_once()


@pytest.mark.asyncio
async def test_heartbeat_maintenance_isolates_a_failing_pass() -> None:
    """A failed reconciliation cannot suppress stale cleanup, idle sweep or renewal."""
    service = SimpleNamespace(
        reconcile_durable_http_bridge_ownership=AsyncMock(side_effect=RuntimeError("durable read failed")),
        abandon_stale_http_bridge_operations=AsyncMock(return_value=0),
        prune_idle_http_bridge_sessions=AsyncMock(return_value=0),
    )
    heartbeat = AsyncMock()
    lifecycle = BridgeRingPeriodicLifecycle(
        heartbeat=heartbeat,
        durable_ownership=lambda: run_http_bridge_durable_ownership_maintenance(service),
        idle_sweep=lambda: run_http_bridge_idle_sweep_maintenance(service),
        cap_partition=AsyncMock(),
        interval_seconds=0.01,
        heartbeat_deadline_seconds=0.5,
        maintenance_deadline_seconds=0.5,
        restart_delay_seconds=0.01,
    )
    lifecycle.start()
    try:
        async with asyncio.timeout(2):
            while not (
                service.abandon_stale_http_bridge_operations.await_count >= 2
                and service.prune_idle_http_bridge_sessions.await_count >= 2
                and heartbeat.await_count >= 2
            ):
                await asyncio.sleep(0)
    finally:
        stopped = await lifecycle.stop(timeout_seconds=1)
    assert stopped.all_stopped
    assert all(phase.phase_task is None for phase in lifecycle.phases)


@pytest.mark.asyncio
async def test_heartbeat_maintenance_tolerates_a_missing_service_or_pass() -> None:
    for service in (None, SimpleNamespace()):
        await run_http_bridge_durable_ownership_maintenance(service)
        await run_http_bridge_idle_sweep_maintenance(service)
