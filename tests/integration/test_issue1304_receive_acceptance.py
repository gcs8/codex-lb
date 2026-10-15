"""Public native-wire ownership, replay and teardown qualification for ISSUE1304."""

from __future__ import annotations

import asyncio
import json
import os
import socket
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import uvicorn
from sqlalchemy import select
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from app.core import shutdown as shutdown_state
from app.core.clients.native_egress import NativeWebSocketRequest, SubprocessNativeEgressClient
from app.core.clients.proxy_websocket import NativeUpstreamWebSocket
from app.core.clock import RealScheduler
from app.db.models import Account, AccountStatus, ApiKeyUsageReservation, RequestLog
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, LimitRuleInput
from app.modules.proxy import api as proxy_api
from app.modules.proxy import service as proxy_service
from tests.integration.test_proxy_websocket_responses import _websocket_settings, _without_installation_metadata

pytestmark = pytest.mark.integration
PATHS = ["/backend-api/codex/responses", "/v1/responses"]


def _body(text):
    return {
        "type": "response.create",
        "model": "gpt-5.4",
        "instructions": "",
        "input": [{"role": "user", "content": text}],
        "stream": True,
    }


@asynccontextmanager
async def _wire(app, monkeypatch, peer, *, key=None, idle=60.0, pause_first=False):
    """Real sockets and helper; observe but never replace the session owner."""
    ready = asyncio.Event()
    entered = asyncio.Event()
    exited = asyncio.Event()
    receive_started = asyncio.Event()
    polled = asyncio.Event()
    release = asyncio.Event()
    dequeued = asyncio.Event()
    state = SimpleNamespace(
        active=0,
        peak=0,
        ingress=[],
        returned=[],
        cancelled=[],
        tasks=[],
        scope=None,
        receive_started=receive_started,
        polled=polled,
        release=release,
        dequeued=dequeued,
        exited=exited,
        prepared=[],
        admission=[],
        opened=[],
        selections=[],
        frames=[],
        closes=[],
    )
    service = get_proxy_service_for_app(app)
    state.service = service
    state.health = AsyncMock()
    state.backoff = AsyncMock()
    monkeypatch.setattr(service, "_handle_stream_error", state.health)
    monkeypatch.setattr(service._load_balancer, "record_error_backoff", state.backoff)
    monkeypatch.setattr(service._load_balancer, "record_success", AsyncMock())
    monkeypatch.setattr(proxy_api, "_websocket_firewall_denial_response", AsyncMock(return_value=None))
    monkeypatch.setattr(proxy_api, "validate_proxy_api_key_authorization", AsyncMock(return_value=key))
    monkeypatch.setattr(proxy_api, "_websocket_upstream_transport_denial", AsyncMock(return_value=None))
    settings = _websocket_settings(proxy_downstream_websocket_idle_timeout_seconds=idle)
    original_settings = proxy_service.get_settings()
    monkeypatch.setattr(
        proxy_service,
        "get_settings",
        lambda: original_settings.model_copy(update={"proxy_downstream_websocket_idle_timeout_seconds": idle}),
    )
    monkeypatch.setattr(
        proxy_service, "get_settings_cache", lambda: SimpleNamespace(get=AsyncMock(return_value=settings))
    )
    monkeypatch.setattr(proxy_service, "_DOWNSTREAM_WEBSOCKET_RECEIVE_POLL_SECONDS", 0.05)
    original_prepare = service._prepare_websocket_response_create_request

    async def prepare(*args, **kwargs):
        result = await original_prepare(*args, **kwargs)
        state.prepared.append(result)
        state.admission.append((result.request_state.started_at, result.request_state.api_key_reservation))
        return result

    monkeypatch.setattr(service, "_prepare_websocket_response_create_request", prepare)

    class Observer(RealScheduler):
        def create_task(self, coro, *, name=None, **kwargs):
            task = asyncio.create_task(coro, name=name, **kwargs)
            if name == "proxy-websocket-downstream-receive":
                state.tasks.append(task)
            return task

        async def wait(self, fs, *, timeout=None, return_when=asyncio.ALL_COMPLETED):
            result = await asyncio.wait(fs, timeout=timeout, return_when=return_when)
            if not result[0] and any(task in state.tasks for task in fs):
                polled.set()
            return result

    monkeypatch.setattr(service, "_scheduler", Observer())

    class Boundary:
        async def __call__(self, scope, receive, send):
            if scope["type"] != "websocket":
                return await app(scope, receive, send)
            state.scope = asyncio.current_task()
            entered.set()

            async def owned_receive():
                state.active += 1
                state.peak = max(state.peak, state.active)
                receive_started.set()
                frame = None
                try:
                    frame = await receive()
                    if frame["type"] == "websocket.receive":
                        state.ingress.append(frame["text"])
                        if len(state.ingress) == (1 if pause_first else 2):
                            polled.clear()
                            dequeued.set()
                            await release.wait()
                        state.returned.append(frame["text"])
                    return frame
                except asyncio.CancelledError:
                    state.cancelled.append(frame)
                    raise
                finally:
                    state.active -= 1

            try:
                await app(scope, owned_receive, send)
            finally:
                exited.set()

    class ReadyServer(uvicorn.Server):
        async def startup(self, sockets=None):
            await super().startup(sockets=sockets)
            ready.set()

    native = SubprocessNativeEgressClient(Path(os.environ["CODEX_LB_NATIVE_EGRESS_TEST_BINARY"]))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    server = ReadyServer(uvicorn.Config(Boundary(), lifespan="off", log_config=None, access_log=False))
    task = None
    try:
        async with serve(lambda ws: peer(ws, state), "127.0.0.1", 0, close_timeout=1) as upstream:
            port = upstream.sockets[0].getsockname()[1]

            async def open_upstream(account, headers, *, request_state=None, **kwargs):
                assert request_state is not None
                state.opened.append(
                    (
                        account.id,
                        request_state,
                        request_state.started_at,
                        request_state.api_key_reservation,
                        request_state.replay_count,
                    )
                )
                websocket = await native.websocket(
                    NativeWebSocketRequest(
                        url=f"ws://127.0.0.1:{port}/responses",
                        headers={},
                        connect_timeout_seconds=2,
                        max_message_bytes=65536,
                        interpret_responses=True,
                    )
                )
                return NativeUpstreamWebSocket(websocket)

            monkeypatch.setattr(service, "_open_upstream_websocket", open_upstream)
            task = asyncio.create_task(server._serve(sockets=[listener]))
            async with asyncio.timeout(5):
                await ready.wait()
            state.url = f"ws://127.0.0.1:{listener.getsockname()[1]}"
            yield state
    finally:
        release.set()
        server.should_exit = True
        if task is not None:
            try:
                await asyncio.wait_for(task, timeout=5)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        listener.close()
        process = native._process
        await native.aclose()
        if process is not None:
            assert process.returncode == 0
        await service.drain_persistence_tasks(timeout_seconds=5)
        assert state.active == 0
        assert state.peak == 1
        assert all(t.done() for t in state.tasks)
        assert exited.is_set() or not entered.is_set()


