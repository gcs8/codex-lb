from __future__ import annotations

import asyncio
import base64
import errno
import json
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs

import aiohttp
import pytest
from aiohttp.client_reqrep import ConnectionKey
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.clients import http as http_module
from app.core.clients import oauth as client_module
from app.core.crypto import TokenEncryptor
from app.db.models import Account, OAuthDeviceFlowSlot, OAuthFlowState
from app.db.session import SessionLocal
from app.modules.accounts.repository import AccountsRepository
from app.modules.oauth import service as oauth_module
from app.modules.oauth.repository import OAuthFlowRepository

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

TRANSPORT_MESSAGE = (
    "Unable to reach the OAuth provider. Check outbound connectivity and proxy settings, then restart login."
)
CODE = "SYNTHETIC_AUTH_CODE_2601"
STATE = "SYNTHETIC_STATE_2601"
VERIFIER = "SYNTHETIC_VERIFIER_2601"
SECRET = "SYNTHETIC_PROXY_PASSWORD_2601"


def _failure(kind):
    if kind == "refused":
        key = ConnectionKey("oauth.invalid", 443, True, True, None, None, None)
        return aiohttp.ClientConnectorError(key, OSError(errno.ECONNREFUSED, SECRET))
    if kind == "timeout":
        return TimeoutError()
    if kind == "payload":
        return aiohttp.ClientPayloadError(SECRET)
    if kind == "disconnect":
        return aiohttp.ServerDisconnectedError(SECRET)
    if kind == "cancel":
        return asyncio.CancelledError()
    if kind == "systemexit":
        return SystemExit(73)
    if kind == "unknown":
        return RuntimeError("synthetic unknown transport class")
    return None


def _token_payload():
    claims = {"email": "synthetic2601@example.invalid", "chatgpt_account_id": "synthetic2601"}
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return {
        "access_token": "synthetic-access-2601",
        "refresh_token": "synthetic-refresh-2601",
        "id_token": f"header.{body}.sig",
    }


@pytest.fixture
async def transport_harness(app_instance, monkeypatch):
    store = oauth_module.OAuthStateStore()
    monkeypatch.setattr(oauth_module, "_OAUTH_STORE", store)
    monkeypatch.setattr(client_module, "AUTH_BASE_URL", "https://oauth.invalid")
    calls = []
    outcome: dict[str, Any] = {"kind": "success", "status": 200, "body": None}
    original = aiohttp.ClientSession._request

    class Response:
        status = 200
        body = None

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.release()
            await self.wait_for_close()

        async def json(self, **kwargs):
            if outcome["kind"] == "payload":
                raise aiohttp.ClientPayloadError(SECRET)
            return self.body

        async def text(self):
            if outcome["kind"] == "payload":
                raise aiohttp.ClientPayloadError(SECRET)
            return json.dumps(self.body)

        def release(self):
            return None

        async def wait_for_close(self):
            return None

    async def request(session, method, url, **kwargs):
        if not str(url).startswith("https://oauth.invalid/"):
            assert str(url).startswith("http://127.0.0.1:")
            return await original(session, method, url, **kwargs)
        calls.append((method, str(url), kwargs))
        failure = _failure(outcome["kind"])
        if failure is not None and outcome["kind"] != "payload":
            if outcome.get("durable_success"):
                await outcome["durable_success"]()
            raise failure
        response = Response()
        response.status = outcome["status"]
        response.body = outcome["body"]
        if response.body is None:
            if str(url).endswith("/oauth/token"):
                response.body = _token_payload()
            elif str(url).endswith("/usercode"):
                response.body = {
                    "user_code": "SYNTHETIC-USER-CODE",
                    "device_auth_id": "synthetic-device-2601",
                    "interval": 60,
                    "expires_in": 120,
                }
            else:
                response.body = {"error": "authorization_pending"}
        return response

    monkeypatch.setattr(aiohttp.ClientSession, "_request", request)
    await http_module.init_http_client()
    async with SessionLocal() as session:
        service = oauth_module.OauthService(AccountsRepository(session), store=store)
        async with AsyncClient(
            transport=ASGITransport(app=app_instance, raise_app_exceptions=False), base_url="http://testserver"
        ) as api:
            yield SimpleNamespace(store=store, service=service, api=api, calls=calls, outcome=outcome)
    tasks = [flow.poll_task for flow in store._flows.values() if flow.poll_task is not None]
    if store._callback_server_stop_task is not None:
        tasks.append(store._callback_server_stop_task)
    await store.reset()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    assert all(task.done() for task in tasks)
    assert store._callback_server is None
    await http_module.close_http_client()


