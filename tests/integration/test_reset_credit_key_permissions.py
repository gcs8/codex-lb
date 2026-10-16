from __future__ import annotations

import base64
import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import text

from app.core.auth import generate_unique_account_id
from app.core.clients.rate_limit_reset_credits import RateLimitResetCreditsSnapshot, ResetCreditItem
from app.db.session import SessionLocal
from app.modules.rate_limit_reset_credits.store import get_rate_limit_reset_credits_store

pytestmark = pytest.mark.integration


async def _snapshot():
    async with SessionLocal() as session:
        # Authentication can record last_used_at; the redemption domain cannot mutate.
        tables = ("accounts", "reset_credit_redeem_claims", "reset_credit_redeem_requests", "usage_history")
        result = {}
        for table in tables:
            result[table] = (await session.execute(text(f'SELECT * FROM "{table}"'))).all()
        return result


@pytest.mark.asyncio
async def test_default_key_denied_before_redemption_and_get_unaffected(async_client, monkeypatch):
    import app.modules.proxy.api as proxy_api

    claims = {
        "email": "fixture@example.com",
        "chatgpt_account_id": "fixture-account",
        "https://api.openai.com/auth": {"chatgpt_plan_type": "plus"},
    }
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    auth = {
        "tokens": {
            "idToken": f"header.{body}.sig",
            "accessToken": "synthetic-access",
            "refreshToken": "synthetic-refresh",
            "accountId": "fixture-account",
        }
    }
    imported = await async_client.post(
        "/api/accounts/import", files={"auth_json": ("fixture.json", json.dumps(auth), "application/json")}
    )
    assert imported.status_code == 200
    account_id = generate_unique_account_id("fixture-account", "fixture@example.com")
    store = get_rate_limit_reset_credits_store()
    snapshot = RateLimitResetCreditsSnapshot(
        available_count=1,
        nearest_expires_at=None,
        credits=[ResetCreditItem(id="credit", status="available", expires_at=None)],
    )
    await store.set(account_id, snapshot)
    created = await async_client.post(
        "/api/api-keys/", json={"name": "arbitrary-writer-name", "assignedAccountIds": [account_id]}
    )
    assert created.status_code == 200
    key = created.json()["key"]
    headers = {"Authorization": f"Bearer {key}"}
    before = await _snapshot()
    fetch = AsyncMock(side_effect=AssertionError("must not fetch"))
    consume = AsyncMock(side_effect=AssertionError("must not consume"))
    lookup = AsyncMock(side_effect=AssertionError("must not look up account"))
    monkeypatch.setattr(proxy_api, "_fetch_authoritative_reset_credit", fetch)
    monkeypatch.setattr(proxy_api, "consume_reset_credit", consume)
    monkeypatch.setattr(proxy_api.AccountsRepository, "get_by_id", lookup)
    response = await async_client.post(
        "/v1/reset-credit", headers=headers, json={"account_id": account_id, "redeem_id": "credit"}
    )
    assert response.status_code == 403
    assert response.json() == {
        "error": {
            "message": "API key cannot redeem reset credits",
            "type": "permission_error",
            "code": "reset_credit_redeem_forbidden",
        }
    }
    fetch.assert_not_awaited()
    consume.assert_not_awaited()
    lookup.assert_not_awaited()
    assert await _snapshot() == before
    assert store.get(account_id) == snapshot
    read = await async_client.get("/v1/reset-credit", headers=headers)
    assert read.status_code == 200
    assert read.json() == [
        {"account_id": account_id, "email": "fixture@example.com", "redeem_id": "credit", "expiredAt": None}
    ]
    await store.invalidate()
    assert created.json()["allowResetCreditRedeem"] is False


@pytest.mark.asyncio
async def test_permission_update_omission_and_regeneration(async_client):
    created = await async_client.post("/api/api-keys", json={"name": "monitor", "allowResetCreditRedeem": True})
    assert created.status_code == 200
    key_id = created.json()["id"]
    assert created.json()["allowResetCreditRedeem"] is True
    for payload, expected in [
        ({"name": "renamed"}, True),
        ({"unknownPermission": True}, True),
        ({"allowResetCreditRedeem": False}, False),
        ({}, False),
    ]:
        updated = await async_client.patch(f"/api/api-keys/{key_id}", json=payload)
        assert updated.status_code == 200
        assert updated.json()["allowResetCreditRedeem"] is expected
    regenerated = await async_client.post(f"/api/api-keys/{key_id}/regenerate")
    assert regenerated.status_code == 200
    assert regenerated.json()["allowResetCreditRedeem"] is False
    listed = await async_client.get("/api/api-keys/")
    assert listed.json()[0]["allowResetCreditRedeem"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", [{"isActive": False}, {"expiresAt": "2020-01-01T00:00:00Z"}])
async def test_granted_permission_does_not_bypass_revocation_or_expiry(async_client, policy):
    created = await async_client.post("/api/api-keys/", json={"name": "monitor", "allowResetCreditRedeem": True})
    headers = {"Authorization": f"Bearer {created.json()['key']}"}
    assert (await async_client.get("/v1/reset-credit", headers=headers)).status_code == 200
    changed = await async_client.patch(f"/api/api-keys/{created.json()['id']}", json=policy)
    assert changed.status_code == 200
    for method, path, kwargs in [
        ("get", "/v1/reset-credit", {}),
        ("post", "/v1/reset-credit", {"json": {"account_id": "absent", "redeem_id": "credit"}}),
    ]:
        response = await getattr(async_client, method)(path, headers=headers, **kwargs)
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "invalid_api_key"


@pytest.mark.asyncio
async def test_cached_grant_is_revoked_by_permission_update(async_client, monkeypatch):
    import app.modules.proxy.api as proxy_api

    created = await async_client.post("/api/api-keys/", json={"name": "monitor", "allowResetCreditRedeem": True})
    headers = {"Authorization": f"Bearer {created.json()['key']}"}
    assert (await async_client.get("/v1/reset-credit", headers=headers)).status_code == 200
    changed = await async_client.patch(f"/api/api-keys/{created.json()['id']}", json={"allowResetCreditRedeem": False})
    assert changed.status_code == 200
    lookup = AsyncMock(side_effect=AssertionError("must not look up account"))
    monkeypatch.setattr(proxy_api.AccountsRepository, "get_by_id", lookup)
    response = await async_client.post(
        "/v1/reset-credit", headers=headers, json={"account_id": "absent", "redeem_id": "credit"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "reset_credit_redeem_forbidden"
    lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "true", "false", 1, 0, [], {}])
async def test_permission_rejects_non_boolean_without_update(async_client, value):
    created = await async_client.post("/api/api-keys/", json={"name": "strict"})
    key_id = created.json()["id"]
    for method, path, payload in [
        ("post", "/api/api-keys/", {"name": "bad", "allowResetCreditRedeem": value}),
        ("patch", f"/api/api-keys/{key_id}", {"allowResetCreditRedeem": value}),
    ]:
        response = await getattr(async_client, method)(path, json=payload)
        assert response.status_code == 422
    listed = await async_client.get("/api/api-keys/")
    assert len(listed.json()) == 1
    assert listed.json()[0]["allowResetCreditRedeem"] is False
