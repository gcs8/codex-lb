from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

import app.modules.proxy.load_balancer as load_balancer_module
from app.core.balancer.logic import AccountState, select_account
from app.db.models import AccountStatus
from app.modules.proxy.account_cache import AccountSelectionCache
from app.modules.proxy.load_balancer import AccountConcurrencyCaps, RuntimeState
from tests.unit.test_load_balancer_contract import _account, _balancer

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "status",
    [AccountStatus.PAUSED, AccountStatus.DEACTIVATED, AccountStatus.RATE_LIMITED, AccountStatus.QUOTA_EXCEEDED],
)
def test_hard_owner_backoff_does_not_bypass_persisted_status(status: AccountStatus) -> None:
    now = 1_700_000_000.0
    owner = AccountState(
        "owner",
        status,
        reset_at=now + 3600,
        error_count=5,
        last_error_at=now - 1,
    )
    assert select_account([owner], now=now, hard_owner_pool=True).account is None
    assert owner.error_count == 5
    assert owner.last_error_at == now - 1


@pytest.mark.parametrize("gate", ["cooldown", "expired_reauth", "disabled_fallback"])
def test_hard_owner_backoff_does_not_bypass_independent_health_gate(gate: str) -> None:
    now = 1_700_000_000.0
    owner = AccountState(
        "owner",
        AccountStatus.REAUTH_REQUIRED if gate == "expired_reauth" else AccountStatus.ACTIVE,
        access_token_expires_at=now - 1 if gate == "expired_reauth" else None,
        cooldown_until=now + 60 if gate == "cooldown" else None,
        error_count=5,
        last_error_at=now - 1,
    )
    result = select_account([owner], now=now, hard_owner_pool=True, allow_backoff_fallback=gate != "disabled_fallback")
    assert result.account is None
    assert owner.error_count == 5
    assert owner.last_error_at == now - 1


@pytest.mark.asyncio
@pytest.mark.parametrize("gate", ["scope", "security", "exclusion", "cap"])
async def test_transient_hard_owner_backoff_preserves_selection_admission_gates(
    monkeypatch: pytest.MonkeyPatch, gate: str
) -> None:
    monkeypatch.setattr(load_balancer_module, "get_settings", lambda: SimpleNamespace(circuit_breaker_enabled=False))
    degraded: list[str] = []
    normal: list[bool] = []
    monkeypatch.setattr(load_balancer_module, "set_degraded", degraded.append)
    monkeypatch.setattr(load_balancer_module, "set_normal", lambda: normal.append(True))
    owner = _account("backoff-guard-owner")
    alternate = _account("backoff-guard-alternate", security_work_authorized=True)
    balancer, _, _, _ = _balancer([owner, alternate], AccountSelectionCache(ttl_seconds=60))
    balancer._runtime[owner.id] = RuntimeState(error_count=5, last_error_at=time.time() - 1)
    balancer._runtime[alternate.id] = RuntimeState()
    caps = AccountConcurrencyCaps(response_create_limit=1, stream_limit=1)
    held_lease = (
        await balancer.acquire_account_lease(owner.id, kind="stream", concurrency_caps=caps) if gate == "cap" else None
    )
    try:
        selection = await balancer.select_account(
            account_ids={alternate.id} if gate == "scope" else None,
            required_account_id=owner.id,
            required_account_is_ownership_constraint=True,
            required_continuity_owner=True,
            require_security_work_authorized=gate == "security",
            exclude_account_ids={owner.id} if gate == "exclusion" else None,
            concurrency_caps=caps,
            lease_kind="stream",
        )
        assert selection.account is None
        assert selection.lease is None
        if gate in {"scope", "security"}:
            assert selection.error_code == load_balancer_module.CONTINUITY_OWNER_POLICY_CONFLICT
        elif gate == "cap":
            assert held_lease is not None
            assert selection.error_code == "account_stream_cap"
        else:
            assert selection.error_code == load_balancer_module.CONTINUITY_OWNER_UNAVAILABLE
        assert balancer._runtime[alternate.id].inflight_streams == 0
        assert degraded == []
        assert normal == []
    finally:
        await balancer.release_account_lease(held_lease)
