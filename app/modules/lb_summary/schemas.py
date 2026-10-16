from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Window = Literal["1h", "24h", "7d"]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class QuotaSummary(ClosedModel):
    known_accounts: int
    used_percent_mean: float | None
    reset_at_earliest: int | None
    reset_at_latest: int | None
    recorded_at_oldest: datetime | None
    recorded_at_newest: datetime | None


class AccountCohort(ClosedModel):
    plan: str
    status: str
    count: int
    primary: QuotaSummary
    secondary: QuotaSummary


class RequestSummary(ClosedModel):
    total: int
    success: int
    error: int
    cancelled: int
    unknown: int
    errors_by_code: dict[str, int]


class TierSummary(ClosedModel):
    requested: dict[str, int]
    actual: dict[str, int]


class CacheSummary(ClosedModel):
    input_tokens: int | None
    cached_input_tokens: int | None
    hit_ratio: float | None
    measured_requests: int
    unknown_requests: int


class LbSummary(ClosedModel):
    window: Window
    requests: RequestSummary
    service_tier: TierSummary
    cache: CacheSummary
    transport: dict[str, int]
    models: dict[str, int]
    accounts: list[AccountCohort] | None = None