async def _seed(harness, flow_id="synthetic-browser", state=STATE, **kwargs):
    record = oauth_module.OAuthFlowRecord(
        flow_id=flow_id,
        method="browser",
        status="pending",
        state_token=state,
        code_verifier=VERIFIER,
        **kwargs,
    )
    await harness.service._persist_flow_record(record)
    return record


async def _rows():
    async with SessionLocal() as session:
        return (await session.scalars(select(OAuthFlowState))).all()


@pytest.mark.parametrize("kind", ["refused", "timeout", "disconnect", "payload", "success", "provider", "invalid"])
@pytest.mark.parametrize("keep_other", [False, True])
async def test_public_callback_transport(transport_harness, unused_tcp_port, caplog, kind, keep_other):
    h = transport_harness
    await _seed(h)
    if keep_other:
        await _seed(h, "other-flow", "other-state")
        await h.service.oauth_status("other-flow")
    h.outcome["kind"] = kind
    expected = TRANSPORT_MESSAGE
    if kind == "provider":
        h.outcome.update(status=400, body={"error": "invalid_grant", "error_description": "Code expired"})
        expected = "Code expired"
    elif kind == "invalid":
        h.outcome["body"] = {}
        expected = "OAuth response missing tokens"
    server = oauth_module.OAuthCallbackServer(h.service._handle_callback, port=unused_tcp_port)
    h.store._callback_server = server
    await server.start()
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(
                f"http://127.0.0.1:{unused_tcp_port}/auth/callback", params={"code": CODE, "state": STATE}
            ) as response:
                body = await response.text()
                assert response.status == 200
        assert ("Signed in to Codex LB" if kind == "success" else "Login failed") in body
        status = await h.api.get("/api/oauth/status", params={"flowId": "synthetic-browser"})
        assert status.status_code == 200
        assert status.json()["status"] == ("success" if kind == "success" else "error")
        if kind != "success":
            assert expected in body
            assert status.json()["errorMessage"] == expected
        async with SessionLocal() as session:
            record = await OAuthFlowRepository(session, TokenEncryptor()).get_by_flow_id("synthetic-browser")
            assert record is not None and record.status == status.json()["status"]
            count = await session.scalar(select(func.count()).select_from(Account))
            assert count == (1 if kind == "success" else 0)
        replica = oauth_module.OauthService(h.service._accounts_repo, store=oauth_module.OAuthStateStore())
        assert (await replica.oauth_status("synthetic-browser")).status == status.json()["status"]
        for _ in range(100):
            if keep_other or h.store._callback_server is None:
                break
            await asyncio.sleep(0.01)
        assert (h.store._callback_server is server) == keep_other
        assert len(h.calls) == 1
        sent = parse_qs(h.calls[0][2]["data"])
        assert sent["code"] == [CODE] and sent["code_verifier"] == [VERIFIER]
        for secret in (CODE, STATE, VERIFIER, SECRET, "oauth.invalid"):
            assert secret not in body + caplog.text + json.dumps(status.json())
        assert "Traceback" not in caplog.text
    finally:
        await server.stop()


@pytest.mark.parametrize(
    "kind",
    [
        "refused",
        "timeout",
        "disconnect",
        "payload",
        "success",
        "provider",
        "invalid",
        "cancel",
        "systemexit",
        "unknown",
    ],
)
async def test_public_device_start_transport(transport_harness, caplog, kind):
    h = transport_harness
    await _seed(h)
    await h.service.oauth_status("synthetic-browser")
    h.outcome["kind"] = kind
    if kind == "provider":
        h.outcome.update(status=404, body={})
    elif kind == "invalid":
        h.outcome["body"] = {}
    if kind in ("cancel", "systemexit", "unknown"):
        h.api._transport.raise_app_exceptions = True
        expected_exception = {"cancel": asyncio.CancelledError, "systemexit": SystemExit, "unknown": RuntimeError}[kind]
        with pytest.raises(expected_exception):
            await h.api.post("/api/oauth/start", json={"forceMethod": "device"})
    else:
        response = await h.api.post("/api/oauth/start", json={"forceMethod": "device"})
        if kind == "success":
            assert response.status_code == 200
            assert response.json()["method"] == "device"
            assert response.json()["userCode"] == "SYNTHETIC-USER-CODE"
        else:
            assert response.status_code == 502
            if kind in ("refused", "timeout", "disconnect", "payload"):
                assert response.json() == {"error": {"code": "transport_error", "message": TRANSPORT_MESSAGE}}
                for secret in (CODE, STATE, VERIFIER, SECRET, "oauth.invalid"):
                    assert secret not in response.text + caplog.text
                assert "Traceback" not in caplog.text
            else:
                assert response.json()["error"]["code"] == (
                    "device_auth_unavailable" if kind == "provider" else "invalid_response"
                )
    rows = await _rows()
    assert len(rows) == (2 if kind == "success" else 1)
    assert next(row for row in rows if row.flow_id == "synthetic-browser").status == "pending"
    if kind != "success":
        assert not any(flow.poll_task is not None for flow in h.store._flows.values())
        async with SessionLocal() as session:
            assert await session.scalar(select(func.count()).select_from(OAuthDeviceFlowSlot)) == 0
            assert await session.scalar(select(func.count()).select_from(Account)) == 0
    assert len([call for call in h.calls if call[1].endswith("/usercode")]) == 1


