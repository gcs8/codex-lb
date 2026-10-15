"""Issue #2602 coverage using real ASGI routing and disposable SQLite state."""

from __future__ import annotations

import base64
import json
import time
from collections import Counter
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete, select, update

import app.core.openai.model_refresh_scheduler as model_refresh_module
import app.modules.proxy.service as proxy_module
import app.modules.usage.updater as updater_module
from app.core.openai.model_registry import get_model_registry
from app.core.usage import capacity_for_plan
from app.core.usage.models import UsagePayload
from app.core.usage.refresh_scheduler import UsageRefreshScheduler
from app.db.models import Account, AccountStatus, ApiKeyUsageReservation, RequestLog, UsageHistory
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.accounts.auth_manager import AuthManager
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.proxy.load_balancer import RuntimeState
from app.modules.usage.repository import UsageRepository

pytestmark = [pytest.mark.integration, pytest.mark.usage_refresh_request_path]

_ALIAS = "self_serve_business_prolite"


def _at(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, timezone.utc).replace(tzinfo=None)


async def _import(async_client, upstream_id: str, plan: str = _ALIAS) -> str:
    claims = {
        "email": f"{upstream_id}@example.test",
        "chatgpt_account_id": upstream_id,
        "https://api.openai.com/auth": {"chatgpt_plan_type": plan},
    }
    encoded = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    auth = {
        "tokens": {
            "idToken": f"header.{encoded}.sig",
            "accessToken": "synthetic-access",
            "refreshToken": "synthetic-refresh",
            "accountId": upstream_id,
        }
    }
    response = await async_client.post(
        "/api/accounts/import", files={"auth_json": ("auth.json", json.dumps(auth), "application/json")}
    )
    assert response.status_code == 200
    return response.json()["accountId"]


async def _stored(account_id: str) -> Account:
    async with SessionLocal() as session:
        account = await session.get(Account, account_id)
        assert account is not None
        return account


@pytest.fixture
def upstream(monkeypatch):
    state = {"used": 1.0, "reset": int(time.time()) + 604800}

    async def fetch_usage(**kwargs):
        assert kwargs["access_token"] == "synthetic-access"
        return UsagePayload.model_validate(
            {
                "plan_type": _ALIAS,
                "rate_limit": {
                    "primary_window": {
                        "used_percent": state["used"],
                        "reset_at": state["reset"],
                        "limit_window_seconds": 604800,
                    },
                    "secondary_window": {"used_percent": 0, "reset_at": None, "limit_window_seconds": 0},
                },
            }
        )

    async def ensure_fresh(self, account, *, force=False):
        return account

    monkeypatch.setattr(updater_module, "fetch_usage", fetch_usage)
    monkeypatch.setattr(AuthManager, "ensure_fresh", ensure_fresh)
    return state


