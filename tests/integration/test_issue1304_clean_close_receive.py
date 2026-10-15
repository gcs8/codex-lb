"""Public wire reproduction of cancellation-sensitive downstream ingress.

The ASGI boundary pauses only after the real socket receive dequeues turn two.
This models an adapter suspension point, not the proxy or upstream transport.
No production coordinator is replaced. The committed predecessor's public RED
is retained in the lane evidence; this fixture also qualifies the receive owner.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
import uvicorn
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from app.core.clients.native_egress import NativeWebSocketRequest, SubprocessNativeEgressClient
from app.core.clients.proxy_websocket import NativeUpstreamWebSocket
from app.core.clock import RealScheduler
from app.dependencies import get_proxy_service_for_app
from app.modules.proxy import api as proxy_api
from app.modules.proxy import service as proxy_service
from tests.integration.test_proxy_websocket_responses import _websocket_settings

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize("ordering", ["close_before_poll", "poll_before_close"])
async def test_queued_create_survives_clean_close_and_poll(
    app_instance, monkeypatch, path: str, ordering: str, record_property
) -> None:
    binary = os.environ.get("CODEX_LB_NATIVE_EGRESS_TEST_BINARY")
    assert binary, "qualify the unchanged helper inputs before this wire regression"
    queued = asyncio.Event()
    release_frame = asyncio.Event()
    poll_elapsed = asyncio.Event()
    clean_observed = asyncio.Event()
    ready = asyncio.Event()
    downstream_exited = asyncio.Event()
    ingress: list[str] = []
    returned: list[str] = []
    cancelled: list[str] = []
    upstream_frames: list[list[dict[str, Any]]] = []
    owners: list[str] = []
    operation_order: list[str] = []
    active_receives = 0
    peak_receives = 0

    class ObservedScheduler(RealScheduler):
        async def wait_for(self, fut, timeout):
            is_receive = getattr(fut, "__qualname__", "") == "WebSocket.receive"
            try:
                return await asyncio.wait_for(fut, timeout)
            except TimeoutError:
                if is_receive and queued.is_set():
                    operation_order.append("poll_timeout")
                    poll_elapsed.set()
                raise

        async def wait(self, fs, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            result = await asyncio.wait(fs, timeout=timeout, return_when=return_when)
            if not result[0] and queued.is_set():
                operation_order.append("poll_timeout")
                poll_elapsed.set()
            return result

    class ReceiveBarrier:
        async def __call__(self, scope, receive, send):
            nonlocal active_receives, peak_receives
            if scope["type"] != "websocket":
                return await app_instance(scope, receive, send)

            async def owned_receive():
                nonlocal active_receives, peak_receives
                active_receives += 1
                peak_receives = max(peak_receives, active_receives)
                frame = None
                try:
                    frame = await receive()
                    text = frame.get("text")
                    if frame["type"] == "websocket.receive" and text is not None:
                        ingress.append(text)
                        if json.loads(text)["input"][0]["content"] == "fixture:second":
                            operation_order.append("second_dequeued")
                            queued.set()
                            await asyncio.wait_for(release_frame.wait(), timeout=5)
                        returned.append(text)
                    return frame
                except asyncio.CancelledError:
                    if frame is not None and frame.get("text"):
                        operation_order.append("receive_cancelled_after_dequeue")
                        cancelled.append(frame["text"])
                    raise
                finally:
                    active_receives -= 1

            try:
                await app_instance(scope, owned_receive, send)
            finally:
                downstream_exited.set()

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    class ObservedNative(NativeUpstreamWebSocket):
        async def receive(self):
            message = await super().receive()
            if message.kind == "close":
                assert message.close_code == 1000
                operation_order.append("clean_close_received")
                clean_observed.set()
            return message

    async def peer(websocket):
        frames: list[dict[str, Any]] = []
        upstream_frames.append(frames)
        generation = len(upstream_frames)
        async for text in websocket:
            payload = json.loads(text)
            frames.append(payload)
            response_id = "resp_fixture_first" if generation == 1 else "resp_fixture_second"
            for event_type, status in (("response.created", "in_progress"), ("response.completed", "completed")):
                await websocket.send(
                    json.dumps(
                        {
                            "type": event_type,
                            "response": {
                                "id": response_id,
                                "status": status,
                                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                            },
                        }
                    )
                )
            if generation == 1:
                await asyncio.wait_for(queued.wait(), timeout=5)
                if ordering == "poll_before_close":
                    await asyncio.wait_for(poll_elapsed.wait(), timeout=5)
                operation_order.append("upstream_close_started")
                await websocket.close(code=1000)
                return

    service = get_proxy_service_for_app(app_instance)
    monkeypatch.setattr(service, "_scheduler", ObservedScheduler())
    health = AsyncMock()
    logs = AsyncMock()
    monkeypatch.setattr(service, "_handle_stream_error", health)
    monkeypatch.setattr(service, "_write_request_log", logs)
    monkeypatch.setattr(proxy_api, "_websocket_firewall_denial_response", AsyncMock(return_value=None))
    monkeypatch.setattr(proxy_api, "validate_proxy_api_key_authorization", AsyncMock(return_value=None))
    monkeypatch.setattr(proxy_api, "_websocket_upstream_transport_denial", AsyncMock(return_value=None))
    monkeypatch.setattr(proxy_service, "_DOWNSTREAM_WEBSOCKET_RECEIVE_POLL_SECONDS", 0.05)
    monkeypatch.setattr(
        proxy_service, "get_settings_cache", lambda: SimpleNamespace(get=AsyncMock(return_value=_websocket_settings()))
    )
    native = SubprocessNativeEgressClient(Path(binary))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = ReadyServer(uvicorn.Config(ReceiveBarrier(), lifespan="off", log_config=None, access_log=False))
    server_task = None
    try:
        async with serve(peer, "127.0.0.1", 0, close_timeout=1) as upstream:
            port = upstream.sockets[0].getsockname()[1]

            async def connect_upstream(*_args, **_kwargs):
                owners.append("fixture-account")
                websocket = await native.websocket(
                    NativeWebSocketRequest(
                        url=f"ws://127.0.0.1:{port}/responses",
                        headers={},
                        connect_timeout_seconds=2,
                        max_message_bytes=65536,
                        interpret_responses=True,
                    )
                )
                return SimpleNamespace(id="fixture-account"), ObservedNative(websocket)

            monkeypatch.setattr(service, "_connect_proxy_websocket", connect_upstream)
            server_task = asyncio.create_task(server._serve(sockets=[listener]))
            async with asyncio.timeout(5):
                await ready.wait()
            async with connect(
                f"ws://127.0.0.1:{listener.getsockname()[1]}{path}", proxy=None, close_timeout=1
            ) as downstream:

                def body(text):
                    return {
                        "type": "response.create",
                        "model": "gpt-5.4",
                        "instructions": "",
                        "input": [{"role": "user", "content": text}],
                        "stream": True,
                    }

                await downstream.send(json.dumps(body("fixture:first")))
                async with asyncio.timeout(5):
                    first = [json.loads(await downstream.recv()) for _ in range(2)]
                assert [e["type"] for e in first] == ["response.created", "response.completed"]
                await downstream.send(json.dumps(body("fixture:second")))
                async with asyncio.timeout(5):
                    await queued.wait()
                    await clean_observed.wait()
                    await poll_elapsed.wait()
                release_frame.set()
                if ordering == "close_before_poll":
                    assert operation_order.index("clean_close_received") < operation_order.index("poll_timeout")
                else:
                    assert operation_order.index("poll_timeout") < operation_order.index("upstream_close_started")
                # Assert the loss at its actual consumer boundary before a
                # later receive timeout can obscure the missing-frame cause.
                assert not cancelled, "poll cancelled an ASGI receive after it consumed turn two"
                async with asyncio.timeout(5):
                    second = [json.loads(await downstream.recv()) for _ in range(2)]
                assert [e["type"] for e in second] == ["response.created", "response.completed"]
                assert second[-1]["response"]["id"] == "resp_fixture_second"
                assert ingress == returned
                assert len(ingress) == 2
                assert peak_receives == 1
                assert [len(frames) for frames in upstream_frames] == [1, 1]
                assert upstream_frames[1][0]["input"] == body("fixture:second")["input"]
                assert "previous_response_id" not in upstream_frames[1][0]
                assert owners == ["fixture-account", "fixture-account"]
                health.assert_not_awaited()
        await service.drain_persistence_tasks(timeout_seconds=5)
        assert logs.await_count == 2
    finally:
        release_frame.set()
        # Release upstream barriers even when an ingress assertion fails.
        queued.set()
        poll_elapsed.set()
        server.should_exit = True
        if server_task is not None:
            try:
                await asyncio.wait_for(server_task, timeout=5)
            finally:
                if not server_task.done():
                    server_task.cancel()
                    await asyncio.gather(server_task, return_exceptions=True)
        listener.close()
        native_process = native._process
        await native.aclose()
        assert native_process is not None and native_process.returncode is not None
        record_property(
            "wire_evidence",
            json.dumps(
                {
                    "ordering": ordering,
                    "path": path,
                    "ingress": len(ingress),
                    "returned": len(returned),
                    "cancelled_after_dequeue": len(cancelled),
                    "upstream_dispatch_counts": [len(frames) for frames in upstream_frames],
                    "owners": owners,
                    "operation_order": operation_order,
                    "native_exit_code": native_process.returncode,
                    "peak_receives": peak_receives,
                    "active_receives_after_cleanup": active_receives,
                    "downstream_exited": downstream_exited.is_set(),
                }
            ),
        )
        assert active_receives == 0
        if server_task is not None:
            assert server_task.done()
