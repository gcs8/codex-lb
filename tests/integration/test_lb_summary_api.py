from __future__ import annotations

import json
import re
from datetime import timedelta

import pytest
from sqlalchemy import event, insert, text

from app.core.config.settings_cache import get_settings_cache
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, ApiKey, RequestLog, UsageHistory
from app.db.session import SessionLocal, engine
from app.modules.api_keys.repository import ApiKeysRepository
from app.modules.api_keys.service import ApiKeyCreateData, ApiKeysService, ApiKeyUpdateData

pytestmark = pytest.mark.integration


async def create_key(*, sections="lb_summary", assigned=None):
    async with SessionLocal() as session:
        return await ApiKeysService(ApiKeysRepository(session)).create_key(
            ApiKeyCreateData(
                name="synthetic", allowed_models=None, usage_sections=sections, assigned_account_ids=assigned
            )
        )


def auth(key):
    return {"Authorization": f"Bearer {key.key}"}


async def seed_accounts():
    async with SessionLocal() as session:
        session.add_all(
            [
                Account(
                    id=name,
                    email=f"{name}@invalid.example",
                    plan_type=plan,
                    status=AccountStatus.ACTIVE,
                    alias="private-alias",
                    access_token_encrypted=b"synthetic-access",
                    refresh_token_encrypted=b"synthetic-refresh",
                    id_token_encrypted=b"synthetic-id",
                    last_refresh=utcnow(),
                )
                for name, plan in (("private-account-a", "pro"), ("private-account-b", "plus"))
            ]
        )
        await session.commit()
        for account_id, percent, reset in (("private-account-a", 40.0, 1234), ("private-account-b", 90.0, 9876)):
            session.add(
                UsageHistory(
                    account_id=account_id, window=None, used_percent=percent, reset_at=reset, recorded_at=utcnow()
                )
            )
        await session.commit()


def log(key_id, **changes):
    values = dict(
        api_key_id=key_id,
        account_id="private-account-a",
        request_id="private-request",
        model="gpt-6.1-sol",
        status="success",
        requested_at=utcnow() - timedelta(minutes=10),
    )
    values.update(changes)
    return values


async def seed_logs(rows):
    async with SessionLocal() as session:
        # Render None explicitly to retain consistent executemany column shapes.
        for values in rows:
            session.add(RequestLog(**values))
        await session.commit()


async def test_lb_summary_always_requires_usage_key(async_client):
    for headers in (
        {},
        {"Authorization": "Basic dashboard"},
        {"Authorization": "Bearer malformed"},
        {"Cookie": "dashboard_session=not-a-proxy-key"},
    ):
        response = await async_client.get("/v1/lb/summary", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"error": {"code": "invalid_api_key"}}
        assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("sections", ["", "upstream_limits,account_pool_usage", None])
async def test_default_and_legacy_keys_denied(async_client, sections):
    key = await create_key(sections=sections)
    response = await async_client.get("/v1/lb/summary", headers=auth(key))
    assert response.status_code == 403
    assert response.json() == {"error": {"code": "lb_summary_not_allowed"}}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("mode", ["disabled", "revoked", "expired"])
async def test_invalidated_key_denied_after_warm_cache(async_client, mode):
    key = await create_key()
    assert (await async_client.get("/v1/lb/summary", headers=auth(key))).status_code == 200
    async with SessionLocal() as session:
        service = ApiKeysService(ApiKeysRepository(session))
        if mode == "revoked":
            await service.delete_key(key.id)
        elif mode == "disabled":
            await service.update_key(key.id, ApiKeyUpdateData(is_active=False, is_active_set=True))
        else:
            await service.update_key(
                key.id, ApiKeyUpdateData(expires_at=utcnow() - timedelta(seconds=1), expires_at_set=True)
            )
    response = await async_client.get("/v1/lb/summary", headers=auth(key))
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "query",
    [
        "window=-1",
        "window=-24h",
        "window=8d",
        "window=168h",
        "window=",
        "window=1h&window=7d",
        "account_id=private-account-b",
        "model=private",
        "include=payload",
        "window=NaN",
    ],
)
async def test_reject_request_derived_extensions_and_windows(async_client, query):
    key = await create_key()
    response = await async_client.get("/v1/lb/summary?" + query, headers=auth(key))
    assert response.status_code == 400
    assert response.json() == {"error": {"code": "invalid_summary_query"}}
    assert response.headers["cache-control"] == "no-store"


