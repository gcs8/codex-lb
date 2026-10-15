"""Issue 2538 composition on real Rust HTTP/WS producers and public routes.

Only the upstream peer is synthetic. Native response objects and IPC events are
never fabricated. Existing maintained modules cover malformed-frame policies.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import socket
import time
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
import uvicorn
from sqlalchemy import select
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from app.core.clients import proxy as client_proxy
from app.core.clients import proxy_websocket
from app.core.clients.native_egress import SubprocessNativeEgressClient
from app.core.clients.proxy import CODEX_RESPONSES_LITE_WEBSOCKET_METADATA_KEY as LITE_MARKER
from app.core.clock import REAL_CLOCK, REAL_SCHEDULER
from app.core.openai.requests import ResponsesRequest
from app.core.utils.sse import parse_sse_data_json
from app.db.models import ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.api_keys.service import ApiKeysService
from app.modules.proxy import service as proxy_service
from app.modules.proxy.load_balancer import AccountSelection
from tests.integration.test_http_responses_bridge import (
    _cleanup_http_bridge_sessions,  # noqa: F401
    _get_account,
    _import_account,
    _install_proxy_settings,
    _make_app_settings,
    _make_dashboard_settings,
)
from tests.integration.test_native_sse_egress import (
    _finish_chunks,
    _serve_http,
    _start_chunked_response,
    _write_chunk,
)
from tests.simulation.virtual_time import VirtualClock, VirtualScheduler

pytestmark = pytest.mark.integration


@pytest.fixture
async def native_worker(app_instance, record_property):
    binary = os.environ.get("CODEX_LB_NATIVE_EGRESS_TEST_BINARY")
    if not binary:
        pytest.skip("set CODEX_LB_NATIVE_EGRESS_TEST_BINARY for real native issue2538 probes")
    client = SubprocessNativeEgressClient(Path(binary))
    client.request = AsyncMock(wraps=client.request)
    client.websocket = AsyncMock(wraps=client.websocket)
    try:
        yield client
    finally:
        service = get_proxy_service_for_app(app_instance)
        # Failure cleanup cannot wait for virtual timers that the failed call
        # can no longer advance. Call assertions remain authoritative.
        owned_scheduler = service._scheduler
        service._clock, service._scheduler = REAL_CLOCK, REAL_SCHEDULER
        for session in tuple(service._http_bridge_sessions.values()):
            await service._close_http_bridge_session(session)
        if isinstance(owned_scheduler, VirtualScheduler):
            await owned_scheduler.cancel_owned_tasks()
            assert all(task.done() for task in owned_scheduler.owned_tasks)
        process, reader = client._process, client._reader_task
        await client.aclose()
        assert process is None or process.returncode is not None
        assert reader is None or reader.done()
        assert not client._streams
        record_property("real_native_http_dispatches", client.request.await_count)
        record_property("real_native_websocket_connections", client.websocket.await_count)
        record_property("native_child_reaped", process is not None and process.returncode is not None)


ERROR = {
    "code": "unsupported_value",
    "type": "invalid_request_error",
    "param": "parallel_tool_calls",
    "message": "X-OpenAI-Internal-Codex-Responses-Lite requires `parallel_tool_calls` to be false.",
}
CREATED = {
    "type": "response.created",
    "response": {"id": "resp_issue2538", "object": "response", "status": "in_progress"},
}
DELTA = {"type": "response.output_text.delta", "delta": "visible", "output_index": 0, "content_index": 0}
COMPLETED = {
    "type": "response.completed",
    "response": {"id": "resp_issue2538_next", "object": "response", "status": "completed", "output": []},
}


def _body(lite: bool = True) -> dict:
    items = [{"role": "user", "content": "issue2538 synthetic request"}]
    if lite:
        items.insert(0, {"type": "additional_tools", "role": "developer", "tools": []})
    return {
        "model": "gpt-5.4",
        "instructions": "synthetic instructions retained",
        "stream": True,
        "input": items,
        "parallel_tool_calls": True,
        "prompt_cache_key": "issue2538-composition",
        "reasoning": {"effort": "high", "summary": "auto"},
        "tools": [{"type": "function", "name": "lookup", "parameters": {"type": "object"}}],
    }


def _assert_full_payload(sent: dict, body: dict, *, websocket: bool, installation_id: str) -> None:
    # Build the schema-normalized control independently of the egress finalizer.
    expected: dict[str, Any] = deepcopy(dict(ResponsesRequest.model_validate(body).to_payload()))
    lite = any(item.get("type") == "additional_tools" for item in body["input"])
    if lite:
        expected["parallel_tool_calls"] = False
        expected["reasoning"]["context"] = "all_turns"
    if websocket:
        expected.pop("stream", None)
        expected["type"] = "response.create"
        if lite:
            expected["client_metadata"] = {LITE_MARKER: "true"}
    expected.setdefault("client_metadata", {})["x-codex-installation-id"] = installation_id
    assert sent == expected


async def _configure(async_client, monkeypatch, native_worker, base_url: str, mode: str):
    account_id = await _import_account(async_client, "acc_issue2538", "issue2538@example.com")
    account = await _get_account(account_id)
    settings = _make_app_settings(enabled=True)
    settings.upstream_base_url = base_url
    dashboard = _make_dashboard_settings()
    dashboard.api_key_auth_enabled = True
    if mode not in {"bridge", "raw_bridge"}:
        dashboard.upstream_stream_transport = "http"
        dashboard.http_downstream_transport_policy = "always_http" if mode == "forced_http" else "smart"
    _install_proxy_settings(monkeypatch, app_settings=settings, dashboard_settings=dashboard)
    monkeypatch.setattr(client_proxy, "get_settings", lambda: settings)
    monkeypatch.setattr(proxy_websocket, "get_settings", lambda: settings)
    monkeypatch.setattr(client_proxy, "discover_native_egress_client", lambda: native_worker)
    monkeypatch.setattr(proxy_websocket, "discover_native_egress_client", lambda: native_worker)
    monkeypatch.setattr(client_proxy, "resolve_http_proxy_from_env", lambda _url: None)

    async def select(self, *args, **kwargs):
        return AccountSelection(account=account, error_message=None, error_code=None)

    async def fresh(self, target, **kwargs):
        return target

    monkeypatch.setattr(proxy_service.ProxyService, "_select_account_with_budget", select)
    monkeypatch.setattr(proxy_service.ProxyService, "_ensure_fresh_with_budget", fresh)
    return account


def _events(response) -> list[dict]:
    return [
        event
        for block in re.split(r"\r\n\r\n|\n\n|\r\r", response.text)
        if (event := parse_sse_data_json(block)) is not None
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/responses", "/backend-api/codex/responses"])
@pytest.mark.parametrize("mode", ["forced_http", "native_http", "bridge", "raw_bridge"])
@pytest.mark.parametrize("visible", [False, True], ids=["before-visible", "after-visible"])
@pytest.mark.parametrize("lite", [True, False], ids=["lite", "non-lite"])
async def test_real_native_pretty_error_and_lite_route_composition(
    async_client, app_instance, monkeypatch, native_worker, path: str, mode: str, visible: bool, lite: bool
) -> None:
    requests: list[dict] = []
    heads: list[bytes] = []
    # A validation error is intentionally injected even though Lite normalization
    # removes the historical cause. Error delivery must remain independently safe.
    terminal = {"type": "error", "status": 400, "error": ERROR}
    upstream_done = asyncio.Event()
    enabled = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert enabled.status_code == 200
    key = await async_client.post(
        "/api/api-keys/",
        json={
            "name": "issue2538-synthetic",
            "limits": [{"limitType": "total_tokens", "limitWindow": "weekly", "maxValue": 100000}],
        },
    )
    assert key.status_code == 200
    releases: list[str] = []
    real_release = ApiKeysService.release_usage_reservation

    async def release(self, reservation_id, *args, **kwargs):
        releases.append(reservation_id)
        return await real_release(self, reservation_id, *args, **kwargs)

    monkeypatch.setattr(ApiKeysService, "release_usage_reservation", release)

    async def http_handler(reader, writer, head, body):
        heads.append(head)
        requests.append(json.loads(body))
        if len(requests) > 1:
            frames = [COMPLETED]
        elif visible:
            frames = [CREATED, DELTA, terminal]
        else:
            frames = []
        if frames:
            await _start_chunked_response(writer)
            for frame in frames:
                # Real multiline SSE data fields, split inside JSON/CRLF tokens.
                text = json.dumps(frame, indent=2)
                block = ("\r\n".join("data: " + line for line in text.splitlines()) + "\r\n\r\n").encode()
                for index in range(0, len(block), 11):
                    await _write_chunk(writer, block[index : index + 11])
        else:
            await _start_chunked_response(
                writer, status="400 Bad Request", content_type="application/json; charset=utf-8"
            )
            raw = json.dumps({"error": ERROR}, indent=2).encode()
            for index in range(0, len(raw), 7):
                await _write_chunk(writer, raw[index : index + 7])
        await _finish_chunks(writer)
        upstream_done.set()

    async def websocket_handler(websocket):
        async for text in websocket:
            requests.append(json.loads(text))
            frames = [COMPLETED] if len(requests) > 1 else ([CREATED, DELTA, terminal] if visible else [terminal])
            for frame in frames:
                await websocket.send(" \r\n" + json.dumps(frame, indent=2).replace("\n", "\r\n") + "\r\n ")
            upstream_done.set()

    async with _serve_http(http_handler) as http_url, serve(websocket_handler, "127.0.0.1", 0) as ws_server:
        websocket_mode = mode in {"bridge", "raw_bridge"}
        base_url = f"http://127.0.0.1:{ws_server.sockets[0].getsockname()[1]}" if websocket_mode else http_url
        account = await _configure(async_client, monkeypatch, native_worker, base_url, mode)
        service = get_proxy_service_for_app(app_instance)
        scheduler = VirtualScheduler(VirtualClock(monotonic_value=time.monotonic()))
        if websocket_mode:
            monkeypatch.setattr(service, "_clock", scheduler.clock)
            monkeypatch.setattr(service, "_scheduler", scheduler)
        health = AsyncMock(wraps=service._handle_stream_error)
        monkeypatch.setattr(service, "_handle_stream_error", health)
        penalty = AsyncMock(wraps=service._load_balancer.record_error)
        monkeypatch.setattr(service._load_balancer, "record_error", penalty)
        body = _body(lite)
        headers = {
            "session_id": "issue2538-affinity",
            "Authorization": "Bearer " + key.json()["key"],
            "user-agent": "codex_exec/0.153.4" if mode in {"native_http", "raw_bridge"} else "OpenAI/Python",
        }
        response = await asyncio.wait_for(async_client.post(path, json=body, headers=headers), timeout=10)
        await asyncio.wait_for(upstream_done.wait(), timeout=2)
        if response.status_code == 400:
            assert not visible
            assert response.json() == {"error": ERROR}
        else:
            assert response.status_code == 200
            events = _events(response)
            terminals = [e for e in events if e["type"] in {"error", "response.failed"}]
            assert len(terminals) == 1
            failed = terminals[0]
            assert (failed["response"] if failed["type"] == "response.failed" else failed)["error"] == ERROR
            if visible:
                assert [e["type"] for e in events if e["type"] != "codex.keepalive"] == [
                    "response.created",
                    "response.output_text.delta",
                    failed["type"],
                ]
            assert failed["type"] == (
                "error" if mode in {"native_http", "raw_bridge"} and path != "/v1/responses" else "response.failed"
            )
        assert len(requests) == 1
        _assert_full_payload(requests[0], body, websocket=websocket_mode, installation_id=account.codex_installation_id)
        if not websocket_mode:
            assert (b"x-openai-internal-codex-responses-lite: true" in heads[0].lower()) is lite
        assert native_worker._process is not None and native_worker._process.returncode is None
        penalty.assert_not_awaited()
        if websocket_mode:
            health.assert_not_awaited()
        for session in service._http_bridge_sessions.values():
            assert not session.pending_requests and session.queued_request_count == 0
            assert not session.response_create_gate.locked()
            assert session.account.id == account.id
        await service.drain_persistence_tasks(timeout_seconds=5)
        async with SessionLocal() as db:
            reservations = list((await db.execute(select(ApiKeyUsageReservation))).scalars())
            logs = list((await db.execute(select(RequestLog))).scalars())
        assert len(reservations) == 1 and reservations[0].status == "released"
        assert releases == [reservations[0].id]
        assert len(logs) == 1 and logs[0].status == "error"
        assert logs[0].error_code == "unsupported_value" and logs[0].account_id == account.id
        if websocket_mode:
            await scheduler.advance(122)
            assert len(requests) == 1
            assert not getattr(service, "_http_bridge_quarantined_keys", {})
            assert not getattr(service, "_http_bridge_retry_circuits")
        next_response = await asyncio.wait_for(async_client.post(path, json=body, headers=headers), timeout=10)
        assert next_response.status_code == 200
        assert _events(next_response)[-1]["type"] == "response.completed"
        assert len(requests) == 2
        assert native_worker.request.await_count == (0 if websocket_mode else 2)
        assert native_worker.websocket.await_count == (1 if websocket_mode else 0)
        penalty.assert_not_awaited()
        if websocket_mode:
            health.assert_not_awaited()
        assert not getattr(service, "_http_bridge_quarantined_keys", {})
        assert not getattr(service, "_http_bridge_retry_circuits")
        await service.drain_persistence_tasks(timeout_seconds=5)
        assert len(releases) == 2 and len(set(releases)) == 2
        if websocket_mode:
            for session in tuple(service._http_bridge_sessions.values()):
                await service._close_http_bridge_session(session)
            await scheduler.cancel_owned_tasks()
            assert all(task.done() for task in scheduler.owned_tasks)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/v1/responses", "/backend-api/codex/responses"])
@pytest.mark.parametrize("visible", [False, True])
async def test_direct_websocket_real_native_pretty_validation(
    async_client, app_instance, monkeypatch, native_worker, path: str, visible: bool
) -> None:
    requests: list[dict] = []
    terminal = {"type": "error", "status": 400, "error": ERROR}

    async def upstream(websocket):
        async for text in websocket:
            requests.append(json.loads(text))
            frames = [COMPLETED] if len(requests) > 1 else ([CREATED, DELTA, terminal] if visible else [terminal])
            for frame in frames:
                await websocket.send(json.dumps(frame, indent=2))

    async with serve(upstream, "127.0.0.1", 0) as peer:
        base_url = f"http://127.0.0.1:{peer.sockets[0].getsockname()[1]}"
        account = await _configure(async_client, monkeypatch, native_worker, base_url, "bridge")
        service = get_proxy_service_for_app(app_instance)
        penalty = AsyncMock(wraps=service._load_balancer.record_error)
        monkeypatch.setattr(service._load_balancer, "record_error", penalty)
        config = uvicorn.Config(
            app_instance, host="127.0.0.1", port=0, lifespan="off", log_config=None, access_log=False
        )
        server = uvicorn.Server(config)
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)
            body = _body()
            wire = {**body, "type": "response.create"}
            async with connect(
                f"ws://127.0.0.1:{listener.getsockname()[1]}{path}",
                additional_headers={"user-agent": "codex_exec/0.153.4", "session_id": "issue2538-direct"},
                proxy=None,
            ) as downstream:
                await downstream.send(json.dumps(wire))
                events = []
                async with asyncio.timeout(10):
                    while True:
                        event = json.loads(await downstream.recv())
                        events.append(event)
                        if event["type"] in {"error", "response.failed"}:
                            break
                assert events[-1] == terminal
                assert [e["type"] for e in events] == (
                    ["response.created", "response.output_text.delta", "error"] if visible else ["error"]
                )
                assert len(requests) == 1
                _assert_full_payload(requests[0], body, websocket=True, installation_id=account.codex_installation_id)
                await downstream.send(json.dumps(wire))
                async with asyncio.timeout(10):
                    completed = json.loads(await downstream.recv())
                assert completed["type"] == "response.completed"
                assert len(requests) == 2
                penalty.assert_not_awaited()
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(task, timeout=10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                listener.close()
        await service.drain_persistence_tasks(timeout_seconds=5)
        async with SessionLocal() as db:
            logs = list((await db.execute(select(RequestLog))).scalars())
        assert [row.status for row in logs].count("error") == 1
        assert {row.account_id for row in logs} == {account.id}
