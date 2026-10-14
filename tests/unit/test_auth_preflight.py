from __future__ import annotations

import base64
import json
from datetime import timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from app.core.auth.refresh import RefreshError
from app.core.balancer import PERMANENT_FAILURE_CODES
from app.core.crypto import TokenEncryptor
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus
from app.modules.accounts import auth_manager as auth_manager_module
from app.modules.accounts.auth_manager import AuthManager

pytestmark = pytest.mark.unit


def _account(*, expires_at: int, status: AccountStatus) -> Account:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expires_at}).encode()).rstrip(b"=").decode()
    encryptor = TokenEncryptor()
    return Account(
        id="boundary-fixture",
        chatgpt_account_id="boundary-workspace",
        email="boundary@example.invalid",
        plan_type="plus",
        status=status,
        deactivation_reason=PERMANENT_FAILURE_CODES["invalid_grant"]
        if status == AccountStatus.REAUTH_REQUIRED
        else None,
        access_token_encrypted=encryptor.encrypt(f"header.{payload}.sig"),
        refresh_token_encrypted=encryptor.encrypt("fixture-refresh"),
        id_token_encrypted=encryptor.encrypt("fixture-id"),
        last_refresh=utcnow() - timedelta(days=9),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [-1, 0, 1])
async def test_recovery_checks_latest_expiry_strictly_after_now(monkeypatch, offset):
    now = 2_000_000_000
    snapshot = _account(expires_at=now + 3600, status=AccountStatus.ACTIVE)
    latest = _account(expires_at=now + offset, status=AccountStatus.REAUTH_REQUIRED)
    before = (
        latest.access_token_encrypted,
        latest.refresh_token_encrypted,
        latest.id_token_encrypted,
        latest.last_refresh,
    )
    failure = RefreshError("invalid_grant", "Fixture rejection", True)
    shared = AsyncMock(side_effect=failure)
    repo = Mock()
    repo.get_by_id_fresh = AsyncMock(return_value=latest)
    monkeypatch.setattr(auth_manager_module._REFRESH_SINGLEFLIGHT, "run", shared)
    monkeypatch.setattr(auth_manager_module.time, "time", lambda: now)

    if offset > 0:
        result = await AuthManager(repo).ensure_fresh(snapshot)
        assert result is snapshot
        assert result.status == AccountStatus.REAUTH_REQUIRED
        assert result.deactivation_reason == PERMANENT_FAILURE_CODES["invalid_grant"]
        assert (
            result.access_token_encrypted,
            result.refresh_token_encrypted,
            result.id_token_encrypted,
            result.last_refresh,
        ) == before
    else:
        with pytest.raises(RefreshError) as raised:
            await AuthManager(repo).ensure_fresh(snapshot)
        assert raised.value is failure
    repo.get_by_id_fresh.assert_awaited_once_with(snapshot.id)
    assert len(repo.method_calls) == 1
    shared.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["missing", "active", "paused", "deactivated", "other-warning", "read-failed"])
async def test_recovery_fails_closed_when_fresh_state_cannot_authorize_it(monkeypatch, state):
    now = 2_000_000_000
    snapshot = _account(expires_at=now + 3600, status=AccountStatus.ACTIVE)
    latest = _account(expires_at=now + 3600, status=AccountStatus.REAUTH_REQUIRED)
    if state in {"active", "paused", "deactivated"}:
        latest.status = AccountStatus(state)
    elif state == "other-warning":
        latest.deactivation_reason = PERMANENT_FAILURE_CODES["app_session_terminated"]
    failure = RefreshError("invalid_grant", "Fixture rejection", True)
    read_failure = RuntimeError("Fixture database unavailable")
    repo = Mock()
    repo.get_by_id_fresh = AsyncMock(
        return_value=None if state == "missing" else latest,
        side_effect=read_failure if state == "read-failed" else None,
    )
    monkeypatch.setattr(auth_manager_module._REFRESH_SINGLEFLIGHT, "run", AsyncMock(side_effect=failure))
    monkeypatch.setattr(auth_manager_module.time, "time", lambda: now)

    with pytest.raises(RuntimeError if state == "read-failed" else RefreshError) as raised:
        await AuthManager(repo).ensure_fresh(snapshot)
    assert raised.value is (read_failure if state == "read-failed" else failure)
    repo.get_by_id_fresh.assert_awaited_once_with(snapshot.id)
    assert len(repo.method_calls) == 1
