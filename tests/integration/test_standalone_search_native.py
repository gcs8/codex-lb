"""Standalone search public routes with a real native HTTP producer.

Only synthetic upstream I/O is supplied. The success fixture is opaque JSON,
not evidence of provider search availability or a Codex result-schema contract.
"""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import pytest

from app.core.clients import codex as codex_client_module
from app.core.clients import proxy as client_proxy
from app.core.clients.native_egress import SubprocessNativeEgressClient
from app.core.config.settings import get_settings
from app.db.models import Account, AccountStatus
from app.db.session import SessionLocal
from tests.integration.test_http_responses_bridge import _import_account
from tests.integration.test_native_sse_egress import _serve_http

pytestmark = pytest.mark.integration
PATHS = ["/backend-api/codex/alpha/search", "/v1/alpha/search", "/backend-api/codex/v1/alpha/search"]
SUCCESS = (
    b'{\n "results": [{"title":"Synthetic fixture", "url":"https://example.invalid/search", '
    b'"snippet":"caf\xc3\xa9"}]\n}\n'
)
ERROR = {
    "error": {
        "code": "unsupported_value",
        "type": "invalid_request_error",
        "param": "commands",
        "message": "Synthetic search refusal",
    }
}


@pytest.fixture
async def search_native(monkeypatch, record_property):
    binary = os.environ.get("CODEX_LB_NATIVE_EGRESS_TEST_BINARY")
    if not binary:
        pytest.skip("set CODEX_LB_NATIVE_EGRESS_TEST_BINARY for native search wire coverage")
    native = SubprocessNativeEgressClient(Path(binary))
    monkeypatch.setattr(codex_client_module, "discover_native_egress_client", lambda: native)
    try:
        yield native
    finally:
        process, reader = native._process, native._reader_task
        await native.aclose()
        assert process is None or process.returncode is not None
        assert reader is None or reader.done()
        assert not native._streams
        record_property("native_child_reaped", process is not None and process.returncode is not None)


async def _setup(async_client, monkeypatch, upstream):
    owner = await _import_account(async_client, "acc_search_owner", "search-owner@example.com", plan_type="pro")
    sibling = await _import_account(async_client, "acc_search_sibling", "search-sibling@example.com", plan_type="pro")
    endpoint = await async_client.post(
        "/api/settings/upstream-proxy/endpoints",
        json={"name": "synthetic loopback", "scheme": "http", "host": "127.0.0.1", "port": urlsplit(upstream).port},
    )
    assert endpoint.status_code == 200, endpoint.text
    pool = await async_client.post(
        "/api/settings/upstream-proxy/pools", json={"name": "synthetic pool", "endpointIds": [endpoint.json()["id"]]}
    )
    assert pool.status_code == 200, pool.text
    binding = await async_client.put(
        f"/api/settings/upstream-proxy/accounts/{owner}/binding", json={"poolId": pool.json()["id"], "isActive": True}
    )
    assert binding.status_code == 200, binding.text
    key = await async_client.post(
        "/api/api-keys/", json={"name": "search-scoped", "assignedAccountIds": [owner], "enforcedModel": "gpt-5.4"}
    )
    assert key.status_code == 200, key.text
    enabled = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert enabled.status_code == 200
    settings = get_settings().model_copy(update={"upstream_base_url": upstream, "proxy_request_budget_seconds": 1.0})
    monkeypatch.setattr(client_proxy, "get_settings", lambda: settings)
    return owner, sibling, key.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