@pytest.mark.asyncio
async def test_import_business_prolite_is_canonical(async_client, upstream):
    account_id = await _import(async_client, "business-import")
    account = await _stored(account_id)
    assert account.plan_type == "prolite"
    assert capacity_for_plan(_ALIAS, "primary") == capacity_for_plan("prolite", "primary")
    assert capacity_for_plan(_ALIAS, "secondary") == capacity_for_plan("prolite", "secondary")


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["/backend-api/codex/responses", "/v1/responses"])
@pytest.mark.parametrize("stored_plan", [_ALIAS, "prolite"])
async def test_weekly_reset_refresh_allows_same_account_public_request(
    async_client, monkeypatch, upstream, route, stored_plan
):
    account_id = await _import(async_client, "business-weekly")
    now = int(time.time())
    blocked_at = now - 600
    deadline = now + 259200
    async with SessionLocal() as session:
        await session.execute(update(Account).where(Account.id == account_id).values(plan_type=stored_plan))
        await session.commit()
    account = await _stored(account_id)
    service = get_proxy_service_for_app(async_client._transport.app)
    # Exercise the real 429 classifier and durable block writer, then let its
    # local retry debounce elapse. Do not replace selection or status writes.
    result = await service._handle_stream_error(
        account,
        {"message": "You've hit your usage limit.", "resets_in_seconds": 259200},
        "usage_limit_reached",
        429,
    )
    assert result["failure_class"] == "rate_limit"
    async with SessionLocal() as session:
        await session.execute(update(Account).where(Account.id == account_id).values(blocked_at=blocked_at))
        await session.commit()
    before = await _stored(account_id)
    assert before.status == AccountStatus.RATE_LIMITED
    assert before.reset_at is not None and before.reset_at >= deadline
    deadline = before.reset_at
    service._load_balancer._runtime[account_id] = RuntimeState(
        blocked_at=float(blocked_at), cooldown_until=now - 1, reset_at=float(deadline)
    )

    # The payload shape reported by #2602: a weekly window in primary, with an
    # empty secondary placeholder. Actual updater persistence canonicalizes a
    # historical raw plan and records a fresh available weekly observation.
    upstream.update(used=1.0, reset=now - 60 + 604800)
    updater = updater_module.build_background_usage_updater()
    assert await updater.force_refresh(before)
    refreshed = await _stored(account_id)
    assert refreshed.plan_type == "prolite"
    # Poll success alone must not erase an unexpired hard 429 marker.
    assert refreshed.status == AccountStatus.RATE_LIMITED
    async with SessionLocal() as session:
        usage = UsageRepository(session)
        weekly = await usage.latest_entry_for_account(account_id, window="primary")
        assert weekly is not None
        assert (weekly.used_percent, weekly.window_minutes, weekly.reset_at) == (1.0, 10080, upstream["reset"])
        assert (weekly.credits_has, weekly.credits_unlimited, weekly.credits_balance) == (None, None, None)

    # Select a supported ID from the shipped catalog, not the reporter's model
    # name. Refresh the real persisted registry after recovery below.
    registry = get_model_registry()
    model = next(item for item in registry.get_models_with_fallback().values() if "pro" in item.available_in_plans)
    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        seen.append(account_id)
        assert payload.model == model.slug
        yield (
            'data: {"type":"response.completed","response":{"id":"resp_business",'
            '"usage":{"input_tokens":2,"output_tokens":1,"total_tokens":3}}}\n\n'
        )

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    settings = await async_client.put("/api/settings", json={"apiKeyAuthEnabled": True})
    assert settings.status_code == 200
    created = await async_client.post(
        "/api/api-keys/",
        json={
            "name": "business recovery",
            "assignedAccountIds": [account_id],
            "limits": [{"limitType": "total_tokens", "limitWindow": "weekly", "maxValue": 1000000}],
        },
    )
    assert created.status_code == 200
    key = created.json()
    headers = {"Authorization": f"Bearer {key['key']}"}
    settlements = []
    original_settle = ApiKeysRepository.settle_usage_reservation

    async def settle(self, reservation_id, **kwargs):
        settlements.append(reservation_id)
        return await original_settle(self, reservation_id, **kwargs)

    monkeypatch.setattr(ApiKeysRepository, "settle_usage_reservation", settle)
    response = await async_client.post(
        route, headers=headers, json={"model": model.slug, "input": "synthetic", "stream": True}
    )
    assert response.status_code == 200
    assert '"type":"response.completed"' in response.text
    assert seen == ["business-weekly"]
    recovered = await _stored(account_id)
    assert (recovered.status, recovered.reset_at, recovered.blocked_at, recovered.deactivation_reason) == (
        AccountStatus.ACTIVE,
        None,
        None,
        None,
    )

    fetched = []

    async def fetch_models(access_token, upstream_account_id, **kwargs):
        fetched.append(upstream_account_id)
        return [model]

    monkeypatch.setattr(model_refresh_module, "fetch_models_for_plan", fetch_models)
    scheduler = model_refresh_module.ModelRefreshScheduler(interval_seconds=300, enabled=True)
    await scheduler._refresh_once()
    assert fetched == ["business-weekly"]
    snapshot = registry.get_snapshot()
    assert snapshot is not None
    assert model.slug in snapshot.plan_models["prolite"]
    assert registry.account_ids_for_model(model.slug) == frozenset({account_id})
    response = await async_client.post(
        route, headers=headers, json={"model": model.slug, "input": "synthetic again", "stream": True}
    )
    assert response.status_code == 200
    assert '"type":"response.completed"' in response.text
    assert seen == ["business-weekly", "business-weekly"]
    assert len(settlements) == 2
    assert set(Counter(settlements).values()) == {1}
    async with SessionLocal() as session:
        reservations = (await session.scalars(select(ApiKeyUsageReservation))).all()
        logs = (await session.scalars(select(RequestLog).where(RequestLog.api_key_id == key["id"]))).all()
    assert {row.id for row in reservations} == set(settlements)
    assert {(row.status, row.input_tokens, row.output_tokens) for row in reservations} == {("finalized", 2, 1)}
    assert len(logs) == 2
    assert {row.account_id for row in logs} == {account_id}


