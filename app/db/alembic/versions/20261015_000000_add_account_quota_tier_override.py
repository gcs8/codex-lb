"""Add an owner-set subscription tier override to accounts.

Revision ID: 20261015_000000_add_account_quota_tier_override
Revises: 20260918_000000_merge_scim_and_overflow_heads
Create Date: 2026-10-15

The auth plan claim (``pro``/``prolite``) can't tell subscription tiers apart:
a grandfathered Pro 200 (20x Plus until 2026-10-29) and a new Pro 200 (10x)
both report ``pro``. Both columns are nullable with no default, so existing
rows keep the plan-derived capacity and the change is rolling-safe: older
replicas never read them.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261015_000000_add_account_quota_tier_override"
down_revision = "20260918_000000_merge_scim_and_overflow_heads"
branch_labels = None
depends_on = None

_TABLE = "accounts"
_MULTIPLIER = "quota_tier_multiplier"
_EXPIRES_AT = "quota_tier_multiplier_expires_at"


def _columns() -> set[str]:
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table(_TABLE):
        return set()
    return {str(column["name"]) for column in inspector.get_columns(_TABLE)}


def upgrade() -> None:
    existing = _columns()
    if not existing:
        return
    missing = [name for name in (_MULTIPLIER, _EXPIRES_AT) if name not in existing]
    if not missing:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        if _MULTIPLIER in missing:
            batch_op.add_column(sa.Column(_MULTIPLIER, sa.Float(), nullable=True))
        if _EXPIRES_AT in missing:
            batch_op.add_column(sa.Column(_EXPIRES_AT, sa.DateTime(), nullable=True))


def downgrade() -> None:
    present = [name for name in (_EXPIRES_AT, _MULTIPLIER) if name in _columns()]
    if not present:
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        for name in present:
            batch_op.drop_column(name)