async def _events(ws):
    async with asyncio.timeout(5):
        events = [json.loads(await ws.recv()) for _ in range(2)]
    assert [event["type"] for event in events] == ["response.created", "response.completed"]
    return events


async def _complete(ws, response_id):
    for kind, status in [("response.created", "in_progress"), ("response.completed", "completed")]:
        await ws.send(
            json.dumps(
                {
                    "type": kind,
                    "response": {
                        "id": response_id,
                        "status": status,
                        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                    },
                }
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("mode", ["fresh", "sent_replay", "caller", "file", "mcp", "opaque", "healthy_idle"])
async def test_receive_handoff_keeps_real_dispatch_and_reservation_owner(
    app_instance, monkeypatch, path, mode, record_property
):
    accounts = []
    async with SessionLocal() as session:
        for suffix in ("old", "fresh"):
            account = Account(
                id=f"fixture-{suffix}",
                chatgpt_account_id=f"fixture-{suffix}",
                email=f"fixture-{suffix}@example.invalid",
                plan_type="plus",
                access_token_encrypted=b"fixture",
                refresh_token_encrypted=b"fixture",
                id_token_encrypted=b"fixture",
                last_refresh=proxy_service.utcnow(),
                status=AccountStatus.ACTIVE,
            )
            session.add(account)
            accounts.append(account)
        await session.commit()
    async with SessionLocal() as session:
        key = await ApiKeysService(ApiKeysRepository(session)).create_key(
            ApiKeyCreateData(
                name="fixture receive owner",
                allowed_models=None,
                limits=[LimitRuleInput(limit_type="total_tokens", limit_window="weekly", max_value=1_000_000)],
            )
        )
    settled = []
    original_finalize = ApiKeysService.finalize_usage_reservation

    async def finalize(self, reservation_id, **kwargs):
        settled.append(reservation_id)
        return await original_finalize(self, reservation_id, **kwargs)

    monkeypatch.setattr(ApiKeysService, "finalize_usage_reservation", finalize)
    first = _body("fixture:first")
    second = _body("fixture:second")
    if mode in {"caller", "mcp", "opaque"}:
        second["previous_response_id"] = "resp_fixture_first"
    if mode == "mcp":
        second["input"] = [{"type": "mcp_approval_response", "approval_request_id": "fixture:mcp", "approve": True}]
    if mode == "opaque":
        second["input"] = [{"type": "item_reference", "id": "fixture:opaque"}]
    if mode == "file":
        second["input"] = [{"role": "user", "content": [{"type": "input_file", "file_id": "fixture:file"}]}]
    pinned = mode in {"caller", "file", "mcp", "opaque"}
    old_observed = asyncio.Event()
    old_closed = asyncio.Event()

    async def peer(ws, state):
        frames = []
        state.frames.append(frames)
        generation = len(state.frames)
        async for text in ws:
            frames.append(json.loads(text))
            if generation == 1 and len(frames) == 1:
                await _complete(ws, "resp_fixture_first")
                await asyncio.wait_for(state.dequeued.wait(), timeout=5)
                await asyncio.wait_for(state.polled.wait(), timeout=5)
                if mode == "sent_replay":
                    state.release.set()
                    text = await asyncio.wait_for(ws.recv(), timeout=5)
                    frames.append(json.loads(text))
                    old_observed.set()
                await ws.close(code=1000)
                old_closed.set()
                return
            await _complete(ws, "resp_fixture_second")

    async with _wire(app_instance, monkeypatch, peer, key=key, idle=0.5 if mode == "healthy_idle" else 60) as state:
        service = state.service

        async def select_account(deadline, **kwargs):
            state.selections.append(kwargs)
            preferred = kwargs.get("preferred_account_id")
            selected = accounts[0] if preferred == accounts[0].id or len(state.opened) == 0 else accounts[1]
            return SimpleNamespace(account=selected, lease=None)

        async def fresh(account, **kwargs):
            return account

        monkeypatch.setattr(service, "_select_account_with_budget_compatible", select_account)
        monkeypatch.setattr(service, "_ensure_fresh_with_budget", fresh)
        if mode == "file":

            async def file_owner(payload, headers):
                return accounts[0].id if "fixture:file" in json.dumps(payload.to_payload()) else None

            monkeypatch.setattr(service, "_resolve_file_account_for_responses", file_owner)
        async with connect(state.url + path, proxy=None, close_timeout=1) as downstream:
            await downstream.send(json.dumps(first))
            await _events(downstream)
            await downstream.send(json.dumps(second))
            async with asyncio.timeout(5):
                await state.dequeued.wait()
                await state.polled.wait()
                await old_closed.wait()
            assert not state.cancelled
            state.release.set()
            events = await _events(downstream)
            assert events[-1]["response"]["id"] == "resp_fixture_second"
            if mode == "healthy_idle":
                async with asyncio.timeout(5):
                    await downstream.wait_closed()
                assert downstream.close_code == 1001
        async with asyncio.timeout(5):
            await state.exited.wait()
        await service.drain_persistence_tasks(timeout_seconds=5)
        assert state.ingress == state.returned == [json.dumps(first), json.dumps(second)]
        assert len(state.prepared) == 2
        assert [len(frames) for frames in state.frames] == ([2, 1] if mode == "sent_replay" else [1, 1])
        assert _without_installation_metadata(state.frames[1][0]) == _without_installation_metadata(
            json.loads(state.prepared[1].text_data)
        )
        assert state.frames[1][0]["input"] == second["input"]
        assert state.frames[1][0].get("previous_response_id") == second.get("previous_response_id")
        assert [item[0] for item in state.opened] == ["fixture-old", "fixture-old" if pinned else "fixture-fresh"]
        assert state.selections[-1]["preferred_account_id"] == ("fixture-old" if pinned else None)
        assert state.selections[-1]["fallback_on_preferred_account_unavailable"] is (not pinned)
        second_state = state.prepared[1].request_state
        assert state.opened[-1][1] is second_state
        assert state.opened[-1][2:4] == state.admission[1]
        assert state.admission[0][1].reservation_id != state.admission[1][1].reservation_id
        assert second_state.replay_count == (1 if mode == "sent_replay" else 0)
        assert old_observed.is_set() is (mode == "sent_replay")
        if mode == "sent_replay":
            assert _without_installation_metadata(state.frames[0][1]) == _without_installation_metadata(
                state.frames[1][0]
            )
        assert len(settled) == len(set(settled)) == 2
        async with SessionLocal() as session:
            rows = list((await session.scalars(select(ApiKeyUsageReservation))).all())
            logs = list((await session.scalars(select(RequestLog))).all())
            statuses = list((await session.scalars(select(Account.status))).all())
        assert {row.id for row in rows} == set(settled)
        assert [row.status for row in rows] == ["finalized", "finalized"]
        assert len(logs) == 2
        assert {log.request_id: log.account_id for log in logs} == {
            "resp_fixture_first": "fixture-old",
            "resp_fixture_second": "fixture-old" if pinned else "fixture-fresh",
        }
        assert [row.input_tokens for row in rows] == [1, 1]
        assert [row.output_tokens for row in rows] == [1, 1]
        assert statuses == [AccountStatus.ACTIVE, AccountStatus.ACTIVE]
        state.health.assert_not_awaited()
        state.backoff.assert_not_awaited()
        record_property(
            "ownership",
            json.dumps(
                {
                    "mode": mode,
                    "owners": [x[0] for x in state.opened],
                    "dispatch_counts": [len(x) for x in state.frames],
                    "settlement_count": len(settled),
                    "replay_count": second_state.replay_count,
                    "receive_peak": state.peak,
                }
            ),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize(
    "ending,phase",
    [
        ("client_disconnect", "blocked"),
        ("scope_cancel", "blocked"),
        ("drain", "blocked"),
        ("idle", "blocked"),
        ("scope_cancel", "consumed"),
        ("drain", "consumed"),
        ("idle", "consumed"),
    ],
)
async def test_public_blocked_receive_is_joined_only_at_connection_teardown(
    app_instance, monkeypatch, path, ending, phase
):
    async def peer(ws, state):
        raise AssertionError("idle/cancelled ingress must not open an upstream")

    async with _wire(
        app_instance, monkeypatch, peer, idle=0.1 if ending == "idle" else 60, pause_first=phase == "consumed"
    ) as state:
        connector = AsyncMock(side_effect=AssertionError("no upstream dispatch"))
        monkeypatch.setattr(state.service, "_connect_proxy_websocket", connector)
        async with connect(state.url + path, proxy=None, close_timeout=1) as downstream:
            if phase == "consumed":
                await downstream.send(json.dumps(_body("fixture:cancel")))
            async with asyncio.timeout(5):
                await state.receive_started.wait()
                if phase == "consumed":
                    await state.dequeued.wait()
                await state.polled.wait()
            assert len(state.tasks) == 1
            receive = state.tasks[0]
            assert not receive.done()
            assert not state.cancelled
            if ending == "client_disconnect":
                await downstream.close()
            elif ending == "scope_cancel":
                state.scope.cancel()
            elif ending == "drain":
                shutdown_state.set_draining()
            try:
                async with asyncio.timeout(5):
                    await state.exited.wait()
                if ending in {"idle", "drain"}:
                    await downstream.wait_closed()
                    assert downstream.close_code == (1001 if ending == "idle" else 1012)
                assert receive.done()
                assert len(state.tasks) == 1
                connector.assert_not_awaited()
                state.health.assert_not_awaited()
                state.backoff.assert_not_awaited()
                if phase == "consumed":
                    assert len(state.ingress) == len(state.cancelled) == 1
                    assert state.returned == []
                    assert state.prepared == []
            finally:
                shutdown_state.reset()