async def test_reject_get_body_and_no_mutation_route(async_client):
    key = await create_key()
    response = await async_client.request("GET", "/v1/lb/summary", headers=auth(key), json={"prompt": "private"})
    assert response.status_code == 400
    assert (await async_client.post("/v1/lb/summary", headers=auth(key))).status_code == 405


async def test_key_cohort_isolation_closed_allowlist_and_measurement(async_client):
    await seed_accounts()
    key = await create_key(assigned=["private-account-a"])
    other = await create_key()
    await seed_logs(
        [
            log(
                key.id,
                input_tokens=100,
                cached_input_tokens=25,
                requested_service_tier="priority",
                actual_service_tier="default",
                upstream_transport="auto",
                transport="websocket",
            ),
            log(
                key.id,
                status="error",
                error_code="stream_incomplete",
                error_message="private-error",
                requested_service_tier="priority",
                actual_service_tier=None,
                service_tier="priority",
                upstream_transport="http",
                input_tokens=0,
                cached_input_tokens=0,
            ),
            log(
                key.id,
                status="error",
                error_code="private-error",
                model="private-model",
                requested_service_tier="private-tier",
                actual_service_tier="private-tier",
                upstream_transport="private-transport",
                input_tokens=8,
                cached_input_tokens=9,
            ),
            log(key.id, status="cancelled", upstream_transport="websocket"),
            log(key.id, status="private-status"),
            log(other.id, input_tokens=100000, cached_input_tokens=100000),
            log(key.id, account_id="private-account-b"),
            log(key.id, requested_at=utcnow() - timedelta(days=8)),
            log(key.id, requested_at=utcnow() + timedelta(hours=1)),
            log(key.id, deleted_at=utcnow()),
            log(key.id, request_kind="warmup"),
        ]
    )
    response = await async_client.get("/v1/lb/summary", headers=auth(key))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    data = response.json()
    assert set(data) == {"window", "accounts", "requests", "service_tier", "cache", "transport", "models"}
    assert data["window"] == "24h"
    assert data["requests"] == {
        "total": 5,
        "success": 1,
        "error": 2,
        "cancelled": 1,
        "unknown": 1,
        "errors_by_code": {"stream_incomplete": 1, "unknown": 1},
    }
    assert data["service_tier"] == {"requested": {"priority": 2, "unknown": 3}, "actual": {"default": 1, "unknown": 4}}
    assert data["cache"] == {
        "input_tokens": 100,
        "cached_input_tokens": 25,
        "hit_ratio": 0.25,
        "measured_requests": 2,
        "unknown_requests": 3,
    }
    assert data["transport"] == {"configured_auto": 1, "http": 1, "websocket": 1, "unknown": 2}
    assert data["models"] == {"gpt-6.1-sol": 4, "unknown": 1}
    assert len(data["accounts"]) == 1
    cohort = data["accounts"][0]
    assert set(cohort) == {"plan", "status", "count", "primary", "secondary"}
    assert (cohort["plan"], cohort["status"], cohort["count"]) == ("pro", "active", 1)
    assert set(cohort["primary"]) == {
        "known_accounts",
        "used_percent_mean",
        "reset_at_earliest",
        "reset_at_latest",
        "recorded_at_oldest",
        "recorded_at_newest",
    }
    assert cohort["primary"]["used_percent_mean"] == 40
    assert cohort["primary"]["reset_at_earliest"] == cohort["primary"]["reset_at_latest"] == 1234
    assert cohort["primary"]["recorded_at_oldest"] is not None
    assert cohort["secondary"] == {
        "known_accounts": 0,
        "used_percent_mean": None,
        "reset_at_earliest": None,
        "reset_at_latest": None,
        "recorded_at_oldest": None,
        "recorded_at_newest": None,
    }
    serialized = json.dumps(data, allow_nan=False)
    for forbidden in (
        "private-",
        key.id,
        other.id,
        key.key,
        "@invalid.example",
        "synthetic-access",
        "prompt",
        "payload",
        "headers",
    ):
        assert forbidden not in serialized
    other_data = (await async_client.get("/v1/lb/summary", headers=auth(other))).json()
    assert other_data["requests"]["total"] == 1
    assert len(other_data["accounts"]) == 2


