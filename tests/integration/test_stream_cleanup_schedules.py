from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

import pytest
from aiohttp import web
from sqlalchemy import select

import app.core.utils.sse as sse
from app.core.utils.shared_future import wait_on_shared_future
from app.core.utils.sse import format_sse_event
from app.db.models import (
    Account,
    AccountStatus,
    ApiKeyLimit,
    ApiKeyUsageReservation,
    ApiKeyUsageReservationItem,
    RequestLog,
)
from app.db.session import SessionLocal
from tests.integration.test_stream_wrapper_lease import _setup

pytestmark = pytest.mark.integration


class _StreamPhase(TypedDict, total=False):
    mode: str
    requests: int
    arrived: asyncio.Event
    finish: asyncio.Event
    server_done: asyncio.Event
    disconnect: asyncio.Event
    cleanup_started: asyncio.Event
    cleanup_release: asyncio.Event
    delta_sent: bool
    heartbeat_for_read: bool


@asynccontextmanager
async def _blocked_upstream(phase: _StreamPhase) -> AsyncIterator[str]:
    async def respond(request):
        await request.json()
        phase["requests"] += 1
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        phase["arrived"].set()
        try:
            if phase["mode"] == "gap":
                await phase["finish"].wait()
            else:
                for event in [
                    {
                        "type": "response.created",
                        "response": {"id": f"resp_schedule_{phase['requests']}", "status": "in_progress", "output": []},
                    },
                    {"type": "response.output_text.delta", "delta": "partial"},
                ]:
                    await response.write(format_sse_event(event).encode())
                await phase["finish"].wait()
        finally:
            phase["server_done"].set()
        return response

    app = web.Application()
    app.router.add_post("/backend-api/codex/responses", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}/backend-api"
    finally:
        phase["finish"].set()
        await runner.cleanup()


