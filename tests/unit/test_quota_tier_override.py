"""Per-account subscription tier overrides (gcs8/codex-lb#7 phase 2).

The plan claim can't tell tiers apart (grandfathered Pro 200 at 20x and new Pro 200
at 10x both report ``pro``), so an owner can set the tier, optionally until a date.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.usage import (
    capacity_for_account,
    capacity_for_plan,
    effective_quota_tier_multiplier,
    plan_quota_tier_multiplier,
)
from app.db.models import Account

NOW = datetime(2026, 10, 15, 12, 0, 0)


def _account(plan: str, multiplier: float | None = None, expires_at: datetime | None = None) -> Account:
    return Account(
        id=f"acc-{plan}",
        email=f"{plan}@example.com",
        plan_type=plan,
        quota_tier_multiplier=multiplier,
        quota_tier_multiplier_expires_at=expires_at,
    )


def test_no_override_is_exactly_the_plan_capacity() -> None:
    for plan in ("plus", "prolite", "pro", "free"):
        account = _account(plan)
        for window in ("primary", "secondary", "monthly"):
            assert capacity_for_account(account, window, NOW) == capacity_for_plan(plan, window)
    assert effective_quota_tier_multiplier(_account("pro"), NOW) == plan_quota_tier_multiplier("pro") == 10.0


def test_grandfathered_pro_200_override_doubles_weekly_capacity() -> None:
    account = _account("pro", 20.0, NOW + timedelta(days=14))
    assert capacity_for_account(account, "secondary", NOW) == pytest.approx(7560.0 * 20 * 7 / 30)
    pro_weekly = capacity_for_plan("pro", "secondary")
    pro_5h = capacity_for_plan("pro", "primary")
    assert pro_weekly is not None and pro_5h is not None
    assert capacity_for_account(account, "secondary", NOW) == pytest.approx(2 * pro_weekly)
    # 5 h window scales by override / plan multiplier.
    assert capacity_for_account(account, "primary", NOW) == pytest.approx(2 * pro_5h)


def test_override_reverts_to_plan_default_at_expiry() -> None:
    expires = NOW + timedelta(hours=1)
    account = _account("pro", 20.0, expires)
    assert effective_quota_tier_multiplier(account, expires - timedelta(seconds=1)) == 20.0
    assert effective_quota_tier_multiplier(account, expires) == 10.0
    assert capacity_for_account(account, "secondary", expires + timedelta(days=1)) == pytest.approx(
        capacity_for_plan("pro", "secondary")
    )


def test_pro_500_override_without_expiry() -> None:
    account = _account("pro", 25.0)
    assert capacity_for_account(account, "secondary", NOW) == pytest.approx(7560.0 * 25 * 7 / 30)


def test_override_never_changes_window_applicability() -> None:
    # Free has no 5 h capacity (0.0) and no monthly row for paid plans (None):
    # an override must not invent a window.
    assert capacity_for_account(_account("free", 25.0), "primary", NOW) == capacity_for_plan("free", "primary")
    assert capacity_for_account(_account("pro", 25.0), "monthly", NOW) is None


def test_timezone_aware_values_compare_in_utc() -> None:
    from datetime import timezone

    aware_expiry = (NOW + timedelta(hours=1)).replace(tzinfo=timezone.utc)
    account = _account("pro", 20.0, aware_expiry)
    assert effective_quota_tier_multiplier(account, NOW.replace(tzinfo=timezone.utc)) == 20.0
    assert effective_quota_tier_multiplier(account, NOW + timedelta(hours=2)) == 10.0


def test_non_positive_override_is_ignored() -> None:
    assert effective_quota_tier_multiplier(_account("prolite", 0.0), NOW) == 5.0
