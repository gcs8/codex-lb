from __future__ import annotations

import asyncio
import json
import socket as socket_module
from typing import Any

import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from app.core.clients import native_egress, proxy_websocket
from app.core.config.settings import Settings
from app.modules.proxy import service as proxy_service
from app.modules.proxy.load_balancer import AccountSelection
from tests.integration.test_http_responses_bridge import (
    _collect_sse_events,
    _get_account,
    _import_account,
    _install_proxy_settings,
    _make_dashboard_settings,
)
from tests.integration.test_native_websocket_backpressure import helper  # noqa: F401

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.mark.parametrize("path", ["/v1/responses", "/backend-api/codex/responses"])
@pytest.mark.parametrize("count", [64, 65, 129])
@pytest.mark.parametrize("transport", ["http", "websocket"])
async def test_public_http_bridge_preserves_native_burst(async_client, monkeypatch, helper, path, count, transport):  # noqa: F811
    account_id = await _import_account(async_client, "burst-account", "burst@example.test")
    account = await _get_account(account_id)
    frames = [{"type": "response.created", "response": {"id": "burst-response", "status": "in_progress"}}]
    frames.extend(
        {
            "type": "response.output_text.delta",
            "response_id": "burst-response",
            "sequence_number": index,
            "delta": f"chunk:{index}",
        }
        for index in range(count)
    )
    frames.append(
        {
            "type": "response.completed",
            "response": {
                "id": "burst-response",
                "status": "completed",
                "output": [],
                "usage": {"input_tokens": 1, "output_tokens": count, "total_tokens": count + 1},
            },
        }
    )
    barrier = asyncio.Event()
    produced = asyncio.Event()
    full = asyncio.Event()
    enqueue = native_egress.NativeEgressWebSocket._queue_message

    def observe(socket, message):
        enqueue(socket, message)
        if socket._messages.qsize() == 64:
            full.set()

    monkeypatch.setattr(native_egress.NativeEgressWebSocket, "_queue_message", observe)
    receive = native_egress.NativeEgressWebSocket.receive
    paused: set[native_egress.NativeEgressWebSocket] = set()

    async def gated_receive(socket):
        if socket not in paused:
            paused.add(socket)

            async def release():
                if count <= 65:
                    await barrier.wait()
                else:
                    await produced.wait()
                    await full.wait()

            ready = asyncio.create_task(release())
            try:
                await asyncio.wait({ready, socket._pump_task}, return_when=asyncio.FIRST_COMPLETED)
            finally:
                ready.cancel()
                await asyncio.gather(ready, return_exceptions=True)
        return await receive(socket)

    monkeypatch.setattr(native_egress.NativeEgressWebSocket, "receive", gated_receive)

    async def select_account(self, deadline, **kwargs):
        return AccountSelection(account=account, error_message=None, error_code=None)

    async def ensure_fresh(self, target, *, force=False, timeout_seconds):
        return target

    async def origin(websocket: Any):
        command = json.loads(await websocket.recv())
        assert command["model"] == "gpt-5.4"
        assert command["type"] == "response.create"
        for frame in frames:
            await websocket.send(json.dumps(frame))
        produced.set()
        if count <= 65:
            pong = await websocket.ping(b"public-native-read-barrier")
            await pong
            barrier.set()
        await websocket.wait_closed()

    async with serve(origin, "127.0.0.1", 0, ping_interval=None) as server:
        port = server.sockets[0].getsockname()[1]
        settings = Settings(
            upstream_base_url=f"http://127.0.0.1:{port}/backend-api",
            http_responses_session_bridge_enabled=True,
            upstream_websocket_trust_env=False,
        )
        _install_proxy_settings(monkeypatch, app_settings=settings, dashboard_settings=_make_dashboard_settings())
        monkeypatch.setattr(proxy_websocket, "get_settings", lambda: settings)
        monkeypatch.setattr(proxy_websocket, "discover_native_egress_client", lambda: helper)
        monkeypatch.setattr(proxy_service.ProxyService, "_select_account_with_budget", select_account)
        monkeypatch.setattr(proxy_service.ProxyService, "_ensure_fresh_with_budget", ensure_fresh)
        try:
            async with asyncio.timeout(5):
                if transport == "http":
                    events = await _collect_sse_events(
                        async_client, path, json_body={"model": "gpt-5.4", "input": "burst", "stream": True}
                    )
                    assert events == frames
                    assert len(paused) == 1, "public route must consume the actual native socket"
                    assert all(socket._terminal_failure is None for socket in paused)
                else:
                    listener = socket_module.socket()
                    listener.bind(("127.0.0.1", 0))
                    listener.listen()
                    gateway = uvicorn.Server(
                        uvicorn.Config(async_client._transport.app, lifespan="off", log_level="error")
                    )
                    task = asyncio.create_task(gateway.serve(sockets=[listener]))
                    try:
                        while not gateway.started:
                            assert not task.done()
                            await asyncio.sleep(0.001)
                        async with connect(
                            f"ws://127.0.0.1:{listener.getsockname()[1]}{path}", ping_interval=None
                        ) as downstream:
                            await downstream.send(
                                json.dumps({"type": "response.create", "model": "gpt-5.4", "input": "burst"})
                            )
                            events = [json.loads(await downstream.recv()) for _ in frames]
                            # Delivery assertions precede intentional downstream
                            # close and gateway shutdown, not their clean-close
                            # sentinel (which the legacy helper also produces).
                            assert events == frames
                            assert len(paused) == 1, "public route must consume the actual native socket"
                            assert all(socket._terminal_failure is None for socket in paused)
                    finally:
                        gateway.should_exit = True
                        await task
                        listener.close()
                        assert task.done() and task.exception() is None
                        assert listener.fileno() == -1
        finally:
            service = async_client._transport.app.state.proxy_service
            for session in list(service._http_bridge_sessions.values()):
                await service._close_http_bridge_session(session)
                assert session.closed
                assert session.upstream_reader is None
                assert not session.pending_requests
                assert session.resource_close_task is not None and session.resource_close_task.done()
            for socket in paused:
                await socket.close()
                failure = socket._terminal_failure
                assert isinstance(failure, native_egress.NativeEgressTransportError)
                assert (str(failure), failure.failure_phase) in {
                    ("native websocket closed", "websocket_receive"),
                    ("native websocket was closed locally", "cancelled"),
                }
                assert socket._pump_task.done()
                assert socket._pump_task.cancelled() or socket._pump_task.exception() is None
                assert not socket._pending
                assert socket._request_id not in helper._streams