@pytest.mark.asyncio
@pytest.mark.parametrize("sample", ["old", "same-second", "expired", "fresh", "paused", "deactivated"])
async def test_weekly_only_public_recovery_requires_applicable_post_block_sample(
    async_client, monkeypatch, upstream, sample
):
    account_id = await _import(async_client, "business-evidence")
    now = int(time.time())
    blocked_at = now - 600
    deadline = now + 259200
    status = {"paused": AccountStatus.PAUSED, "deactivated": AccountStatus.DEACTIVATED}.get(
        sample, AccountStatus.RATE_LIMITED
    )
    recorded_at = blocked_at - 1 if sample == "old" else blocked_at + 0.9 if sample == "same-second" else now - 1
    async with SessionLocal() as session:
        await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(status=status, reset_at=deadline, blocked_at=blocked_at, deactivation_reason=None)
        )
        await session.execute(delete(UsageHistory).where(UsageHistory.account_id == account_id))
        await session.commit()
        usage = UsageRepository(session)
        # A prior, expired short-window row is not an applicable exhausted
        # quota. It must neither prevent recovery nor prove fresh availability.
        await usage.add_entry(
            account_id,
            100.0,
            window="primary",
            reset_at=blocked_at - 1,
            window_minutes=300,
            recorded_at=_at(blocked_at - 10),
        )
        await usage.add_entry(
            account_id,
            1.0,
            window="secondary",
            reset_at=now - 1 if sample == "expired" else now + 604800,
            window_minutes=10080,
            recorded_at=_at(recorded_at),
        )
    service = get_proxy_service_for_app(async_client._transport.app)
    service._load_balancer._runtime[account_id] = RuntimeState(
        blocked_at=float(blocked_at), cooldown_until=now - 1, reset_at=float(deadline)
    )
    registry = get_model_registry()
    model = next(item for item in registry.get_models_with_fallback().values() if "pro" in item.available_in_plans)
    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        seen.append(account_id)
        yield 'data: {"type":"response.completed","response":{"id":"resp_evidence"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    response = await async_client.post(
        "/v1/responses", json={"model": model.slug, "input": "synthetic", "stream": True}
    )
    account = await _stored(account_id)
    if sample == "fresh":
        assert response.status_code == 200
        assert '"type":"response.completed"' in response.text
        assert seen == ["business-evidence"]
        assert (account.status, account.reset_at, account.blocked_at, account.deactivation_reason) == (
            AccountStatus.ACTIVE,
            None,
            None,
            None,
        )
    else:
        assert '"type":"response.completed"' not in response.text
        assert seen == []
        assert (account.status, account.reset_at, account.blocked_at, account.deactivation_reason) == (
            status,
            deadline,
            blocked_at,
            None,
        )


@pytest.mark.asyncio
async def test_persisted_weekly_reset_recovers_after_scheduler_restart(async_client, monkeypatch, upstream):
    account_id = await _import(async_client, "business-restart")
    now = int(time.time())
    blocked_at = now - 7200
    deadline = now + 259200
    async with SessionLocal() as session:
        await session.execute(
            update(Account)
            .where(Account.id == account_id)
            .values(plan_type=_ALIAS, status=AccountStatus.RATE_LIMITED, blocked_at=blocked_at, reset_at=deadline)
        )
        await session.execute(delete(UsageHistory).where(UsageHistory.account_id == account_id))
        await session.commit()
        await UsageRepository(session).add_entry(
            account_id, 100.0, window="primary", reset_at=deadline, window_minutes=10080, recorded_at=_at(now - 3600)
        )
    upstream.update(used=0.0, reset=now - 60 + 604800)
    settings = await async_client.put("/api/settings", json={"limitWarmupEnabled": False})
    assert settings.status_code == 200
    # A fresh scheduler owns no in-memory pair or marking-replica state. It
    # must fetch, persist, resolve the real history and CAS the same account.
    scheduler = UsageRefreshScheduler(interval_seconds=60, enabled=True)
    await scheduler._refresh_once()
    account = await _stored(account_id)
    assert account.plan_type == "prolite"
    assert (account.status, account.reset_at, account.blocked_at, account.deactivation_reason) == (
        AccountStatus.ACTIVE,
        None,
        None,
        None,
    )
    model = next(
        item for item in get_model_registry().get_models_with_fallback().values() if "pro" in item.available_in_plans
    )
    seen = []

    async def stream(payload, headers, access_token, account_id, **kwargs):
        seen.append(account_id)
        yield 'data: {"type":"response.completed","response":{"id":"resp_restart"}}\n\n'

    monkeypatch.setattr(proxy_module, "core_stream_responses", stream)
    response = await async_client.post(
        "/v1/responses", json={"model": model.slug, "input": "synthetic restart", "stream": True}
    )
    assert response.status_code == 200
    assert '"type":"response.completed"' in response.text
    assert seen == ["business-restart"]
