from __future__ import annotations

import time

import pytest

import app.modules.proxy.service as proxy_module
from app.dependencies import get_proxy_service_for_app
from app.modules.proxy.load_balancer import RuntimeState
from tests.integration.test_proxy_files import _import_account

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/v1/responses", "/backend-api/codex/responses"])
async def test_file_pinned_responses_admits_transient_backoff_without_crossing_accounts(
    async_client, monkeypatch, route: str
) -> None:
    owner_id = await _import_account(async_client, "backoff_file_owner", "backoff-owner@example.com")
    await _import_account(async_client, "backoff_file_alternate", "backoff-alternate@example.com")
    service = get_proxy_service_for_app(async_client._transport.app)
    await service._pin_file_account("file_backoff_owner", owner_id)
    last_error_at = time.time() - 1
    service._load_balancer._runtime[owner_id] = RuntimeState(error_count=5, last_error_at=last_error_at)
    dispatched: list[str] = []

    async def fake_stream(payload, headers, access_token, account_id, **kwargs):
        del headers, access_token, kwargs
        dispatched.append(account_id)
        assert payload.input[0]["content"][0]["file_id"] == "file_backoff_owner"
        # Selection must not reset backoff. Later successful settlement may do so.
        runtime = service._load_balancer._runtime[owner_id]
        assert runtime.error_count == 5
        assert runtime.last_error_at == last_error_at
        yield 'data: {"type":"response.completed","response":{"id":"resp_file_backoff"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", fake_stream)
    response = await async_client.post(
        route,
        headers={"session_id": "file-backoff-session"},
        json={
            "model": "gpt-5.2",
            "instructions": "Read the file.",
            "input": [{"role": "user", "content": [{"type": "input_file", "file_id": "file_backoff_owner"}]}],
            "prompt_cache_key": "soft-backoff-locality",
            "stream": True,
        },
    )
    assert response.status_code == 200
    assert '"type":"response.completed"' in response.text
    assert dispatched == ["backoff_file_owner"]
