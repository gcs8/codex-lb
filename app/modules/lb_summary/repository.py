from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, case, func, literal_column, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.expression import SQLColumnExpression
from sqlalchemy.sql.selectable import CTE

from app.core.usage import DEFAULT_WINDOW_MINUTES_SECONDARY
from app.db.models import Account, RequestLog, UsageHistory

# Closed, server-owned labels. Never derive these from request data or a dynamic registry.
PLANS = ("free", "plus", "prolite", "pro", "team", "business", "enterprise", "edu")
STATUSES = ("active", "rate_limited", "quota_exceeded", "paused", "reauth_required", "deactivated")
TIERS = ("auto", "default", "flex", "priority", "scale")
ERRORS = (
    "stream_incomplete",
    "server_error",
    "overloaded",
    "rate_limit_exceeded",
    "insufficient_quota",
    "upstream_error",
    "timeout",
    "invalid_request_error",
    "model_not_found",
    "authentication_error",
)
MODELS = (
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-5-codex",
    "gpt-5.1",
    "gpt-5.1-codex",
    "gpt-5.1-codex-mini",
    "gpt-5.1-codex-max",
    "gpt-5.2",
    "gpt-5.2-codex",
    "gpt-5.3-codex",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-6",
    "gpt-6.1",
    "gpt-6.1-sol",
)


def bucket(column: SQLColumnExpression[Any], labels: tuple[str, ...]) -> ColumnElement[str]:
    return case((column.in_(labels), column), else_="unknown")


@dataclass(frozen=True)
class Measures:
    total: int
    success: int
    error: int
    cancelled: int
    measured: int
    input_tokens: int
    cached_tokens: int


@dataclass(frozen=True)
class QuotaMeasures:
    known_accounts: int
    used_percent_mean: float | None
    reset_at_earliest: int | None
    reset_at_latest: int | None
    recorded_at_oldest: datetime | None
    recorded_at_newest: datetime | None


@dataclass(frozen=True)
class CohortMeasures:
    plan: str
    status: str
    count: int
    primary: QuotaMeasures
    secondary: QuotaMeasures


class LbSummaryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    @staticmethod
    def request_source(key_id: str, since: datetime, until: datetime) -> CTE:
        # Materialize the key/time range first. Without this optimization fence,
        # SQLite can choose the global deleted_at/time index for sparse keys.
        # Only aggregate inputs are selected, never prompts, headers or error messages.
        return (
            select(
                RequestLog.account_id,
                RequestLog.deleted_at,
                RequestLog.request_kind,
                RequestLog.status,
                RequestLog.input_tokens,
                RequestLog.cached_input_tokens,
                RequestLog.error_code,
                RequestLog.requested_service_tier,
                RequestLog.actual_service_tier,
                RequestLog.upstream_transport,
                RequestLog.model,
            )
            .where(
                RequestLog.api_key_id == key_id,
                RequestLog.requested_at >= since,
                RequestLog.requested_at <= until,
            )
            .cte("key_window")
            .prefix_with("MATERIALIZED")
        )

    @staticmethod
    def request_scope(source: CTE, account_ids: list[str] | None) -> list[ColumnElement[bool]]:
        scope = [source.c.deleted_at.is_(None), source.c.request_kind == "normal"]
        if account_ids is not None:
            scope.append(source.c.account_id.in_(account_ids))
        return scope

    async def measures(self, key_id: str, account_ids: list[str] | None, since: datetime, until: datetime) -> Measures:
        source = self.request_source(key_id, since, until)
        valid = and_(
            source.c.input_tokens >= 0,
            source.c.input_tokens <= 1_000_000_000_000,
            source.c.cached_input_tokens >= 0,
            source.c.cached_input_tokens <= source.c.input_tokens,
        )
        stmt = select(
            func.count(),
            func.count(case((source.c.status == "success", 1))),
            func.count(case((source.c.status == "error", 1))),
            func.count(case((source.c.status == "cancelled", 1))),
            func.count(case((valid, 1))),
            func.coalesce(func.sum(case((valid, source.c.input_tokens), else_=0)), 0),
            func.coalesce(func.sum(case((valid, source.c.cached_input_tokens), else_=0)), 0),
        ).where(*self.request_scope(source, account_ids))
        row = (await self.session.execute(stmt)).one()
        return Measures(*row)

    async def dimensions(
        self, key_id: str, account_ids: list[str] | None, since: datetime, until: datetime
    ) -> list[dict[str, int]]:
        source = self.request_source(key_id, since, until)
        transport = case(
            (source.c.upstream_transport.in_(("http", "openai_compatible_http")), "http"),
            (source.c.upstream_transport == "websocket", "websocket"),
            (source.c.upstream_transport == "auto", "configured_auto"),
            else_="unknown",
        )
        dimensions = [
            bucket(source.c.error_code, ERRORS),
            bucket(source.c.requested_service_tier, TIERS),
            bucket(source.c.actual_service_tier, TIERS),
            transport,
            bucket(source.c.model, MODELS),
        ]
        result: list[dict[str, int]] = []
        for index, dimension in enumerate(dimensions):
            stmt = select(dimension, func.count()).where(*self.request_scope(source, account_ids))
            if index == 0:
                stmt = stmt.where(source.c.status == "error")
            rows = await self.session.execute(stmt.group_by(dimension))
            result.append({name: count for name, count in rows})
        return result

    async def cohorts(self, account_ids: list[str] | None) -> list[CohortMeasures]:
        # Index-backed single latest-row lookup per account/window; no auth columns selected.
        windows = [aliased(UsageHistory), aliased(UsageHistory)]
        latest_ids = []
        for window in ("primary", "secondary"):
            normalized = func.coalesce(UsageHistory.window, literal_column("'primary'"))
            latest_ids.append(
                select(UsageHistory.id)
                .where(UsageHistory.account_id == Account.id, normalized == window)
                .order_by(UsageHistory.recorded_at.desc(), UsageHistory.id.desc())
                .limit(1)
                .correlate(Account)
                .scalar_subquery()
            )
        plan, status = bucket(Account.plan_type, PLANS), bucket(Account.status, STATUSES)
        fields = [plan, status, func.count()]
        primary_row, secondary_row = windows

        def is_placeholder(usage: Any) -> ColumnElement[bool]:
            # Upstream omitted the slot: no duration and no reset is the absence
            # of a measurement, not 0 % used.
            return and_(func.coalesce(usage.window_minutes, 0) <= 0, usage.reset_at.is_(None))

        primary_real = and_(primary_row.id.is_not(None), ~is_placeholder(primary_row))
        secondary_real = and_(secondary_row.id.is_not(None), ~is_placeholder(secondary_row))
        # Weekly-only plans (Pro, Pro Lite) report their 7-day window in the
        # primary slot and leave a placeholder in secondary. Mirror the usage
        # normalization so "primary" is the 5 h window and "secondary" the weekly
        # one, as /v1/usage and the dashboard do.
        weekly_in_primary = and_(
            primary_real,
            # coalesce: a NULL duration must yield false, not NULL (which would void
            # the primary measurement through three-valued logic).
            func.coalesce(primary_row.window_minutes, 0) == DEFAULT_WINDOW_MINUTES_SECONDARY,
            ~secondary_real | func.coalesce(primary_row.recorded_at >= secondary_row.recorded_at, False),
        )

        def primary_value(column: str) -> ColumnElement[Any]:
            return case((and_(primary_real, ~weekly_in_primary), getattr(primary_row, column)))

        def secondary_value(column: str) -> ColumnElement[Any]:
            return case(
                (weekly_in_primary, getattr(primary_row, column)),
                (secondary_real, getattr(secondary_row, column)),
            )

        for pick in (primary_value, secondary_value):
            used_percent, reset_at, recorded_at = pick("used_percent"), pick("reset_at"), pick("recorded_at")
            # Invalid/nonfinite percentages never become measurements. SQL comparisons exclude infinities/NaN.
            valid = and_(used_percent >= 0, used_percent <= 100)
            reset = case((and_(reset_at >= 0, reset_at <= 253402300799), reset_at))
            fields.extend(
                [
                    func.count(case((valid, 1))),
                    func.avg(case((valid, used_percent))),
                    func.min(reset),
                    func.max(reset),
                    func.min(recorded_at),
                    func.max(recorded_at),
                ]
            )
        stmt = (
            select(*fields)
            .select_from(Account)
            .outerjoin(windows[0], windows[0].id == latest_ids[0])
            .outerjoin(windows[1], windows[1].id == latest_ids[1])
            .where(Account.delete_requested_at.is_(None))
        )
        if account_ids is not None:
            stmt = stmt.where(Account.id.in_(account_ids))
        rows = await self.session.execute(stmt.group_by(plan, status).order_by(plan, status))
        return [
            CohortMeasures(row[0], row[1], row[2], QuotaMeasures(*row[3:9]), QuotaMeasures(*row[9:15])) for row in rows
        ]
