"""Synthetic visibility proof for #1467, never real provider inference.

Only provider catalog data is synthetic. Registry authority, SQLite persistence,
application lifespans, API-key authentication and discovery routes stay real.
A retained native metadata row is not a public availability advertisement.
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.clients.model_fetcher import _parse_upstream_model
from app.core.crypto import TokenEncryptor
from app.core.openai.model_registry import get_model_registry
from app.core.openai.model_registry_store import encode_registry_export, persist_registry_snapshot
from app.core.utils.time import utcnow
from app.db.models import Account, AccountStatus, ModelRegistrySnapshotRecord
from app.db.session import SessionLocal
from app.main import create_app
from app.modules.proxy._load_balancer.model_eligibility import _filter_accounts_for_model_with_catalog_evidence
from app.modules.proxy.schemas import CodexModelEntry, CodexModelsResponse, ModelListResponse

pytestmark = pytest.mark.integration

SPARK = "gpt-5.3-codex-spark"
CONTROL = "gpt-5.3-codex"


def _provider_model(slug: str, *, supported_in_api: bool = True):
    # Validate the controlled provider row against the maintained native schema
    # before passing its JSON through the actual provider-catalog parser.
    entry = CodexModelEntry(
        slug=slug,
        display_name=slug,
        description="Synthetic issue 1467 provider catalog",
        context_window=128_000,
        input_modalities=["text"],
        available_in_plans=["pro"],
        supported_in_api=supported_in_api,
        visibility="list",
        shell_type="shell_command",
        minimal_client_version="0.100.0",
        truncation_policy={"mode": "tokens", "limit": 10_000},
        experimental_supported_tools=[],
    )
    return _parse_upstream_model(entry.model_dump(mode="json"))


async def _persist_and_read_back() -> str:
    encoded = encode_registry_export(await get_model_registry().export_state())
    async with SessionLocal() as session:
        await persist_registry_snapshot(session, encoded=encoded, leader_id="synthetic-issue-1467")
    async with SessionLocal() as session:
        row = await session.scalar(select(ModelRegistrySnapshotRecord).where(ModelRegistrySnapshotRecord.id == 1))
        assert row is not None
        assert row.content_hash == encoded.content_hash
        assert row.payload == encoded.payload
    return encoded.content_hash


async def _seed_accounts(plans: list[str]) -> list[Account]:
    encryptor = TokenEncryptor()
    accounts = [
        Account(
            id=f"synthetic-1467-{index}",
            email=f"synthetic-1467-{index}@example.invalid",
            plan_type=plan,
            access_token_encrypted=encryptor.encrypt("synthetic-access"),
            refresh_token_encrypted=encryptor.encrypt("synthetic-refresh"),
            id_token_encrypted=encryptor.encrypt("synthetic-id"),
            last_refresh=utcnow(),
            status=AccountStatus.ACTIVE,
        )
        for index, plan in enumerate(plans)
    ]
    async with SessionLocal() as session:
        session.add_all(accounts)
        await session.commit()
    async with SessionLocal() as session:
        rows = list((await session.scalars(select(Account).order_by(Account.id))).all())
        assert [row.plan_type for row in rows] == plans
        session.expunge_all()
    return rows


@pytest.mark.parametrize("catalog", ["eligible", "unsupported", "withdrawn"])
@pytest.mark.parametrize("scope", ["all", "literal", "other"])
async def test_literal_spark_visibility_survives_real_app_restart(app_instance, catalog: str, scope: str):
    """Exact Pro catalog evidence plus key scope, before/after SQLite reload."""
    registry = get_model_registry()
    async with app_instance.router.lifespan_context(app_instance):
        async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://testserver") as client:
            accounts = await _seed_accounts(["pro"])
            account = accounts[0]
            spark = _provider_model(SPARK, supported_in_api=catalog != "unsupported")
            control = _provider_model(CONTROL)
            models = [control, spark]
            await registry.update(
                {"pro": models},
                per_account_results={account.id: ("pro", models)},
                active_account_plans={account.id: "pro"},
            )
            if catalog == "withdrawn":
                await registry.update(
                    {"pro": [control]},
                    per_account_results={account.id: ("pro", [control])},
                    active_account_plans={account.id: "pro"},
                )
            snapshot = registry.get_snapshot()
            assert snapshot is not None
            assert snapshot.account_catalogs_authoritative is True
            assert snapshot.bootstrap_floor_active is False
            assert registry.is_suppressed_model(SPARK) is (catalog == "withdrawn")
            assert registry.plan_types_for_model(SPARK) == (
                frozenset() if catalog == "withdrawn" else frozenset({"pro"})
            )
            content_hash = await _persist_and_read_back()
            settings = await client.put(
                "/api/settings",
                json={
                    "stickyThreadsEnabled": False,
                    "preferEarlierResetAccounts": False,
                    "totpRequiredOnLogin": False,
                    "apiKeyAuthEnabled": True,
                },
            )
            assert settings.status_code == 200
            allowed_models = None if scope == "all" else [SPARK if scope == "literal" else CONTROL]
            created = await client.post(
                "/api/api-keys/", json={"name": "synthetic-1467", "allowedModels": allowed_models}
            )
            assert created.status_code == 200
            key_id = created.json()["id"]
            headers = {"Authorization": f"Bearer {created.json()['key']}"}
            expected = {CONTROL, SPARK} if catalog == "eligible" else {CONTROL}
            if allowed_models is not None:
                expected &= set(allowed_models)
            await _assert_catalogs(client, headers, expected, catalog, scope)

    # Exercise a new real app lifespan, not an injected in-memory export.
    # Startup must read the fresh persisted SQLite snapshot before any tick.
    await registry.clear()
    restarted = create_app()
    async with restarted.router.lifespan_context(restarted):
        assert registry.applied_content_hash == content_hash
        async with AsyncClient(transport=ASGITransport(app=restarted), base_url="http://testserver") as client:
            await _assert_catalogs(client, headers, expected, catalog, scope)
            listed = await client.get("/api/api-keys/")
            assert listed.status_code == 200
            key = next(row for row in listed.json() if row["id"] == key_id)
            assert key["allowedModels"] == allowed_models
            dashboard = await client.get("/api/models")
            assert dashboard.status_code == 200
            dashboard_ids = {item["id"] for item in dashboard.json()["models"]}
            assert dashboard_ids == ({CONTROL, SPARK} if catalog == "eligible" else {CONTROL})


async def _assert_catalogs(client, headers, expected: set[str], catalog: str, scope: str) -> None:
    public = await client.get("/v1/models", headers=headers)
    assert public.status_code == 200
    payload = public.json()
    ModelListResponse.model_validate(payload)
    assert set(payload) == {"object", "data"}
    assert payload["object"] == "list"
    assert {item["id"] for item in payload["data"]} == expected
    for item in payload["data"]:
        assert item["object"] == "model"
        assert item["owned_by"] == "codex-lb"
        assert item["metadata"]["supported_in_api"] is True
        assert item["metadata"]["context_window"] == 128_000
    retrieve = await client.get(f"/v1/models/{SPARK}", headers=headers)
    assert retrieve.status_code == (200 if SPARK in expected else 404)
    if SPARK in expected:
        assert retrieve.json()["id"] == SPARK
    else:
        assert retrieve.json()["error"] == {
            "message": f"The model '{SPARK}' does not exist",
            "type": "invalid_request_error",
            "code": "model_not_found",
        }
    for path, params in [("/backend-api/codex/models", {}), ("/v1/models", {"client_version": "0.144.3"})]:
        native = await client.get(path, params=params, headers=headers)
        assert native.status_code == 200
        data = native.json()
        CodexModelsResponse.model_validate(data)
        assert set(data) == {"models", "object", "data"}
        assert data["object"] == "list"
        assert {item["id"] for item in data["data"]} == expected
        entries = {item["slug"]: item for item in data["models"]}
        if scope != "other":
            assert entries[SPARK]["visibility"] == ("hide" if catalog == "withdrawn" else "list")
            assert entries[SPARK]["supported_in_api"] is (catalog != "unsupported")
        else:
            assert SPARK not in entries


@pytest.mark.parametrize(
    ("plan", "eligible"),
    [("pro", True), ("prolite", True), ("self_serve_business_prolite", True), ("plus", False), ("free", False)],
)
async def test_literal_spark_declared_pro_plan_equivalence_uses_sqlite_accounts(db_setup, plan: str, eligible: bool):
    """Accepted local plan policy, not a current provider entitlement claim."""
    del db_setup
    accounts = await _seed_accounts([plan])
    registry = get_model_registry()
    await registry.update({"pro": [_provider_model(SPARK)]})
    result = _filter_accounts_for_model_with_catalog_evidence(accounts, SPARK, registry=registry)
    assert [account.id for account in result.accounts] == ([accounts[0].id] if eligible else [])
    assert accounts[0].plan_type == plan
    await registry.update(
        {"pro": []}, per_account_results={accounts[0].id: (plan, [])}, active_account_plans={accounts[0].id: plan}
    )
    assert registry.is_suppressed_model(SPARK) is True
    suppressed = _filter_accounts_for_model_with_catalog_evidence(accounts, SPARK, registry=registry)
    assert suppressed.accounts == []
