from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from aiohttp import web
from sqlalchemy import select

import app.core.clients.proxy as core_proxy
import app.modules.proxy.api as proxy_api
import app.modules.proxy.service as proxy_service
from app.core.config.settings import get_settings
from app.core.crypto import TokenEncryptor
from app.core.utils.sse import format_sse_event
from app.db.models import Account, AccountStatus, ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app

pytestmark = pytest.mark.integration


@asynccontextmanager
async def _loopback_upstream(mode: str) -> AsyncIterator[tuple[str, list[dict]]]:
    requests: list[dict] = []

    async def respond(request: web.Request) -> web.StreamResponse:
        body = await request.json()
        requests.append(body)
        response_id = f"resp_lease_{len(requests)}"
        response = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
        await response.prepare(request)
        events = [
            {"type": "response.created", "response": {"id": response_id, "status": "in_progress", "output": []}},
            {"type": "response.output_text.delta", "response_id": response_id, "delta": "partial"},
        ]
        if mode == "native-failure":
            events.append(
                {
                    "type": "response.failed",
                    "_codex_lb_synthetic_transport_failure": True,
                    "response": {
                        "id": response_id,
                        "status": "failed",
                        "error": {
                            "code": "upstream_request_timeout",
                            "message": "Synthetic upstream transport failure",
                        },
                        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    },
                }
            )
        elif mode == "public-error":
            events.append({"type": "error", "error": {"code": "fixture_error", "message": "Synthetic provider error"}})
        else:
            events.append(
                {
                    "type": "response.completed",
                    "response": {
                        "id": response_id,
                        "status": "completed",
                        "output": [],
                        "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                    },
                }
            )
        for event in events:
            await response.write(format_sse_event(event).encode())
        await response.write_eof()
        return response

    app = web.Application()
    app.router.add_post("/backend-api/codex/responses", respond)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    try:
        yield f"http://127.0.0.1:{port}/backend-api", requests
    finally:
        await runner.cleanup()


async def _setup(async_client, app_instance, monkeypatch, upstream: str):
    service = get_proxy_service_for_app(app_instance)
    encryptor = TokenEncryptor()
    account = Account(
        id="fixture-stream-lease",
        chatgpt_account_id="fixture-stream-lease",
        email="fixture-stream-lease@example.invalid",
        plan_type="plus",
        access_token_encrypted=encryptor.encrypt("synthetic-access"),
        refresh_token_encrypted=encryptor.encrypt("synthetic-refresh"),
        id_token_encrypted=encryptor.encrypt("synthetic-id"),
        last_refresh=proxy_service.utcnow(),
        status=AccountStatus.ACTIVE,
    )
    async with SessionLocal() as session:
        session.add(account)
        await session.commit()
    configured = get_settings().model_copy(update={"upstream_base_url": upstream})
    for module in (proxy_api, proxy_service, core_proxy):
        monkeypatch.setattr(module, "get_settings", lambda: configured)
    monkeypatch.setattr(core_proxy, "discover_native_egress_client", lambda: None)

    async def fresh(selected, **kwargs):
        assert selected.id == account.id
        return selected

    monkeypatch.setattr(service, "_ensure_fresh_with_budget", fresh)
    updated = await async_client.put(
        "/api/settings",
        json={"apiKeyAuthEnabled": True, "upstreamStreamTransport": "http", "routingStrategy": "usage_weighted"},
    )
    assert updated.status_code == 200, updated.text
    key = await async_client.post(
        "/api/api-keys/",
        json={
            "name": "fixture-stream-lease",
            "limits": [{"limitType": "total_tokens", "limitWindow": "weekly", "maxValue": 1_000_000}],
        },
    )
    assert key.status_code == 200, key.text
    # Retain the actual retry iterators so GC cannot conceal a missing close.
    retry_streams = []
    original = service._stream_with_retry

    def retry(*args, **kwargs):
        result = original(*args, **kwargs)
        retry_streams.append(result)
        return result

    monkeypatch.setattr(service, "_stream_with_retry", retry)
    return service, account.id, {"authorization": f"Bearer {key.json()['key']}"}, retry_streams


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "mode"),
    [("/backend-api/codex/responses", "native-failure"), ("/v1/responses", "public-error")],
)
async def test_public_stream_early_exit_releases_real_account_lease(
    async_client, app_instance, monkeypatch, path, mode
):
    async with _loopback_upstream(mode) as (url, upstream_requests):
        service, account_id, headers, streams = await _setup(async_client, app_instance, monkeypatch, url)
        if mode == "native-failure":
            headers.update({"user-agent": "codex_exec/0.150.1 (Ubuntu; x86_64)", "originator": "codex_exec"})
        try:
            for index in range(9):
                request = async_client.post(
                    path,
                    json={"model": "gpt-5.1", "instructions": "fixture", "input": [], "stream": True},
                    headers=headers,
                )
                if mode == "native-failure":
                    with pytest.raises(core_proxy.ProxyResponseError) as caught:
                        await asyncio.wait_for(request, timeout=5)
                    assert caught.value.payload["error"]["code"] == "stream_incomplete"
                else:
                    response = await asyncio.wait_for(request, timeout=5)
                    assert response.status_code == 200, response.text
                    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: {")]
                    assert events[-1]["type"] == "response.failed"
                    assert events[-1]["response"]["error"] == {
                        "code": "fixture_error",
                        "message": "Synthetic provider error",
                        "type": "server_error",
                    }
                assert await service._load_balancer.account_pressure_snapshot(account_id) == (0, 0, 0.0)
                assert len(upstream_requests) == index + 1
                assert await service.drain_persistence_tasks(timeout_seconds=5)
                async with SessionLocal() as session:
                    rows = list((await session.scalars(select(ApiKeyUsageReservation))).all())
                    logs = list((await session.scalars(select(RequestLog))).all())
                assert len(rows) == index + 1
                assert all(row.status in {"finalized", "released"} for row in rows)
                assert len(logs) == index + 1
                assert all(log.account_id == account_id for log in logs)
        finally:
            # Test-owned cleanup of retained baseline leaks after the assertion.
            for stream in streams:
                await stream.aclose()
            await service.drain_persistence_tasks(timeout_seconds=5)
