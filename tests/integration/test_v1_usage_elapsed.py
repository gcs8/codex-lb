from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core.utils.time import naive_utc_to_epoch
from app.db.models import Account, AccountStatus, ApiKey, UsageHistory
from app.db.session import SessionLocal
from app.dependencies import get_proxy_service_for_app
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService

pytestmark = pytest.mark.integration
NOW = datetime(2030, 1, 15, 12)
EPOCH = naive_utc_to_epoch(NOW)


@pytest.fixture
def fixed_clock(monkeypatch):
    monkeypatch.setattr("app.modules.proxy.api.utcnow", lambda: NOW, raising=False)
    monkeypatch.setattr("time.time", lambda: float(EPOCH))


def _account(account_id: str, plan: str) -> Account:
    return Account(
        id=account_id,
        email=f"{account_id}@example.invalid",
        chatgpt_account_id=f"workspace-{account_id}",
        plan_type=plan,
        access_token_encrypted=b"synthetic",
        refresh_token_encrypted=b"synthetic",
        id_token_encrypted=b"synthetic",
        last_refresh=NOW,
        status=AccountStatus.ACTIVE,
    )


async def _seed(window: str, *, offset: int | None, duration: int | None, live: bool = True) -> None:
    plan = "free" if window == "monthly" else "plus"
    async with SessionLocal() as session:
        session.add(_account("silent", plan))
        if live:
            session.add(_account("live", plan))
        await session.flush()
        session.add(
            UsageHistory(
                account_id="silent",
                window=window,
                recorded_at=NOW - timedelta(days=30),
                used_percent=100.0,
                reset_at=None if offset is None else EPOCH + offset,
                window_minutes=duration,
            )
        )
        if live:
            session.add(
                UsageHistory(
                    account_id="live",
                    window=window,
                    recorded_at=NOW,
                    used_percent=20.0,
                    reset_at=EPOCH + 3600,
                    window_minutes={"primary": 300, "secondary": 10080, "monthly": 43200}[window],
                )
            )
        await session.commit()


async def _key(*, assigned: list[str] | None = None, empty_scope: bool = False) -> str:
    async with SessionLocal() as session:
        created = await ApiKeysService(ApiKeysRepository(session)).create_key(
            ApiKeyCreateData(name="elapsed-fixture", allowed_models=None, assigned_account_ids=assigned or [])
        )
        if empty_scope:
            row = await session.get(ApiKey, created.id)
            assert row is not None
            row.account_assignment_scope_enabled = True
            await session.commit()
        return created.key


async def _raw_rows() -> list[tuple]:
    async with SessionLocal() as session:
        return [
            (r.id, r.account_id, r.window, r.used_percent, r.reset_at, r.window_minutes, r.recorded_at)
            for r in (await session.execute(select(UsageHistory).order_by(UsageHistory.id))).scalars()
        ]


def _iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


@pytest.mark.parametrize(("window", "label", "capacity"), [("primary", "5h", 225), ("monthly", "monthly", 1134)])
@pytest.mark.parametrize("offset", [-21 * 86400, 0, 1, None])
@pytest.mark.parametrize("duration", [None, 0, 300])
async def test_elapsed_aggregate_projection_boundary_and_raw_retention(
    async_client, fixed_clock, window, label, capacity, offset, duration
):
    await _seed(window, offset=offset, duration=duration)
    key = await _key()
    before = await _raw_rows()
    response = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    payload = response.json()
    expired = offset is not None and offset <= 0
    current = round(capacity * (0.2 if expired else 1.2))
    reset = EPOCH + 3600 if offset is None or expired else EPOCH + offset
    assert payload["upstream_limits"] == [
        {
            "limit_type": "credits",
            "limit_window": label,
            "max_value": capacity * 2,
            "current_value": current,
            "remaining_value": capacity * 2 - current,
            "model_filter": None,
            "reset_at": _iso(reset),
            "source": "aggregate",
        }
    ]
    assert payload["limits"] == payload["upstream_limits"]
    assert payload["request_count"] == payload["total_tokens"] == payload["cached_input_tokens"] == 0
    assert payload["total_cost_usd"] == 0.0
    assert await _raw_rows() == before


@pytest.mark.parametrize(("window", "duration"), [("primary", 300), ("monthly", 43200)])
@pytest.mark.parametrize("offset", [-1, 0, None])
async def test_all_elapsed_or_unknown_reset_windows_are_not_fabricated(
    async_client, fixed_clock, window, duration, offset
):
    await _seed(window, offset=offset, duration=duration, live=False)
    key = await _key()
    before = await _raw_rows()
    response = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    assert response.json()["upstream_limits"] == response.json()["limits"] == []
    assert await _raw_rows() == before


