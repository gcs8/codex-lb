from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta

from app.core.utils.time import utcnow
from app.modules.api_keys.service import ApiKeyData
from app.modules.lb_summary.repository import LbSummaryRepository
from app.modules.lb_summary.schemas import (
    AccountCohort,
    CacheSummary,
    LbSummary,
    QuotaSummary,
    RequestSummary,
    TierSummary,
    Window,
)


class LbSummaryService:
    def __init__(self, repository: LbSummaryRepository) -> None:
        self.repository = repository

    async def summary(self, key: ApiKeyData, window: Window, include_accounts: bool) -> LbSummary:
        until = utcnow()
        since = until - timedelta(hours={"1h": 1, "24h": 24, "7d": 168}[window])
        account_ids = list(key.assigned_account_ids) if key.account_assignment_scope_enabled else None
        measures = await self.repository.measures(key.id, account_ids, since, until)
        errors, requested, actual, transport, models = await self.repository.dimensions(
            key.id, account_ids, since, until
        )
        result = LbSummary(
            window=window,
            requests=RequestSummary(
                total=measures.total,
                success=measures.success,
                error=measures.error,
                cancelled=measures.cancelled,
                unknown=measures.total - measures.success - measures.error - measures.cancelled,
                errors_by_code=errors,
            ),
            service_tier=TierSummary(requested=requested, actual=actual),
            cache=CacheSummary(
                input_tokens=measures.input_tokens if measures.measured else None,
                cached_input_tokens=measures.cached_tokens if measures.measured else None,
                hit_ratio=(measures.cached_tokens / measures.input_tokens if measures.input_tokens else 0.0)
                if measures.measured
                else None,
                measured_requests=measures.measured,
                unknown_requests=measures.total - measures.measured,
            ),
            transport=transport,
            models=models,
        )
        if include_accounts:
            result.accounts = [
                AccountCohort(
                    plan=cohort.plan,
                    status=cohort.status,
                    count=cohort.count,
                    primary=QuotaSummary(**asdict(cohort.primary)),
                    secondary=QuotaSummary(**asdict(cohort.secondary)),
                )
                for cohort in await self.repository.cohorts(account_ids)
            ]
        return result