async def test_empty_enabled_assignment_is_not_global(async_client):
    await seed_accounts()
    key = await create_key(assigned=[])
    await seed_logs([log(key.id)])
    # The existing create contract treats [] as unscoped; explicitly model the durable enabled-empty state.
    async with SessionLocal() as session:
        row = await session.get(ApiKey, key.id)
        assert row is not None
        row.account_assignment_scope_enabled = True
        await session.commit()
    response = await async_client.get("/v1/lb/summary", headers=auth(key))
    assert response.status_code == 200, response.text
    assert response.json()["accounts"] == []
    assert response.json()["requests"]["total"] == 0
    assert response.json()["cache"]["hit_ratio"] is None


async def test_hide_quota_omits_account_field_and_skips_quota_reads(async_client):
    await seed_accounts()
    key = await create_key()
    (await get_settings_cache().get()).hide_upstream_quota_from_api_keys = True
    statements = []

    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await async_client.get("/v1/lb/summary", headers=auth(key))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200
    assert set(response.json()) == {"window", "requests", "service_tier", "cache", "transport", "models"}
    assert not any("usage_history" in stmt for stmt in statements)


@pytest.mark.parametrize("window,expected", [("1h", 1), ("24h", 2), ("7d", 3)])
async def test_windows_and_measured_zero(async_client, window, expected):
    key = await create_key()
    await seed_logs(
        [
            log(
                key.id,
                account_id=None,
                requested_at=utcnow() - timedelta(hours=hours),
                input_tokens=0,
                cached_input_tokens=0,
            )
            for hours in (0.5, 2, 150, 170)
        ]
    )
    response = await async_client.get("/v1/lb/summary", params={"window": window}, headers=auth(key))
    assert response.status_code == 200
    assert response.json()["requests"]["total"] == expected
    assert response.json()["cache"] == {
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "hit_ratio": 0.0,
        "measured_requests": expected,
        "unknown_requests": 0,
    }


async def test_nonfinite_quota_and_cache_inputs_remain_unknown(async_client):
    await seed_accounts()
    key = await create_key()
    async with SessionLocal() as session:
        session.add(
            UsageHistory(
                account_id="private-account-a",
                window="primary",
                used_percent=float("inf"),
                reset_at=-1,
                recorded_at=utcnow(),
            )
        )
        await session.commit()
    await seed_logs(
        [
            log(key.id, input_tokens=float("inf"), cached_input_tokens=1),
            log(key.id, input_tokens=-1, cached_input_tokens=0),
        ]
    )
    response = await async_client.get("/v1/lb/summary", headers=auth(key))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["cache"] == {
        "input_tokens": None,
        "cached_input_tokens": None,
        "hit_ratio": None,
        "measured_requests": 0,
        "unknown_requests": 2,
    }
    pro = next(item for item in data["accounts"] if item["plan"] == "pro")
    assert pro["primary"]["known_accounts"] == 0
    assert pro["primary"]["used_percent_mean"] is None
    assert pro["primary"]["reset_at_earliest"] is None
    json.dumps(data, allow_nan=False)


