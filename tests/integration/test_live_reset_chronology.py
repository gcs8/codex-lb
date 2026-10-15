from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.core.usage import refresh_scheduler
from app.core.utils.time import naive_utc_to_epoch, utcnow
from app.db.models import AccountLimitWarmup
from app.db.session import SessionLocal
from app.modules.limit_warmup.repository import LimitWarmupRepository
from app.modules.limit_warmup.reset_evidence import recover_current_reset_evidence
from app.modules.settings.repository import SettingsRepository
from app.modules.usage import updater
from app.modules.usage.live_ingest import LiveUsageIngestor
from app.modules.usage.repository import UsageRepository
from tests.integration.live_reset_helpers import (
    prepare_live_reset,
    publish_and_wait,
    record_warmup_sends,
    run_scheduler_ticks,
)

pytestmark = [pytest.mark.integration, pytest.mark.usage_refresh_request_path]


@pytest.mark.asyncio
@pytest.mark.parametrize("window", ["primary", "secondary", "monthly"])
async def test_recovered_reset_claim_is_atomic_after_both_workers_read_evidence(
    db_setup: bool, monkeypatch: pytest.MonkeyPatch, window: str
) -> None:
    account, snapshot, reset_at = await prepare_live_reset(window)
    sends = record_warmup_sends(monkeypatch)

    async def no_poll(**kwargs: object):
        pytest.fail("Fresh fixture snapshots must not reach the upstream poll")

    monkeypatch.setattr(updater, "fetch_usage", no_poll)
    original_recover = refresh_scheduler.recover_current_reset_evidence
    ready = asyncio.Event()
    observed: list[tuple[int, int]] = []

    async def recover_together(**kwargs):
        evidence = await original_recover(**kwargs)
        pair = evidence[account.id, window]
        assert pair.before.recorded_at <= pair.after.recorded_at
        assert pair.before.reset_at is not None and pair.after.reset_at == reset_at
        assert pair.before.reset_at < pair.after.reset_at
        observed.append((pair.before.id, pair.after.id))
        if len(observed) == 2:
            ready.set()
        async with asyncio.timeout(5):
            await ready.wait()
        return evidence

    monkeypatch.setattr(refresh_scheduler, "recover_current_reset_evidence", recover_together)
    ingestor = LiveUsageIngestor(queue_size=8, write_min_interval_seconds=0)
    ingestor.start()
    try:
        await publish_and_wait(ingestor, snapshot, account.id, window)
        await run_scheduler_ticks(monkeypatch, workers=2)
        assert len(observed) == 2 and observed[0] == observed[1]
        assert sends == [account.id]
        async with SessionLocal() as session:
            attempts = list((await session.scalars(select(AccountLimitWarmup))).all())
        assert len(attempts) == 1
        assert (attempts[0].window, attempts[0].reset_at, attempts[0].status) == (window, reset_at, "succeeded")

        monkeypatch.setattr(refresh_scheduler, "recover_current_reset_evidence", original_recover)
        slot = "secondary" if window == "secondary" else "primary"
        sample = getattr(snapshot, slot)
        assert sample is not None
        jittered = replace(snapshot, **{slot: replace(sample, reset_at=reset_at + 4)})
        await publish_and_wait(ingestor, jittered, account.id, window)
        await run_scheduler_ticks(monkeypatch)
        assert sends == [account.id]
        async with SessionLocal() as session:
            assert list((await session.scalars(select(AccountLimitWarmup.id))).all()) == [attempts[0].id]
    finally:
        await ingestor.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy_primary", [False, True])
async def test_retained_reset_history_uses_id_order_for_equal_timestamps(db_setup: bool, legacy_primary: bool) -> None:
    account, _, reset_at = await prepare_live_reset("primary", baseline="missing")
    boundary = int(naive_utc_to_epoch(utcnow())) + 1
    observed_at = datetime.fromtimestamp(boundary, timezone.utc).replace(tzinfo=None)
    async with SessionLocal() as session:
        repo = UsageRepository(session)
        before = await repo.add_entry(
            account.id, 51.0, window="primary", recorded_at=observed_at, reset_at=boundary, window_minutes=300
        )
        after = await repo.add_entry(
            account.id, 0.0, window="primary", recorded_at=observed_at, reset_at=reset_at, window_minutes=300
        )
        latest = await repo.add_entry(
            account.id, 1.0, window="primary", recorded_at=observed_at, reset_at=reset_at, window_minutes=300
        )
        if legacy_primary:
            before.window = after.window = latest.window = None
            await session.commit()
        settings = await SettingsRepository(session).get_or_create()
        evidence = await recover_current_reset_evidence(
            accounts=[account],
            settings=settings,
            primary={account.id: latest},
            secondary={},
            usage_repo=repo,
            warmup_repo=LimitWarmupRepository(session),
            now=observed_at,
        )
        pair = evidence[account.id, "primary"]
        assert (pair.before.id, pair.after.id) == (before.id, after.id)
        assert pair.before.id < pair.after.id < latest.id
        assert pair.before.recorded_at == pair.after.recorded_at == latest.recorded_at


@pytest.mark.asyncio
async def test_retained_evidence_cannot_cross_snapshot_horizon_or_window(db_setup: bool) -> None:
    account, _, reset_at = await prepare_live_reset("primary", baseline="missing")
    boundary = int(naive_utc_to_epoch(utcnow())) + 1
    observed_at = datetime.fromtimestamp(boundary, timezone.utc).replace(tzinfo=None)
    async with SessionLocal() as session:
        repo = UsageRepository(session)
        # A sibling baseline cannot supply the missing primary predecessor.
        await repo.add_entry(
            account.id, 51.0, window="secondary", recorded_at=observed_at, reset_at=boundary, window_minutes=300
        )
        captured = await repo.add_entry(
            account.id, 0.0, window="primary", recorded_at=observed_at, reset_at=reset_at, window_minutes=300
        )
        # A pair persisted after the captured latest row is outside its horizon.
        await repo.add_entry(
            account.id, 51.0, window="primary", recorded_at=observed_at, reset_at=boundary, window_minutes=300
        )
        later = await repo.add_entry(
            account.id, 0.0, window="primary", recorded_at=observed_at, reset_at=reset_at, window_minutes=300
        )
        settings = await SettingsRepository(session).get_or_create()
        assert (
            await recover_current_reset_evidence(
                accounts=[account],
                settings=settings,
                primary={account.id: captured},
                secondary={},
                usage_repo=repo,
                warmup_repo=LimitWarmupRepository(session),
                now=observed_at,
            )
            == {}
        )
        evidence = await recover_current_reset_evidence(
            accounts=[account],
            settings=settings,
            primary={account.id: later},
            secondary={},
            usage_repo=repo,
            warmup_repo=LimitWarmupRepository(session),
            now=observed_at,
        )
        assert evidence[account.id, "primary"].after.id == later.id
        assert evidence[account.id, "primary"].before.id > captured.id
