# Design

Use an explicit non-null boolean with Python and database defaults false. Add the column default false, then backfill rows that exist during migration to true. New creates and raw imports that omit it stay false. Updates carry an explicit field-set marker; strict JSON booleans reject null and coercions. Unknown fields retain DashboardModel ignore behavior.

Keep Daybreak transport refusal ahead of the permission check to preserve the existing 400 contract. Check permission before account lookup or redeem coordination. Reuse the existing API-key cache invalidation on updates. No independent usage-section or inference policy changes.

Downgrade removes the permission; re-upgrade treats all then-existing keys as compatibility keys. This deliberately restores old behavior and does not preserve post-upgrade hardening across downgrade. Existing monitoring keys are NOT automatically hardened. No live update is part of this candidate.