async def test_private_exception_is_not_returned(async_client, monkeypatch):
    from app.modules.lb_summary.service import LbSummaryService

    key = await create_key()

    async def fail(*args, **kwargs):
        raise RuntimeError("private-exception-token")

    monkeypatch.setattr(LbSummaryService, "summary", fail)
    response = await async_client.get("/v1/lb/summary", headers=auth(key))
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "summary_unavailable"}}
    assert response.headers["cache-control"] == "no-store"


def _quota_lookup_indexes(plan):
    """Require two bounded latest-row lookups, independent of legal index names."""
    nodes = {row[0]: (row[1], row[3]) for row in plan}
    assert len(nodes) == len(plan), plan
    assert all(parent == 0 or parent in nodes for parent, _ in nodes.values()), plan
    subqueries = [node for node, (_, detail) in nodes.items() if detail.startswith("CORRELATED SCALAR SUBQUERY ")]
    assert len(subqueries) == 2, plan
    assert not any(re.match(r"SCAN usage_history(?:_\d+)?(?:\s|$)", detail) for _, detail in nodes.values()), plan
    indexes = []
    for subquery in subqueries:
        descendants = {subquery}
        while True:
            expanded = descendants | {node for node, (parent, _) in nodes.items() if parent in descendants}
            if expanded == descendants:
                break
            descendants = expanded
        details = [nodes[node][1] for node in descendants]
        assert not any("TEMP B-TREE" in detail for detail in details), plan
        searches = [detail for detail in details if detail.startswith("SEARCH usage_history ")]
        assert len(searches) == 1, plan
        match = re.fullmatch(
            r"SEARCH usage_history USING (?:COVERING )?INDEX (\S+) \(<expr>=\? AND account_id=\?\)", searches[0]
        )
        assert match is not None, plan
        indexes.append(match.group(1))
    assert sum(detail.startswith("SEARCH usage_history ") for _, detail in nodes.values()) == 2, plan
    return indexes


async def test_seeded_sqlite_query_count_and_indexed_window(async_client, record_property):
    if engine.dialect.name != "sqlite":
        pytest.skip("SQLite query-plan contract")
    await seed_accounts()
    key = await create_key()
    now = utcnow()
    rows = [log("foreign-key", account_id=None, requested_at=now - timedelta(days=30)) for _ in range(4000)]
    rows += [log(key.id, account_id=None, requested_at=now - timedelta(days=30)) for _ in range(4000)]
    rows += [
        log(
            key.id,
            account_id=None,
            error_code=f"attacker-{i}",
            model=f"attacker-{i}",
            status="error",
            requested_service_tier=f"attacker-{i}",
            upstream_transport=f"attacker-{i}",
        )
        for i in range(300)
    ]
    async with SessionLocal() as session:
        # Insert each homogeneous batch without materializing ORM rows.
        await session.execute(insert(RequestLog), rows[:8000])
        await session.execute(insert(RequestLog), rows[8000:])
        await session.commit()
    captured = []

    def capture(conn, cursor, statement, params, context, many):
        if "FROM request_logs" in statement or "usage_history" in statement:
            captured.append((statement, params))

    event.listen(engine.sync_engine, "before_cursor_execute", capture)
    try:
        response = await async_client.get("/v1/lb/summary?window=7d", headers=auth(key))
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", capture)
    assert response.status_code == 200, response.text
    assert response.json()["requests"]["total"] == 300
    for dimension in ("models", "transport"):
        assert response.json()[dimension] == {"unknown": 300}
    assert response.json()["requests"]["errors_by_code"] == {"unknown": 300}
    assert len(captured) == 7
    assert sum("usage_history" in statement for statement, _ in captured) == 1
    assert sum("FROM request_logs" in statement for statement, _ in captured) == 6
    async with engine.connect() as conn:
        for statement, params in captured:
            plan = (await conn.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, params)).all()
            details = " ".join(row[3] for row in plan)
            if "usage_history" in statement:
                record_property("quota_plan_tree", json.dumps([tuple(row) for row in plan]))
                for index in set(_quota_lookup_indexes(plan)):
                    # Verify the selected index's actual expression/window-account/time
                    # keys, not a name substring. SQLite's implicit rowid supplies the
                    # tie key for the ascending covering index, read in reverse order.
                    ddl = (
                        await conn.execute(
                            text(
                                "SELECT sql FROM sqlite_master "
                                "WHERE type='index' AND tbl_name='usage_history' AND name=:name"
                            ),
                            {"name": index},
                        )
                    ).scalar_one()
                    normalized = re.sub(r'[\s"`\[\]]', "", ddl).lower()
                    assert "onusage_history(coalesce(window,'primary'),account_id,recorded_at" in normalized, ddl
                    keys = (
                        await conn.execute(
                            text('SELECT cid, name, "desc", key FROM pragma_index_xinfo(:name) ORDER BY seqno'),
                            {"name": index},
                        )
                    ).all()
                    assert keys[0][0] == -2 and keys[1][1] == "account_id", keys
                    assert keys[2][1] == "recorded_at", keys
                    assert keys[3][1] == "id" or keys[3][0] == -1, keys
                    assert keys[2][2] == keys[3][2], keys
                    record_property("quota_index_keys", json.dumps([tuple(row) for row in keys]))
                continue
            assert "SEARCH request_logs USING INDEX idx_logs_api_key" in details, details
            assert "requested_at>?" in details and "requested_at<?" in details, details
            assert "SCAN request_logs" not in details
            assert "request_logs.error_message" not in statement
            assert "request_logs.request_id" not in statement
        assert (await conn.execute(text("SELECT count(*) FROM request_logs"))).scalar_one() == 8300