async def _assert_released(service, account_id: str, streams: list, count: int) -> None:
    # No test-owned aclose and no collection: retained real owners must already be dead.
    assert len(streams) == count
    assert all(stream.ag_frame is None for stream in streams)
    assert await service._load_balancer.account_pressure_snapshot(account_id) == (0, 0, 0.0)
    assert await service.drain_persistence_tasks(timeout_seconds=5)
    async with SessionLocal() as session:
        reservations = list((await session.scalars(select(ApiKeyUsageReservation))).all())
        items = list((await session.scalars(select(ApiKeyUsageReservationItem))).all())
        limits = list((await session.scalars(select(ApiKeyLimit))).all())
        logs = list((await session.scalars(select(RequestLog))).all())
        account = await session.get(Account, account_id)
    assert len(reservations) == len(items) == len(logs) == count
    assert all(row.status == "released" for row in reservations)
    assert all((row.input_tokens, row.output_tokens) == (None, None) for row in reservations)
    assert all(item.actual_delta == 0 for item in items)
    assert len(limits) == 1 and limits[0].current_value == 0
    assert all(
        (log.status, log.error_code, log.input_tokens, log.output_tokens)
        == ("cancelled", "client_disconnected", None, None)
        for log in logs
    )
    assert all(log.account_id == account_id for log in logs)
    assert account is not None and account.status == AccountStatus.ACTIVE


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize("mode", ["gap", "mid-read", "repeated-cancel"])
async def test_real_asgi_disconnect_drains_retained_retry_and_exact_reservation(
    async_client,
    app_instance,
    monkeypatch,
    path,
    mode,
):
    phase: _StreamPhase = {"mode": mode, "requests": 0}
    for name in ("arrived", "finish", "server_done", "disconnect", "cleanup_started", "cleanup_release"):
        phase[name] = asyncio.Event()
    phase["delta_sent"] = False
    phase["heartbeat_for_read"] = False
    original_wait = wait_on_shared_future

    async def causal_keepalive(shared, *, timeout=None, **kwargs):
        if mode == "gap" and not phase["heartbeat_for_read"]:
            await asyncio.wait_for(phase["arrived"].wait(), timeout=3)
            phase["heartbeat_for_read"] = True
            raise TimeoutError
        if phase["delta_sent"] and not phase["heartbeat_for_read"]:
            phase["heartbeat_for_read"] = True
            raise TimeoutError
        return await original_wait(shared, timeout=timeout, **kwargs)

    monkeypatch.setattr(sse, "wait_on_shared_future", causal_keepalive)
    async with _blocked_upstream(phase) as upstream:
        service, account_id, headers, streams = await _setup(async_client, app_instance, monkeypatch, upstream)
        original_release = service._load_balancer.release_account_lease

        async def delayed_release(lease):
            if mode == "repeated-cancel" and phase["disconnect"].is_set():
                phase["cleanup_started"].set()
                await phase["cleanup_release"].wait()
            return await original_release(lease)

        monkeypatch.setattr(service._load_balancer, "release_account_lease", delayed_release)
        for index in range(9):
            for name in ("arrived", "finish", "server_done", "disconnect", "cleanup_started", "cleanup_release"):
                phase[name] = asyncio.Event()
            phase["delta_sent"] = False
            phase["heartbeat_for_read"] = False
            body_sent = False
            body = json.dumps({"model": "gpt-5.1", "instructions": "fixture", "input": [], "stream": True}).encode()
            chunks = []

            async def receive():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await phase["disconnect"].wait()
                if mode == "repeated-cancel":
                    await asyncio.Event().wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] != "http.response.body":
                    return
                chunk = message.get("body", b"")
                chunks.append(chunk)
                if b"response.output_text.delta" in chunk:
                    phase["delta_sent"] = True
                heartbeat = chunk.startswith(b":") or b"codex.keepalive" in chunk
                if heartbeat and (mode == "gap" or phase["heartbeat_for_read"]):
                    await asyncio.wait_for(phase["arrived"].wait(), timeout=3)
                    phase["disconnect"].set()
                    if mode == "repeated-cancel":
                        await asyncio.Event().wait()

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.0"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": path,
                "raw_path": path.encode(),
                "query_string": b"",
                "root_path": "",
                "headers": [
                    (b"host", b"testserver"),
                    (b"content-type", b"application/json"),
                    *[(key.encode(), value.encode()) for key, value in headers.items()],
                ],
                "client": ("127.0.0.1", 12345),
                "server": ("testserver", 80),
            }
            task = asyncio.create_task(app_instance(scope, receive, send))
            if mode == "repeated-cancel":
                await asyncio.wait_for(phase["disconnect"].wait(), timeout=5)
                task.cancel()
                await asyncio.wait_for(phase["cleanup_started"].wait(), timeout=3)
                task.cancel()
                phase["cleanup_release"].set()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=5)
            else:
                await asyncio.wait_for(task, timeout=5)
            assert chunks
            if mode == "gap":
                assert chunks[-1].startswith(b":") or b"codex.keepalive" in chunks[-1]
            if mode != "gap":
                assert phase["delta_sent"] and phase["heartbeat_for_read"]
            assert phase["requests"] == index + 1
            await _assert_released(service, account_id, streams, index + 1)
            phase["finish"].set()
            await asyncio.wait_for(phase["server_done"].wait(), timeout=3)
        # Request nine proves admission remains possible after eight prior closes.
        assert not [task for task in service._background_cleanup_tasks if not task.done()]


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
async def test_send_cancellation_must_enter_wrapper_cleanup(async_client, app_instance, monkeypatch, path):
    phase: _StreamPhase = {"mode": "mid-read", "requests": 0}
    for name in ("arrived", "finish", "server_done"):
        phase[name] = asyncio.Event()
    delta_sent = False
    heartbeat_due = False
    send_blocked = asyncio.Event()

    async def causal_wait(shared, *, timeout=None, **kwargs):
        nonlocal heartbeat_due
        if delta_sent and not heartbeat_due:
            heartbeat_due = True
            raise TimeoutError
        return await wait_on_shared_future(shared, timeout=timeout, **kwargs)

    monkeypatch.setattr(sse, "wait_on_shared_future", causal_wait)
    async with _blocked_upstream(phase) as upstream:
        service, account_id, headers, streams = await _setup(async_client, app_instance, monkeypatch, upstream)
        body = json.dumps({"model": "gpt-5.1", "instructions": "fixture", "input": [], "stream": True}).encode()
        sent_request = False
        responses = []
        original_init = __import__(
            "app.modules.proxy.api", fromlist=["DeliveryTracedStreamingResponse"]
        ).DeliveryTracedStreamingResponse.__init__

        def record_response(self, *args, **kwargs):
            original_init(self, *args, **kwargs)
            responses.append(self)

        monkeypatch.setattr("app.modules.proxy.api.DeliveryTracedStreamingResponse.__init__", record_response)

        async def receive():
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            nonlocal delta_sent
            chunk = message.get("body", b"")
            if b"response.output_text.delta" in chunk:
                delta_sent = True
            if heartbeat_due and (chunk.startswith(b":") or b"codex.keepalive" in chunk):
                send_blocked.set()
                await asyncio.Event().wait()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"host", b"testserver"),
                (b"content-type", b"application/json"),
                *[(key.encode(), value.encode()) for key, value in headers.items()],
            ],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
        }
        task = asyncio.create_task(app_instance(scope, receive, send))
        await asyncio.wait_for(send_blocked.wait(), timeout=5)
        assert delta_sent and heartbeat_due
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=3)
        pressure = await service._load_balancer.account_pressure_snapshot(account_id)
        observation = {
            "path": path,
            "outer_task_done": task.done(),
            "outer_task_cancelled": task.cancelled(),
            "retained_retry_count": len(streams),
            "retry_frames_closed": [stream.ag_frame is None for stream in streams],
            "response_wrapper_closed": [response.body_iterator.ag_frame is None for response in responses],
            "account_pressure": pressure,
        }
        assert all(stream.ag_frame is None for stream in streams) and pressure == (0, 0, 0.0), json.dumps(
            observation, sort_keys=True
        )
