from __future__ import annotations

import pytest

from app.core.usage import expire_elapsed_window_rows, normalize_weekly_only_rows
from app.core.usage.types import UsageWindowRow

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("used_percent", [None, 0.0, 100.0])
@pytest.mark.parametrize("reset_at", [None, 99, 100, 101])
@pytest.mark.parametrize("duration", [None, 0, 300, 10080, 43200])
def test_elapsed_projection_preserves_unknown_zero_and_input_rows(used_percent, reset_at, duration):
    row = UsageWindowRow(account_id="fixture", used_percent=used_percent, reset_at=reset_at, window_minutes=duration)
    result = expire_elapsed_window_rows([row], now_epoch=100)
    expired = reset_at is not None and reset_at <= 100
    assert result == [
        UsageWindowRow(
            account_id="fixture",
            used_percent=0.0 if expired else used_percent,
            reset_at=None if expired else reset_at,
            window_minutes=duration,
        )
    ]
    assert row.used_percent == used_percent
    assert row.reset_at == reset_at
    assert row.window_minutes == duration
    assert (result[0] is row) is not expired


def test_empty_and_weekly_only_projection_does_not_seed_primary():
    assert expire_elapsed_window_rows([], now_epoch=100) == []
    weekly = UsageWindowRow(account_id="fixture", used_percent=100.0, reset_at=99, window_minutes=10080)
    primary, secondary = normalize_weekly_only_rows([weekly], [])
    assert expire_elapsed_window_rows(primary, now_epoch=100) == []
    assert secondary == [weekly]
    assert secondary[0].used_percent == 100.0