@pytest.mark.parametrize("kind", ["cancel", "unknown"])
async def test_public_callback_does_not_normalize_unknown_or_cancel(transport_harness, unused_tcp_port, kind):
    h = transport_harness
    await _seed(h)
    h.outcome["kind"] = kind
    server = oauth_module.OAuthCallbackServer(h.service._handle_callback, port=unused_tcp_port)
    await server.start()
    try:
        # A single native HTTP request avoids the aiohttp client's GET replay
        # after a server disconnect. Cancellation must produce no success page.
        reader, writer = await asyncio.open_connection("127.0.0.1", unused_tcp_port)
        try:
            writer.write(
                f"GET /auth/callback?code={CODE}&state={STATE} HTTP/1.1\r\n"
                "Host: localhost\r\nConnection: close\r\n\r\n".encode()
            )
            await writer.drain()
            body = await asyncio.wait_for(reader.read(), timeout=5)
            if kind == "unknown":
                assert body.startswith(b"HTTP/1.1 500")
            else:
                assert body == b""
            assert b"Signed in" not in body
        finally:
            writer.close()
            await writer.wait_closed()
    finally:
        await server.stop()
    assert (await _rows())[0].status == "pending"
    assert len(h.calls) == 1


@pytest.mark.parametrize("surface", ["callback", "manual"])
async def test_transport_loser_honors_durable_success(transport_harness, unused_tcp_port, surface):
    h = transport_harness
    await _seed(h)
    h.outcome["kind"] = "refused"

    async def concurrent_success():
        await h.service._set_success("synthetic-browser")

    h.outcome["durable_success"] = concurrent_success
    if surface == "manual":
        response = await h.api.post(
            "/api/oauth/manual-callback",
            json={"flowId": "synthetic-browser", "callbackUrl": f"http://localhost/?code={CODE}&state={STATE}"},
        )
        assert response.status_code == 200 and response.json()["status"] == "success"
    else:
        server = oauth_module.OAuthCallbackServer(h.service._handle_callback, port=unused_tcp_port)
        await server.start()
        try:
            async with aiohttp.ClientSession() as client:
                async with client.get(
                    f"http://127.0.0.1:{unused_tcp_port}/auth/callback", params={"code": CODE, "state": STATE}
                ) as response:
                    assert response.status == 200 and "Signed in to Codex LB" in await response.text()
        finally:
            await server.stop()
    assert (await _rows())[0].status == "success"
    assert len(h.calls) == 1


async def test_public_manual_callback_transport_is_known_error(transport_harness, caplog):
    h = transport_harness
    await _seed(h)
    h.outcome["kind"] = "refused"
    response = await h.api.post(
        "/api/oauth/manual-callback",
        json={"flowId": "synthetic-browser", "callbackUrl": f"http://localhost/?code={CODE}&state={STATE}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "error", "errorMessage": TRANSPORT_MESSAGE}
    assert (await _rows())[0].error_message == TRANSPORT_MESSAGE
    assert "manual OAuth callback failed" not in caplog.text
    assert SECRET not in response.text + caplog.text


@pytest.mark.parametrize("case", ["state_mismatch", "expired", "denied"])
async def test_public_callback_guards_do_not_open_provider_connection(transport_harness, unused_tcp_port, case):
    from datetime import timedelta

    from app.core.utils.time import utcnow

    h = transport_harness
    if case == "expired":
        await _seed(h, expires_at=utcnow() - timedelta(seconds=1))
    else:
        await _seed(h)
    server = oauth_module.OAuthCallbackServer(h.service._handle_callback, port=unused_tcp_port)
    await server.start()
    params = {"code": CODE, "state": "unmatched-state" if case == "state_mismatch" else STATE}
    if case == "denied":
        params["error"] = "access_denied"
    try:
        async with aiohttp.ClientSession() as client:
            async with client.get(f"http://127.0.0.1:{unused_tcp_port}/auth/callback", params=params) as response:
                assert response.status == 200
                assert "Signed in to Codex LB" not in await response.text()
    finally:
        await server.stop()
    assert h.calls == []
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(Account)) == 0