async def test_weekly_only_plans_report_weekly_window_as_secondary_and_prolite_cohort(async_client):
    """Pro / Pro Lite report the 7-day window in the primary slot with a zero-duration
    secondary placeholder (the live h015a shape). Cohorts must label it secondary, not
    5 h, must not average the placeholder as 0 % used, and must keep Pro Lite visible."""
    now = utcnow()
    async with SessionLocal() as session:
        for name, plan in (("weekly-pro", "pro"), ("weekly-lite", "prolite")):
            session.add(
                Account(
                    id=name,
                    email=f"{name}@invalid.example",
                    plan_type=plan,
                    status=AccountStatus.ACTIVE,
                    access_token_encrypted=b"synthetic-access",
                    refresh_token_encrypted=b"synthetic-refresh",
                    id_token_encrypted=b"synthetic-id",
                    last_refresh=now,
                )
            )
        await session.commit()
        for account_id, used in (("weekly-pro", 7.0), ("weekly-lite", 25.0)):
            session.add(
                UsageHistory(
                    account_id=account_id,
                    window="primary",
                    window_minutes=10080,
                    used_percent=used,
                    reset_at=4_000_000_000,
                    recorded_at=now,
                )
            )
            session.add(
                UsageHistory(
                    account_id=account_id,
                    window="secondary",
                    window_minutes=0,
                    used_percent=0.0,
                    reset_at=None,
                    recorded_at=now,
                )
            )
        await session.commit()
    key = await create_key()

    response = await async_client.get("/v1/lb/summary", headers=auth(key))
    assert response.status_code == 200, response.text
    cohorts = {item["plan"]: item for item in response.json()["accounts"]}

    assert "unknown" not in cohorts
    for plan, used in (("pro", 7), ("prolite", 25)):
        cohort = cohorts[plan]
        assert cohort["primary"]["known_accounts"] == 0
        assert cohort["primary"]["used_percent_mean"] is None
        assert cohort["secondary"]["known_accounts"] == 1
        assert cohort["secondary"]["used_percent_mean"] == used
        assert cohort["secondary"]["reset_at_earliest"] == 4_000_000_000
