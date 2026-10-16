from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from aiohttp import web
from sqlalchemy import select
from starlette.requests import ClientDisconnect

import app.core.clients.proxy as core_proxy
import app.core.utils.sse as sse
from app.core.utils.shared_future import wait_on_shared_future
from app.db.models import ApiKeyLimit, ApiKeyUsageReservation, ApiKeyUsageReservationItem, RequestLog
from app.db.session import SessionLocal
from tests.integration.test_stream_cleanup_schedules import _assert_released, _blocked_upstream, _StreamPhase
from tests.integration.test_stream_wrapper_lease import _loopback_upstream, _setup
from tests.unit.test_websocket_transport_fallback import _pre_submit_error

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("path", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize("spec_version", ["2.0", "2.4"])
@pytest.mark.parametrize("exit_kind", ["cancel", "send-error"])
async def test_real_send_exit_recovers_nine_slots(
    async_client, app_instance, monkeypatch, path, spec_version, exit_kind
):
    phase: _StreamPhase = {"mode": "mid-read", "requests": 0}
    for name in ("arrived", "finish", "server_done"):
        phase[name] = asyncio.Event()
    delta = False
    heartbeat = False
    blocked = asyncio.Event()
    fail_send = asyncio.Event()

    async def causal_wait(shared, *, timeout=None, **kwargs):
        nonlocal heartbeat
        if delta and not heartbeat:
            heartbeat = True
            raise TimeoutError
        return await wait_on_shared_future(shared, timeout=timeout, **kwargs)

    monkeypatch.setattr(sse, "wait_on_shared_future", causal_wait)
    async with _blocked_upstream(phase) as upstream:
        service, account_id, headers, streams = await _setup(async_client, app_instance, monkeypatch, upstream)
        for index in range(9):
            delta = heartbeat = False
            blocked = asyncio.Event()
            fail_send = asyncio.Event()
            for name in ("arrived", "finish", "server_done"):
                phase[name] = asyncio.Event()
            sent_request = False
            body = json.dumps({"model": "gpt-5.1", "instructions": "fixture", "input": [], "stream": True}).encode()

            async def receive():
                nonlocal sent_request
                if not sent_request:
                    sent_request = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await asyncio.Event().wait()

            async def send(message):
                nonlocal delta
                chunk = message.get("body", b"")
                if b"response.output_text.delta" in chunk:
                    delta = True
                if heartbeat and (chunk.startswith(b":") or b"codex.keepalive" in chunk):
                    blocked.set()
                    if exit_kind == "send-error":
                        await fail_send.wait()
                        raise OSError("synthetic send failure")
                    await asyncio.Event().wait()

            scope = {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": spec_version},
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
            await asyncio.wait_for(blocked.wait(), 5)
            assert delta and heartbeat
            if exit_kind == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 5)
            else:
                fail_send.set()
                error = OSError if spec_version == "2.0" else ClientDisconnect
                with pytest.raises(error):
                    await asyncio.wait_for(task, 5)
            await _assert_released(service, account_id, streams, index + 1)
            assert phase["requests"] == index + 1
            phase["finish"].set()
            await asyncio.wait_for(phase["server_done"].wait(), 3)
        assert not [task for task in service._background_cleanup_tasks if not task.done()]


async def test_native_failed_frame_usage_unobserved_without_charge(async_client, app_instance, monkeypatch):
    async with _loopback_upstream("native-failure") as (url, requests):
        service, account_id, headers, streams = await _setup(async_client, app_instance, monkeypatch, url)
        headers.update({"user-agent": "codex_exec/0.150.1 (Ubuntu; x86_64)", "originator": "codex_exec"})
        for index in range(9):
            with pytest.raises(core_proxy.ProxyResponseError) as caught:
                await asyncio.wait_for(
                    async_client.post(
                        "/backend-api/codex/responses",
                        json={"model": "gpt-5.1", "instructions": "fixture", "input": [], "stream": True},
                        headers=headers,
                    ),
                    5,
                )
            assert caught.value.payload["error"]["code"] == "stream_incomplete"
            assert len(streams) == len(requests) == index + 1
            assert all(stream.ag_frame is None for stream in streams)
            assert await service._load_balancer.account_pressure_snapshot(account_id) == (0, 0, 0.0)
            assert await service.drain_persistence_tasks(timeout_seconds=5)
            async with SessionLocal() as session:
                reservations = list((await session.scalars(select(ApiKeyUsageReservation))).all())
                items = list((await session.scalars(select(ApiKeyUsageReservationItem))).all())
                limits = list((await session.scalars(select(ApiKeyLimit))).all())
                logs = list((await session.scalars(select(RequestLog))).all())
            assert len(reservations) == len(items) == len(logs) == index + 1
            assert all(row.status == "released" for row in reservations)
            assert all((row.input_tokens, row.output_tokens) == (None, None) for row in reservations)
            assert all(item.actual_delta == 0 for item in items)
            assert len(limits) == 1 and limits[0].current_value == 0
            assert all(
                (log.status, log.error_code, log.input_tokens, log.output_tokens)
                == (
                    "error",
                    "upstream_request_timeout",
                    None,
                    None,
                )
                for log in logs
            )
            assert all(
                log.input_tokens is None and log.output_tokens is None and log.account_id == account_id for log in logs
            )


@asynccontextmanager
async def _incomplete_usage_upstream() -> AsyncIterator[tuple[str, list[dict]]]:
    # Local fixture: do not change the older failed/completed upstream contract.
    requests: list[dict] = []

    async def respond(request: web.Request) -> web.StreamResponse:
        requests.append(await request.json())
        response_id = f"resp_incomplete_usage_{len(requests)}"
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        events = [
            {"type": "response.created", "response": {"id": response_id, "status": "in_progress", "output": []}},
            {"type": "response.output_text.delta", "response_id": response_id, "delta": "partial"},
            {
                "type": "response.incomplete",
                "response": {
                    "id": response_id,
                    "status": "incomplete",
                    "output": [],
                    "incomplete_details": {"reason": "max_output_tokens"},
                    "usage": {"input_tokens": 7, "output_tokens": 4, "total_tokens": 11},
                },
            },
        ]
        for event in events:
            await response.write(sse.format_sse_event(event).encode())
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/backend-api/codex/responses", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    try:
        yield f"http://127.0.0.1:{runner.addresses[0][1]}/backend-api", requests
    finally:
        await runner.cleanup()


async def test_native_incomplete_preserves_observed_usage_with_released_reservation(
    async_client, app_instance, monkeypatch
):
    from app.modules.api_keys.service import ApiKeysService

    releases = []
    finalizations = []
    release = ApiKeysService.release_usage_reservation
    finalize = ApiKeysService.finalize_usage_reservation

    async def tracked_release(self, reservation_id):
        releases.append(reservation_id)
        return await release(self, reservation_id)

    async def tracked_finalize(self, reservation_id, **kwargs):
        finalizations.append(reservation_id)
        return await finalize(self, reservation_id, **kwargs)

    monkeypatch.setattr(ApiKeysService, "release_usage_reservation", tracked_release)
    monkeypatch.setattr(ApiKeysService, "finalize_usage_reservation", tracked_finalize)
    async with _incomplete_usage_upstream() as (url, requests):
        service, account_id, headers, streams = await _setup(async_client, app_instance, monkeypatch, url)
        headers.update({"user-agent": "codex_exec/0.150.1 (Ubuntu; x86_64)", "originator": "codex_exec"})
        for index in range(9):
            response = await asyncio.wait_for(
                async_client.post(
                    "/backend-api/codex/responses",
                    json={"model": "gpt-5.1", "instructions": "fixture", "input": [], "stream": True},
                    headers=headers,
                ),
                5,
            )
            assert response.status_code == 200, response.text
            events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
            assert [event["type"] for event in events] == [
                "response.created",
                "response.output_text.delta",
                "response.incomplete",
            ]
            assert events[-1]["response"]["status"] == "incomplete"
            assert events[-1]["response"]["incomplete_details"] == {"reason": "max_output_tokens"}
            assert events[-1]["response"]["usage"] == {"input_tokens": 7, "output_tokens": 4, "total_tokens": 11}
            assert len(streams) == len(requests) == index + 1
            assert all(stream.ag_frame is None for stream in streams)
            assert await service._load_balancer.account_pressure_snapshot(account_id) == (0, 0, 0.0)
            assert await service.drain_persistence_tasks(timeout_seconds=5)
            async with SessionLocal() as session:
                reservations = list((await session.scalars(select(ApiKeyUsageReservation))).all())
                items = list((await session.scalars(select(ApiKeyUsageReservationItem))).all())
                limits = list((await session.scalars(select(ApiKeyLimit))).all())
                logs = list((await session.scalars(select(RequestLog))).all())
            assert len(reservations) == len(items) == len(logs) == index + 1
            assert all(row.status == "released" for row in reservations)
            assert all((row.input_tokens, row.output_tokens) == (None, None) for row in reservations)
            assert all(item.actual_delta == 0 for item in items)
            assert len(limits) == 1 and limits[0].current_value == 0
            assert all(
                (log.status, log.error_code, log.input_tokens, log.output_tokens) == ("error", None, 7, 4)
                for log in logs
            )
            assert all(
                log.input_tokens is not None
                and log.output_tokens is not None
                and log.input_tokens + log.output_tokens == 11
                and log.account_id == account_id
                for log in logs
            )
            assert len(releases) == len(set(releases)) == index + 1
            assert set(releases) == {row.id for row in reservations}
            assert finalizations == []
        assert not [task for task in service._background_cleanup_tasks if not task.done()]


async def test_no_reservation_bridge_fallback_closes_real_retry(async_client, app_instance, monkeypatch):
    import app.modules.proxy._service.http_bridge.streaming as bridge_module
    from tests.unit.test_websocket_transport_fallback import _bridge_runtime_config

    async with _loopback_upstream("complete") as (url, requests):
        service, account_id, _, streams = await _setup(async_client, app_instance, monkeypatch, url)
        # Exercise the genuine service subscription path, where fallback is
        # allowed only without an API-key reservation. Retain real retry owners.
        monkeypatch.setattr(bridge_module, "_http_bridge_runtime_config", lambda *args: _bridge_runtime_config())
        monkeypatch.setattr(bridge_module, "configured_upstream_stream_transport", lambda settings: "default")
        attempts = []

        async def bridge(*args, **kwargs):
            assert kwargs["api_key_reservation"] is None
            attempts.append("pre-submit-connect")
            raise _pre_submit_error()
            yield "unreachable"

        monkeypatch.setattr(service, "_stream_via_http_bridge", bridge)
        for index in range(9):
            # A real connect failure arms the transport marker; clear only that
            # test-owned marker between independent fallback attempts.
            from app.modules.proxy._service import support

            support.clear_upstream_websocket_transport_failure()
            from app.core.openai.requests import ResponsesRequest

            stream = service.stream_http_responses(
                ResponsesRequest(model="gpt-5.1", instructions="fixture", input=[]),
                {},
                codex_session_affinity=True,
                propagate_http_errors=True,
                openai_cache_affinity=False,
                api_key=None,
                api_key_reservation=None,
                suppress_text_done_events=False,
            )
            assert "response.created" in await asyncio.wait_for(anext(stream), 5)
            await stream.aclose()
            assert len(streams) == len(requests) == len(attempts) == index + 1
            assert all(child.ag_frame is None for child in streams)
            assert await service._load_balancer.account_pressure_snapshot(account_id) == (0, 0, 0.0)
            assert await service.drain_persistence_tasks(timeout_seconds=5)
        async with SessionLocal() as session:
            assert list((await session.scalars(select(ApiKeyUsageReservation))).all()) == []