@pytest.mark.parametrize("status", [200, 400, 429])
@pytest.mark.parametrize("encoding", ["identity", "gzip", None])
async def test_standalone_search_real_native_wire(
    async_client, monkeypatch, search_native, record_property, path, status, encoding
):
    captured = []
    response_body = SUCCESS if status == 200 else json.dumps(ERROR, indent=2).encode()

    async def upstream(reader, writer, head, body):
        captured.append((head, body))
        encoded = gzip.compress(response_body, mtime=0) if encoding == "gzip" else response_body
        reason = {200: "OK", 400: "Bad Request", 429: "Too Many Requests"}[status]
        writer.write(
            f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json; charset=utf-8\r\n".encode()
            + b"X-Request-Id: synthetic-search\r\nSet-Cookie: must-not-leak=1\r\n"
            + (b"Content-Encoding: gzip\r\n" if encoding == "gzip" else b"")
            + f"Content-Length: {len(encoded)}\r\nConnection: close\r\n\r\n".encode()
        )
        for offset in range(0, len(encoded), 7):
            writer.write(encoded[offset : offset + 7])
            await writer.drain()

    async with _serve_http(upstream) as url:
        owner, sibling, key = await _setup(async_client, monkeypatch, url)
        payload = (
            '{ "id": "'
            + str(uuid4())
            + '", "model":"gpt-5.6", "commands":{"search_query":[{"q":"synthetic fixture"}]}}\n'
        ).encode()
        headers = {
            "authorization": "Bearer " + key["key"],
            "content-type": "application/json; charset=utf-8",
            "user-agent": "Codex Desktop/0.153.4",
            "session_id": "synthetic-search-session",
        }
        if encoding is not None:
            headers["accept-encoding"] = encoding
        else:
            # httpx otherwise supplies its own compression negotiation.
            async_client.headers.pop("accept-encoding", None)
        response = await async_client.post(path + "?result_count=1&tag=a&tag=b", content=payload, headers=headers)
        assert response.status_code == status, response.text
        if status == 200:
            assert response.content == SUCCESS
            assert response.json() == json.loads(SUCCESS)
            assert response.json()["results"]
            assert response.headers["x-request-id"] == "synthetic-search"
            assert response.headers["content-type"] == "application/json; charset=utf-8"
            assert "set-cookie" not in response.headers
            assert "content-encoding" not in response.headers
        else:
            assert response.json() == ERROR
        assert len(captured) == 1
        head, sent = captured[0]
        # Keep every field occurrence. Never collapse headers to a dictionary.
        fields = [line.partition(b":") for line in head.split(b"\r\n")[1:] if b":" in line]
        assert [(name, value.strip()) for name, _, value in fields if name.lower() == b"content-type"] == [
            (b"content-type", b"application/json; charset=utf-8")
        ]
        assert [value.strip() for name, _, value in fields if name.lower() == b"authorization"] == [
            b"Bearer access-token"
        ]
        assert [value.strip() for name, _, value in fields if name.lower() == b"chatgpt-account-id"] == [
            b"acc_search_owner"
        ]
        assert [value.strip() for name, _, value in fields if name.lower() == b"session_id"] == [
            b"synthetic-search-session"
        ]
        assert [value.strip() for name, _, value in fields if name.lower() == b"accept-encoding"] == (
            [encoding.encode()] if encoding is not None else []
        )
        record_property("native_request_head_hex", head.hex())
        record_property("native_request_body_hex", sent.hex())
        record_property("downstream_status", response.status_code)
        record_property("downstream_body_hex", response.content.hex())
        assert sent == payload
        assert (
            head.split(b"\r\n", 1)[0] == f"POST {url}/codex/alpha/search?result_count=1&tag=a&tag=b HTTP/1.1".encode()
        )
        assert key["key"].encode() not in head
        assert search_native._process is not None
        record_property("native_wire_dispatches", len(captured))


@pytest.mark.asyncio
@pytest.mark.parametrize("path", PATHS)
async def test_standalone_search_auth_scope_and_methods(async_client, monkeypatch, search_native, path):
    captured = []

    async def upstream(reader, writer, head, body):
        captured.append((head, body))
        writer.write(
            b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}"
        )
        await writer.drain()

    async with _serve_http(upstream) as url:
        owner, sibling, key = await _setup(async_client, monkeypatch, url)
        for auth in [None, "Bearer synthetic-invalid"]:
            response = await async_client.post(path, json={}, headers={"authorization": auth} if auth else {})
            assert response.status_code == 401
            assert response.json()["error"]["code"] == "invalid_api_key"
        headers = {"authorization": "Bearer " + key["key"]}
        for method, expected_status in [
            ("GET", 404),
            ("HEAD", 405),
            ("PUT", 405),
            ("DELETE", 405),
            ("OPTIONS", 405),
            ("PATCH", 405),
        ]:
            response = await async_client.request(method, path, headers=headers, follow_redirects=False)
            # The app's GET dashboard catch-all owns unknown API GET paths.
            assert response.status_code == expected_status
        slash = await async_client.post(path + "/", json={}, headers=headers, follow_redirects=False)
        assert slash.status_code == 405
        # Account scope must not fall through to the active, unassigned sibling.
        async with SessionLocal() as session:
            account = await session.get(Account, owner)
            assert account is not None
            account.status = AccountStatus.PAUSED
            await session.commit()
        denied = await async_client.post(path, json={}, headers=headers)
        assert denied.status_code == 503, denied.text
        assert denied.json()["error"]["code"] == "no_accounts"
        assert not captured
        assert search_native._process is None
