from __future__ import annotations

import os

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text

from app.db.migrate import _build_alembic_config, check_schema_drift, run_upgrade
from app.db.migration_url import to_sync_database_url

pytestmark = pytest.mark.integration
PARENT = "20261015_000000_add_account_quota_tier_override"
HEAD = "20261015_010000_add_reset_credit_key_permission"


def _insert(engine, key_id):
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO api_keys (id, name, key_hash, key_prefix, is_active, created_at) "
                "VALUES (:id, :id, :id, :id, true, CURRENT_TIMESTAMP)"
            ),
            {"id": key_id},
        )


def _permission(engine, key_id):
    with engine.connect() as conn:
        return bool(
            conn.execute(
                text("SELECT allow_reset_credit_redeem FROM api_keys WHERE id=:id"), {"id": key_id}
            ).scalar_one()
        )


@pytest.mark.parametrize("populated", [False, True])
def test_reset_credit_permission_migration_roundtrip(tmp_path, populated):
    # Explicit opt-in only for a private fixture; ordinary tests always own a SQLite file.
    pg_url = os.environ.get("KEY_PERMISSION_MIGRATION_DATABASE_URL")
    url = pg_url or f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}"
    engine = create_engine(to_sync_database_url(url))
    try:
        if pg_url:
            with engine.begin() as conn:
                conn.execute(text("DROP SCHEMA public CASCADE"))
                conn.execute(text("CREATE SCHEMA public"))
        if populated:
            run_upgrade(url, PARENT, bootstrap_legacy=False)
            _insert(engine, "legacy-monitor")
        result = run_upgrade(url, bootstrap_legacy=False)
        assert result.current_revision == HEAD
        assert check_schema_drift(url) == ()
        if populated:
            assert _permission(engine, "legacy-monitor") is True
        _insert(engine, "imported-default")
        assert _permission(engine, "imported-default") is False
        with engine.begin() as conn:
            conn.execute(text("UPDATE api_keys SET allow_reset_credit_redeem=false WHERE id='imported-default'"))
        # A no-op upgrade must not re-grant a hardened key.
        run_upgrade(url, bootstrap_legacy=False)
        assert _permission(engine, "imported-default") is False
        command.downgrade(_build_alembic_config(url), PARENT)
        assert "allow_reset_credit_redeem" not in {column["name"] for column in inspect(engine).get_columns("api_keys")}
        run_upgrade(url, bootstrap_legacy=False)
        assert _permission(engine, "imported-default") is True
        _insert(engine, "after-roundtrip")
        assert _permission(engine, "after-roundtrip") is False
        assert check_schema_drift(url) == ()
    finally:
        engine.dispose()