@pytest.mark.parametrize("weekly_primary", [False, True])
async def test_secondary_raw_policy_and_header_comparator(async_client, app_instance, fixed_clock, weekly_primary):
    await _seed("primary" if weekly_primary else "secondary", offset=-21 * 86400, duration=10080, live=False)
    key = await _key()
    before = await _raw_rows()
    response = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    assert response.json()["upstream_limits"] == [
        {
            "limit_type": "credits",
            "limit_window": "7d",
            # One Plus account, weekly = 7,560/month x 7/30 (gcs8/codex-lb#7).
            "max_value": 1764,
            "current_value": 1764,
            "remaining_value": 0,
            "model_filter": None,
            "reset_at": _iso(EPOCH - 21 * 86400),
            "source": "aggregate",
        }
    ]
    assert response.json()["account_pool_usage"] == {"primary": None, "secondary": 0.0}
    # Native headers already expire weekly display rows. That is not admission policy.
    service = get_proxy_service_for_app(app_instance)
    headers = await service._compute_rate_limit_headers()
    assert headers["x-codex-secondary-used-percent"] == "0.0"
    assert "x-codex-primary-used-percent" not in headers
    assert await _raw_rows() == before


@pytest.mark.parametrize(
    ("assignment", "expected_primary"), [(None, 90.0), (["silent"], None), (["live"], 80.0), ([], None)]
)
async def test_projection_preserves_assignment_pool_contract(async_client, fixed_clock, assignment, expected_primary):
    await _seed("primary", offset=-86400, duration=300)
    key = await _key(assigned=assignment, empty_scope=assignment == [])
    response = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    payload = response.json()
    # This existing section is explicitly global; only account_pool_usage is assignment scoped.
    assert payload["upstream_limits"][0]["reset_at"] == _iso(EPOCH + 3600)
    assert payload["upstream_limits"][0]["current_value"] == 45
    assert payload["account_pool_usage"]["primary"] == expected_primary
    if assignment == []:
        assert payload["account_pool_usage"] == {"primary": None, "secondary": None}


@pytest.mark.parametrize("path", ["/api/codex/usage", "/api/codex/usage/"])
async def test_native_api_key_usage_does_not_borrow_global_aggregate(async_client, fixed_clock, path):
    await _seed("primary", offset=-86400, duration=300)
    key = await _key()
    response = await async_client.get(path, headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    assert response.json()["plan_type"] == "api_key"
    assert response.json()["rate_limit"] is None
    assert response.json()["credits"] is None


async def test_hidden_elapsed_aggregate_and_unpromised_v1_trailing_slash(async_client, fixed_clock):
    await _seed("primary", offset=-86400, duration=300)
    key = await _key()
    setting = await async_client.put("/api/settings", json={"hideUpstreamQuotaFromApiKeys": True})
    assert setting.status_code == 200
    response = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    assert response.json()["upstream_limits"] == response.json()["limits"] == []
    assert response.json()["account_pool_usage"] is None
    slash = await async_client.get("/v1/usage/", headers={"Authorization": f"Bearer {key}"}, follow_redirects=False)
    # No equivalent trailing-slash v1 route is promised by the owning capability.
    assert slash.status_code == 404
    assert slash.json()["error"]["code"] == "not_found"


async def test_secondary_silent_reset_still_requires_owner_policy(async_client, fixed_clock):
    await _seed("secondary", offset=-21 * 86400, duration=10080)
    key = await _key()
    before = await _raw_rows()
    response = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    # Intentionally unresolved: expiring this row would advertise free weekly credits.
    assert response.json()["upstream_limits"] == [
        {
            "limit_type": "credits",
            "limit_window": "7d",
            # Two Plus accounts at 1,764 weekly each, 60 % used (gcs8/codex-lb#7).
            "max_value": 3528,
            "current_value": 2117,
            "remaining_value": 1411,
            "model_filter": None,
            "reset_at": _iso(EPOCH - 21 * 86400),
            "source": "aggregate",
        }
    ]
    # Derived weekly capacity (x 7/30) leaves float noise; the percentage is unchanged.
    assert response.json()["account_pool_usage"]["secondary"] == pytest.approx(40.0)
    assert await _raw_rows() == before


async def test_nonapplicable_old_short_bucket_does_not_fabricate_primary(async_client, fixed_clock):
    await _seed("monthly", offset=-86400, duration=43200)
    async with SessionLocal() as session:
        session.add(
            UsageHistory(
                account_id="silent",
                window="primary",
                recorded_at=NOW - timedelta(days=30),
                used_percent=100.0,
                reset_at=EPOCH - 86400,
                window_minutes=300,
            )
        )
        await session.commit()
    key = await _key()
    before = await _raw_rows()
    response = await async_client.get("/v1/usage", headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 200
    assert [row["limit_window"] for row in response.json()["upstream_limits"]] == ["monthly"]
    assert response.json()["account_pool_usage"]["primary"] is None
    assert await _raw_rows() == before
