"""Persist reset-credit redemption permission without changing existing keys' access.

Revision ID: 20261015_010000_add_reset_credit_key_permission
Revises: 20261015_000000_add_account_quota_tier_override
Create Date: 2026-10-15

Sequenced after the account tier-override migration (gcs8/codex-lb#7) so the
graph keeps a single head. Existing keys keep redemption (backfilled true);
monitoring keys must be revoked explicitly after deploy.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261015_010000_add_reset_credit_key_permission"
down_revision = "20261015_000000_add_account_quota_tier_override"
branch_labels = None
depends_on = None

_TABLE = "api_keys"
_COLUMN = "allow_reset_credit_redeem"


def _columns() -> set[str] | None:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        return None
    return {str(column["name"]) for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    columns = _columns()
    if columns is None or _COLUMN in columns:
        # Missing table (nothing to grant) or an interrupted earlier run already
        # added the column: never re-run the backfill, which would re-grant
        # redemption to keys hardened since.
        return
    op.add_column(
        _TABLE,
        sa.Column(_COLUMN, sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Compatibility only: existing monitoring keys are NOT automatically hardened.
    op.execute(sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = true"))


def downgrade() -> None:
    columns = _columns()
    if not columns or _COLUMN not in columns:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.drop_column(_COLUMN)
